"""Dalla timeline risolta alle due tracce dei pannelli (top.mp4 / bottom.mp4).

Ogni traccia è un solo passaggio ffmpeg: un ingresso per shot, una catena di filtri per
shot (conforma a 24 fps → trim su ``in`` → velocità → scala «cover» → durata esatta) e
un ``concat`` finale. Le durate sono garantite al frame: ogni segmento termina con
``tpad`` + ``trim=end_frame=N``.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

from . import media
from .edl import Shot, Source, Timeline

log = logging.getLogger(__name__)

CRF_INTERMEDIO = 10


def _segment(k: int, src: Source, frames: int, w: int, h: int) -> tuple[list[str], str]:
    """Argomenti d'ingresso e catena di filtri per un segmento di ``frames`` frame."""
    fps = media.FPS
    cover = media.cover_filter(w, h)
    pad = f"tpad=stop_mode=clone:stop={frames},trim=end_frame={frames},setpts=PTS-STARTPTS"
    if src.src is None:  # segnaposto a tinta unita
        dur = frames / fps + 1
        args = ["-f", "lavfi", "-i", f"color=c={src.color}:s={w}x{h}:r={fps}:d={dur:.3f}"]
        chain = f"[{k}:v]format=yuv420p,{pad}[v{k}]"
        return args, chain
    if src.src.suffix.lower() in media.IMAGE_EXT:
        dur = frames / fps + 1
        args = ["-loop", "1", "-framerate", str(fps), "-t", f"{dur:.3f}", "-i", str(src.src)]
        # immagine RGB → YUV con matrice BT.709 esplicita (come i clip video)
        chain = (f"[{k}:v]scale={w}:{h}:force_original_aspect_ratio=increase:flags=lanczos"
                 f":out_color_matrix=bt709:out_range=tv,crop={w}:{h},setsar=1,format=yuv420p,"
                 f"fps={fps},{pad}[v{k}]")
        return args, chain
    args = ["-i", str(src.src)]
    steps = [f"fps={fps}", f"trim=start_frame={src.in_frame}", "setpts=PTS-STARTPTS"]
    if abs(src.speed - 1.0) > 1e-9:
        steps += [f"setpts=PTS/{src.speed:.6f}", f"fps={fps}"]
    steps += [cover, "format=yuv420p", pad]
    return args, f"[{k}:v]" + ",".join(steps) + f"[v{k}]"


def render_track(shots: list[Shot], track: str, size: tuple[int, int], out: Path,
                 crf: int = CRF_INTERMEDIO, preset: str = "fast") -> Path:
    w, h = size
    inputs: list[str] = []
    chains: list[str] = []
    for k, shot in enumerate(shots):
        src = shot.top if track == "top" else shot.bottom
        args, chain = _segment(k, src, shot.frames, w, h)
        inputs += args
        chains.append(chain)
    n = len(shots)
    graph = ";".join(chains) + ";" + "".join(f"[v{k}]" for k in range(n)) + f"concat=n={n}:v=1:a=0[out]"
    out.parent.mkdir(parents=True, exist_ok=True)
    cmd = [media.FFMPEG, "-y", "-v", "error", "-nostdin", *inputs,
           "-filter_complex", graph, "-map", "[out]", "-an",
           "-c:v", "libx264", "-preset", preset, "-crf", str(crf), "-pix_fmt", "yuv420p",
           "-r", str(media.FPS), "-fps_mode", "cfr", *media.COLOR_TAGS,
           "-movflags", "+faststart", str(out)]
    log.info("render traccia %s: %d shot → %s", track, n, out)
    media.run(cmd, f"ffmpeg (traccia {track})")
    return out


def render_audio(tl: Timeline, out: Path) -> Path | None:
    """Ritaglia (o allunga con silenzio) l'audio dell'EDL alla durata esatta dello spot."""
    if tl.audio_src is None:
        return None
    dur = tl.duration_s
    off = tl.audio_offset_s
    pre = ["-ss", f"{off:.4f}"] if off > 0 else []
    filt = "apad"
    if off < 0:
        ms = int(round(-off * 1000))
        filt = f"adelay={ms}:all=1,apad"
    cmd = [media.FFMPEG, "-y", "-v", "error", "-nostdin", *pre, "-i", str(tl.audio_src),
           "-vn", "-af", filt, "-t", f"{dur:.6f}", "-ar", "48000", "-ac", "2",
           "-c:a", "pcm_s16le", str(out)]
    media.run(cmd, "ffmpeg (audio)")
    return out


def render(tl: Timeline, out_dir: str | Path, crf: int = CRF_INTERMEDIO, preset: str = "fast") -> dict:
    """Scrive ``top.mp4``, ``bottom.mp4``, ``timeline.json`` e (se c'è) ``audio.wav``."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    res = {
        "top": render_track(tl.shots, "top", tl.size, out_dir / "top.mp4", crf, preset),
        "bottom": render_track(tl.shots, "bottom", tl.size, out_dir / "bottom.mp4", crf, preset),
        "audio": render_audio(tl, out_dir / "audio.wav"),
    }
    tj = out_dir / "timeline.json"
    tj.write_text(json.dumps(tl.to_json(), indent=2, ensure_ascii=False), encoding="utf-8")
    res["timeline"] = tj
    return res
