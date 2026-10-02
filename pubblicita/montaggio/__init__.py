"""Montaggio a tempo di musica: dall'EDL alle due tracce sincronizzate dei pannelli.

Uso tipico::

    python3 -m pubblicita.montaggio render --edl edl.json --out-dir pubblicita/output/montaggio
    python3 -m pubblicita.montaggio beats --bpm 115 --pattern "1,0.5,0.5,1"
    python3 -m pubblicita.montaggio analyze --video spot.mp4 --crop 1056:594:12:1070
"""
from .edl import EDLError, Timeline, load, resolve
from .ritmo import beats_table, boundaries, frames_per_beat

__all__ = ["EDLError", "Timeline", "load", "resolve", "beats_table", "boundaries",
           "frames_per_beat", "render_edl"]


def render_edl(edl_path, out_dir, crf: int = 10, preset: str = "fast") -> dict:
    """Valida l'EDL e scrive top.mp4, bottom.mp4, timeline.json (e audio.wav)."""
    from pathlib import Path

    from .render import render

    p = Path(edl_path)
    tl = resolve(load(p), base_dir=p.resolve().parent, edl_path=p)
    res = render(tl, out_dir, crf=crf, preset=preset)
    res["timeline_obj"] = tl
    return res
