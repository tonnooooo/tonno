"""Impaginazione verticale 9:16 dello spot: sfondo animato, intestazione, due pannelli.

Uso::

    python3 -m pubblicita.compositore --top top.mp4 --bottom bottom.mp4 --out spot.mp4 [--audio a.wav]
    python3 -m pubblicita.compositore spot --edl edl.json --out spot.mp4

Il layout di default (misurato sul riferimento) è ``pubblicita/config/layout.json``.
"""
from .config import load_layout
from .render import Compositor, compose

__all__ = ["load_layout", "Compositor", "compose"]
