"""Impaginazione 9:16: sfondo animato, intestazione, due pannelli video, etichette, barre.

Strategia: tutto ciò che non cambia (tinta + ombra, maschere degli angoli, etichette) è
calcolato una sola volta; per ogni frame si disegnano solo le linee dello sfondo,
l'intestazione (animata nel primo secondo, poi da cache), i due pannelli e le barre.
I pannelli arrivano già scalati «cover» da due processi ffmpeg (rgb24 su pipe), il
risultato va a un terzo ffmpeg (libx264 + AAC). Nessuna casualità: stesso input, stesso
output.
"""
from __future__ import annotations

import logging
import math
import queue
import subprocess
import threading
import time
from pathlib import Path

import numpy as np

from pubblicita.montaggio import media

from . import grafica, sfondo
from .header import Header

log = logging.getLogger(__name__)


class Panel:
    def __init__(self, name: str, cfg: dict, common: dict):
        self.name = name
        x, y, w, h = cfg["box"]
        self.x, self.y, self.w, self.h = int(x), int(y), int(w), int(h)
        self.r = float(cfg.get("radius", common["radius"]))
        self.mask = grafica.round_rect_mask(self.w, self.h, self.r)
        c = int(math.ceil(self.r)) + 1
        self.corners = [(0, 0), (self.w - c, 0), (0, self.h - c), (self.w - c, self.h - c)]
        self.c = c
        # etichetta
        lab = cfg.get("label")
        self.label = None
        if lab and lab.get("items"):
            style = grafica_style(common["label_style"], lab.get("style", {}))
            layer = grafica.label_layer(lab["items"], style)
            m = int(style.get("margin", 2))
            ox, oy = style["offset"]
            self.label = (layer, self.x + int(ox) - m, self.y + int(oy) - m)
        # barra di avanzamento
        pb = dict(common["progress"])
        pb.update(cfg.get("progress", {}))
        self.pb = pb if pb.get("enabled", True) else None
        if self.pb:
            ph = int(pb["height"])
            self.pb_rows = slice(self.h - ph, self.h)
            self.pb_mask = self.mask[self.pb_rows].copy()
            self.pb_track = np.asarray(pb["track_color"], np.float32)
            self.pb_track_a = float(pb["track_opacity"])
            self.pb_color = np.asarray(pb.get("color", (233, 133, 26)), np.float32)

    def composite(self, frame: np.ndarray, content: np.ndarray, progress: float) -> None:
        x, y, w, h, c = self.x, self.y, self.w, self.h, self.c
        saved = [frame[y + cy:y + cy + c, x + cx:x + cx + c].astype(np.float32) for cx, cy in self.corners]
        frame[y:y + h, x:x + w] = content
        for (cx, cy), under in zip(self.corners, saved):
            m = self.mask[cy:cy + c, cx:cx + c, None]
            top = content[cy:cy + c, cx:cx + c].astype(np.float32)
            frame[y + cy:y + cy + c, x + cx:x + cx + c] = (top * m + under * (1 - m) + 0.5).astype(np.uint8)
        if self.label:
            layer, lx, ly = self.label
            grafica.over(frame, layer, lx, ly)
        if self.pb:
            self._progress(frame, progress)

    def _progress(self, frame: np.ndarray, p: float) -> None:
        y0 = self.y + self.pb_rows.start
        region = frame[y0:self.y + self.h, self.x:self.x + self.w].astype(np.float32)
        under = region.copy()
        a_t = self.pb_track_a
        region = region * (1 - a_t) + self.pb_track * a_t
        fill_w = self.w * min(max(p, 0.0), 1.0)
        cov = np.clip(fill_w - np.arange(self.w, dtype=np.float32), 0.0, 1.0)[None, :, None]
        region = region * (1 - cov) + self.pb_color * cov
        m = self.pb_mask[..., None]
        region = region * m + under * (1 - m)
        frame[y0:self.y + self.h, self.x:self.x + self.w] = (region + 0.5).astype(np.uint8)


