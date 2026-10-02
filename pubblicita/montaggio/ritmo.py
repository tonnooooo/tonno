"""Matematica dei battiti: durate in battiti/frame → confini dei tagli senza deriva.

Il confine di ogni taglio si calcola sempre dalla posizione *cumulativa*:
``confine = round(battiti_cumulativi * 60 / bpm * fps)`` (arrotondamento «half up»),
quindi l'errore di arrotondamento non si accumula mai oltre mezzo frame.
I conti sono fatti con ``Fraction`` per evitare sorprese della virgola mobile.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from fractions import Fraction


def _frac(v) -> Fraction:
    if isinstance(v, Fraction):
        return v
    if isinstance(v, int):
        return Fraction(v)
    return Fraction(str(v))  # 0.1 → 1/10 esatto, non 3602879701896397/36028797018963968


def round_half_up(x: Fraction) -> int:
    return math.floor(x + Fraction(1, 2))


def frames_per_beat(bpm, fps: int = 24) -> Fraction:
    bpm = _frac(bpm)
    if bpm <= 0:
        raise ValueError("bpm deve essere positivo")
    return Fraction(60) / bpm * fps


@dataclass(frozen=True)
class Cut:
    index: int
    start_frame: int
    end_frame: int
    beats: float | None  # durata richiesta in battiti (None se data in frame)

    @property
    def frames(self) -> int:
        return self.end_frame - self.start_frame


def boundaries(durations: list[tuple[str, object]], bpm, fps: int = 24) -> list[Cut]:
    """``durations``: lista di ("frames", n) oppure ("beats", b).

    Gli shot in frame aggiungono esattamente n frame; quelli in battiti spostano la
    posizione cumulativa (frazionaria) e il confine è arrotondato una volta sola.
    """
    fpb = frames_per_beat(bpm, fps)
    pos = Fraction(0)
    start = 0
    cuts: list[Cut] = []
    for i, (kind, value) in enumerate(durations):
        if kind == "frames":
            n = _frac(value)
            if n.denominator != 1 or n <= 0:
                raise ValueError(f"shot {i + 1}: 'frames' deve essere un intero positivo")
            pos += n
            beats = None
        elif kind == "beats":
            b = _frac(value)
            if b <= 0:
                raise ValueError(f"shot {i + 1}: 'beats' deve essere positivo")
            pos += b * fpb
            beats = float(b)
        else:
            raise ValueError(f"tipo di durata sconosciuto: {kind}")
        end = round_half_up(pos)
        if end <= start:
            raise ValueError(f"shot {i + 1}: durata nulla dopo l'arrotondamento a {fps} fps")
        cuts.append(Cut(i, start, end, beats))
        start = end
    return cuts


def parse_pattern(pattern: str) -> list[Fraction]:
    """"1,0.5,1/2,2" → battiti come frazioni."""
    out = []
    for tok in pattern.replace(";", ",").split(","):
        tok = tok.strip()
        if not tok:
            continue
        out.append(Fraction(tok) if "/" in tok else _frac(tok))
    if not out:
        raise ValueError("pattern vuoto")
    return out


def beats_table(pattern: str, bpm, fps: int = 24) -> list[dict]:
    cuts = boundaries([("beats", b) for b in parse_pattern(pattern)], bpm, fps)
    return [
        {
            "shot": c.index + 1,
            "beats": c.beats,
            "start_frame": c.start_frame,
            "end_frame": c.end_frame,
            "frames": c.frames,
            "start_s": round(c.start_frame / fps, 4),
            "end_s": round(c.end_frame / fps, 4),
        }
        for c in cuts
    ]
