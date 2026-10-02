"""Utilità comuni attorno a ffmpeg/ffprobe (usate anche dal compositore)."""
from __future__ import annotations

import json
import math
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

FFMPEG = shutil.which("ffmpeg") or "ffmpeg"
FFPROBE = shutil.which("ffprobe") or "ffprobe"

FPS = 24
IMAGE_EXT = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff"}

# Tag colore BT.709 (gamma video, range limitato) per tutti gli output.
COLOR_TAGS = ["-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709", "-color_range", "tv"]


class MediaError(RuntimeError):
    """Errore di ffmpeg/ffprobe con la coda dello stderr già leggibile."""


@dataclass
class MediaInfo:
    path: Path
    width: int
    height: int
    fps: float
    duration: float
    has_audio: bool
    is_image: bool = False

    def frames_at(self, fps: int = FPS) -> int:
        """Numero di frame disponibili una volta conformata la sorgente a ``fps``."""
        if self.is_image:
            return 10 ** 9  # un'immagine fissa si può allungare quanto serve
        return int(math.floor(self.duration * fps + 0.5))


def run(cmd: list[str], what: str = "ffmpeg") -> subprocess.CompletedProcess:
    proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if proc.returncode != 0:
        tail = proc.stderr.decode("utf-8", "replace").strip().splitlines()[-15:]
        raise MediaError(f"{what} fallito (codice {proc.returncode}):\n" + "\n".join(tail))
    return proc


def probe(path: str | Path) -> MediaInfo:
    """Legge risoluzione, fps, durata e presenza di audio di un file."""
    p = Path(path)
    if not p.exists():
        raise MediaError(f"file inesistente: {p}")
    if p.suffix.lower() in IMAGE_EXT:
        out = run([FFPROBE, "-v", "error", "-select_streams", "v:0", "-show_entries",
                   "stream=width,height", "-of", "json", str(p)], "ffprobe")
        st = json.loads(out.stdout)["streams"][0]
        return MediaInfo(p, int(st["width"]), int(st["height"]), float(FPS), float("inf"), False, True)
    out = run([FFPROBE, "-v", "error", "-show_entries",
               "stream=codec_type,width,height,r_frame_rate,avg_frame_rate,duration,nb_frames:format=duration",
               "-of", "json", str(p)], "ffprobe")
    data = json.loads(out.stdout)
    streams = data.get("streams", [])
    v = next((s for s in streams if s.get("codec_type") == "video"), None)
    if v is None:
        raise MediaError(f"nessuna traccia video in {p}")
    has_audio = any(s.get("codec_type") == "audio" for s in streams)
    fps = _rate(v.get("avg_frame_rate")) or _rate(v.get("r_frame_rate")) or float(FPS)
    dur = _float(v.get("duration")) or _float(data.get("format", {}).get("duration"))
    nb = v.get("nb_frames")
    if not dur and nb and str(nb).isdigit():
        dur = int(nb) / fps
    if not dur:
        raise MediaError(f"durata non leggibile per {p}")
    return MediaInfo(p, int(v["width"]), int(v["height"]), fps, dur, has_audio)


def duration(path: str | Path) -> float:
    """Durata del contenitore in secondi (vale anche per file solo audio)."""
    out = run([FFPROBE, "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)], "ffprobe")
    return float(out.stdout.decode().strip())


def has_audio(path: str | Path) -> bool:
    out = run([FFPROBE, "-v", "error", "-select_streams", "a", "-show_entries", "stream=index",
               "-of", "csv=p=0", str(path)], "ffprobe")
    return bool(out.stdout.decode().strip())


def count_frames(path: str | Path) -> int:
    """Conta i frame decodificati (lento ma esatto: usato nei test e nelle verifiche)."""
    out = run([FFPROBE, "-v", "error", "-select_streams", "v:0", "-count_frames",
               "-show_entries", "stream=nb_read_frames", "-of", "csv=p=0", str(path)], "ffprobe")
    return int(out.stdout.decode().strip().split(",")[0])


def _rate(s: str | None) -> float | None:
    if not s or s in ("0/0", "N/A"):
        return None
    if "/" in s:
        a, b = s.split("/")
        return float(a) / float(b) if float(b) else None
    return float(s)


def _float(s) -> float | None:
    try:
        f = float(s)
        return f if f > 0 else None
    except (TypeError, ValueError):
        return None


def cover_filter(w: int, h: int) -> str:
    """Scala «a riempire» e ritaglia al centro (equivalente di object-fit: cover)."""
    return (f"scale={w}:{h}:force_original_aspect_ratio=increase:flags=lanczos,"
            f"crop={w}:{h},setsar=1")