def grafica_style(base: dict, over: dict) -> dict:
    s = dict(base)
    s.update(over or {})
    return s


class Compositor:
    """Compone i frame della tela a partire dal layout risolto."""

    def __init__(self, cfg: dict):
        self.cfg = cfg
        cv = cfg["canvas"]
        self.W, self.H, self.fps = int(cv["width"]), int(cv["height"]), int(cv.get("fps", 24))
        pcfg = cfg["panels"]
        names = [n for n in ("top", "bottom") if n in pcfg]
        self.panels = {n: Panel(n, pcfg[n], pcfg) for n in names}
        bgc = cfg["background"]
        base = sfondo.base_image(bgc, self.W, self.H)
        sh = pcfg.get("shadow")
        if sh and sh.get("opacity", 0) > 0:
            alpha = grafica.shadow_alpha(self.W, self.H, [pcfg[n]["box"] for n in names],
                                         pcfg["radius"], sh.get("offset", (0, 0)), sh.get("blur", 0),
                                         sh["opacity"], sh.get("spread", 0))
            col = np.asarray(sh.get("color", (0, 0, 0)), np.float32)
            self.shade = (1.0 - alpha).astype(np.float32)
            base = base * self.shade[..., None] + col * alpha[..., None]
        else:
            self.shade = None
        self.bg_static = np.clip(base + 0.5, 0, 255).astype(np.uint8)
        wc = bgc.get("waves")
        self.waves = sfondo.Waves(wc, self.W, self.H) if wc and wc.get("lines") else None
        self.header = Header(cfg["header"]) if cfg.get("header") else None

    def frame(self, n: int, total: int, contents: dict) -> np.ndarray:
        t = n / self.fps
        fr = self.bg_static.copy()
        if self.waves is not None:
            self.waves.draw(fr, t, self.shade)
        if self.header is not None:
            self.header.draw(fr, t)
        p = n / (total - 1) if total > 1 else 1.0  # 0 al primo frame, pieno all'ultimo
        for name, panel in self.panels.items():
            c = contents.get(name)
            if c is not None:
                panel.composite(fr, c, p)
        return fr


# ---------------------------------------------------------------- I/O video

class FrameReader:
    """Decodifica un video in frame rgb24 già scalati «cover» (thread di prefetch)."""

    def __init__(self, path: str | Path, w: int, h: int, fps: int = 24, prefetch: int = 6):
        self.w, self.h = w, h
        vf = f"fps={fps},{media.cover_filter(w, h)},format=rgb24"
        cmd = [media.FFMPEG, "-v", "error", "-nostdin", "-i", str(path), "-an", "-vf", vf,
               "-f", "rawvideo", "-pix_fmt", "rgb24", "-"]
        self.proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.q: queue.Queue = queue.Queue(maxsize=prefetch)
        self.last = None
        self.th = threading.Thread(target=self._run, daemon=True)
        self.th.start()

    def _run(self):
        size = self.w * self.h * 3
        while True:
            buf = self.proc.stdout.read(size)
            if len(buf) < size:
                self.q.put(None)
                return
            self.q.put(np.frombuffer(buf, np.uint8).reshape(self.h, self.w, 3))

    def next(self) -> np.ndarray:
        """Frame successivo; a sorgente finita ripete l'ultimo (tiene la posa)."""
        if self.q is not None:
            f = self.q.get()
            if f is None:
                self.q = None
            else:
                self.last = f
        if self.last is None:
            raise media.MediaError("il video del pannello non contiene frame")
        return self.last

    def close(self):
        try:
            self.proc.kill()
        except Exception:
            pass
        self.proc.wait()


