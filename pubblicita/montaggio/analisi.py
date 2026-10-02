"""Rilevamento dei tagli con il filtro ``scene`` di ffmpeg."""
from __future__ import annotations

import re
import subprocess

from . import media

_RE_T = re.compile(r"pts_time:([0-9.]+)")
_RE_S = re.compile(r"lavfi\.scene_score=([0-9.]+)")


def detect_cuts(video: str, crop: str | None = None, threshold: float = 0.3,
                min_gap_frames: int = 3, fps: int = media.FPS) -> dict:
    """Restituisce i tagli (primo frame di ogni nuovo shot) e le durate degli shot.

    ``crop`` nel formato ffmpeg ``w:h:x:y`` (es. il solo pannello inferiore dello spot).
    Rilevamenti più vicini di ``min_gap_frames`` vengono fusi (tiene il punteggio più alto).
    """
    info = media.probe(video)
    vf = [f"fps={fps}"]
    if crop:
        vf.append(f"crop={crop}")
    vf += [f"select='gt(scene\\,{threshold})'", "metadata=print"]
    cmd = [media.FFMPEG, "-v", "info", "-nostdin", "-i", str(video), "-an",
           "-vf", ",".join(vf), "-f", "null", "-"]
    proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if proc.returncode != 0:
        raise media.MediaError(proc.stderr.decode("utf-8", "replace")[-2000:])
    raw = []
    t = None
    for line in proc.stderr.decode("utf-8", "replace").splitlines():
        m = _RE_T.search(line)
        if m:
            t = float(m.group(1))
            continue
        m = _RE_S.search(line)
        if m and t is not None:
            raw.append((int(round(t * fps)), float(m.group(1))))
            t = None
    merged: list[tuple[int, float]] = []
    for f, s in raw:
        if merged and f - merged[-1][0] < min_gap_frames:
            if s > merged[-1][1]:
                merged[-1] = (f, s)
            continue
        merged.append((f, s))
    total = info.frames_at(fps)
    bounds = [0] + [f for f, _ in merged if 0 < f < total] + [total]
    durations = [b - a for a, b in zip(bounds, bounds[1:])]
    return {
        "video": str(video),
        "crop": crop,
        "threshold": threshold,
        "fps": fps,
        "total_frames": total,
        "cuts": [{"frame": f, "s": round(f / fps, 4), "score": round(s, 3)} for f, s in merged],
        "durations_frames": durations,
    }