def _encoder(out: Path, W: int, H: int, fps: int, duration: float, audio: str | None,
             audio_from: str | None, enc: dict, fade_out: float, mute_track: bool):
    cmd = [media.FFMPEG, "-y", "-v", "error", "-nostdin",
           "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(fps), "-i", "-"]
    amap = None
    if audio:
        cmd += ["-i", str(audio)]
        amap = "1:a:0"
    elif audio_from:
        cmd += ["-i", str(audio_from)]
        amap = "1:a:0"
    elif mute_track:
        cmd += ["-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo"]
        amap = "1:a:0"
    cmd += ["-map", "0:v:0"]
    if amap:
        cmd += ["-map", amap]
    cmd += ["-vf", "scale=out_color_matrix=bt709:out_range=tv,format=yuv420p",
            "-c:v", "libx264", "-preset", enc.get("preset", "medium"), "-crf", str(enc.get("crf", 16)),
            "-pix_fmt", "yuv420p", "-profile:v", "high", *media.COLOR_TAGS]
    if amap:
        af = ["apad"]
        if (audio or audio_from) and fade_out > 0 and duration > fade_out:
            af.append(f"afade=t=out:st={duration - fade_out:.4f}:d={fade_out:.4f}")
        cmd += ["-af", ",".join(af), "-c:a", "aac", "-b:a", enc.get("audio_bitrate", "192k"),
                "-ar", "48000", "-ac", "2"]
    cmd += ["-t", f"{duration:.6f}", "-movflags", "+faststart", str(out)]
    return subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE)


def compose(top: str | Path, bottom: str | Path, out: str | Path, cfg: dict,
            audio: str | Path | None = None, audio_from_bottom: bool = False,
            duration: float | None = None, mute_track: bool = True,
            stills: list[float] | None = None, progress_cb=None) -> dict:
    """Compone lo spot. Con ``stills`` scrive solo i PNG dei tempi indicati (anteprima)."""
    comp = Compositor(cfg)
    fps = comp.fps
    out = Path(out)
    if duration is None:
        duration = media.probe(bottom).frames_at(fps) / fps
    total = int(round(duration * fps))
    if total < 1:
        raise ValueError("durata nulla")
    duration = total / fps
    readers = {}
    try:
        for name, src in (("top", top), ("bottom", bottom)):
            if name in comp.panels and src is not None:
                p = comp.panels[name]
                readers[name] = FrameReader(src, p.w, p.h, fps)
        wanted = None
        if stills:
            wanted = {min(total - 1, max(0, int(round(s * fps)))): s for s in stills}
            last = max(wanted)
        enc = None
        if wanted is None:
            out.parent.mkdir(parents=True, exist_ok=True)
            afrom = str(bottom) if audio_from_bottom and media.probe(bottom).has_audio else None
            enc = _encoder(out, comp.W, comp.H, fps, duration, str(audio) if audio else None, afrom,
                           cfg.get("encode", {}), float(cfg.get("audio", {}).get("fade_out_s", 0.5)),
                           mute_track)
        t0 = time.time()
        written = []
        for n in range(total if wanted is None else last + 1):
            contents = {k: r.next() for k, r in readers.items()}
            if wanted is not None and n not in wanted:
                continue
            fr = comp.frame(n, total, contents)
            if wanted is None:
                try:
                    enc.stdin.write(fr.tobytes())
                except BrokenPipeError:
                    break
            else:
                from PIL import Image
                p = out.with_name(f"{out.stem}_{wanted[n]:.2f}s.png") if len(wanted) > 1 else out
                p.parent.mkdir(parents=True, exist_ok=True)
                Image.fromarray(fr).save(p)
                written.append(p)
            if progress_cb:
                progress_cb(n + 1, total)
        if enc is not None:
            enc.stdin.close()
            err = enc.stderr.read().decode("utf-8", "replace")
            if enc.wait() != 0:
                raise media.MediaError("encoder ffmpeg fallito:\n" + err[-2000:])
            written.append(out)
        dt = time.time() - t0
        log.info("composti %d frame in %.1f s (%.1f fps)", total, dt, total / max(dt, 1e-6))
        return {"frames": total, "duration_s": duration, "outputs": written, "seconds": dt}
    finally:
        for r in readers.values():
            r.close()
