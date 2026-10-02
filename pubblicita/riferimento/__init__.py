"""Analisi dello spot di riferimento: dati testuali per costruire il nostro spot.

Il riferimento e' il reel «26 shots, cut to 115 BPM» (blockout Blender sopra, finale AI sotto).
Qui ci sono solo testo e numeri, nessun media: la descrizione completa e' in ``ANALISI.md``,
i dati in ``shots_riferimento.json`` (shot, setup ricorrenti, musica, ricetta per un nuovo soggetto).

Uso::

    from pubblicita.riferimento import carica, durate_frame
    dati = carica()
    dati["shots"][11]["bottom"]        # descrizione del pannello finale dello shot 12
    durate_frame()                     # [8, 6, 6, 6, 14, ...] somma 336
    durate_frame("mezzi_battiti")      # stessi tagli spostati sulla griglia di mezzo battito
"""
from __future__ import annotations

import copy
import json
from functools import lru_cache
from pathlib import Path

PERCORSO_DATI = Path(__file__).with_name("shots_riferimento.json")
PERCORSO_ANALISI = Path(__file__).with_name("ANALISI.md")


@lru_cache(maxsize=1)
def _dati() -> dict:
    return json.loads(PERCORSO_DATI.read_text(encoding="utf-8"))


def carica() -> dict:
    """Copia dei dati di ``shots_riferimento.json`` (modificabile senza effetti collaterali)."""
    return copy.deepcopy(_dati())


def durate_frame(griglia: str = "riferimento") -> list[int]:
    """Durate dei 26 shot in frame a 24 fps.

    ``griglia="riferimento"``: durate misurate sul reel; ``"mezzi_battiti"``: tagli quantizzati
    sul mezzo battito a 115 BPM (vedi la ricetta in ANALISI.md). Entrambe sommano a 336 frame.
    """
    d = _dati()
    if griglia == "riferimento":
        return [s["frames"] for s in d["shots"]]
    if griglia == "mezzi_battiti":
        return [s["frames_mezzi_battiti"] for s in d["ricetta"]["slot"]]
    raise ValueError(f"griglia sconosciuta: {griglia!r} (usa 'riferimento' o 'mezzi_battiti')")


def shot_per_setup(sorgente: str = "riferimento") -> dict[str, list[int]]:
    """Numeri degli shot raggruppati per setup (``S01``..) o per setup della ricetta (``R01``..)."""
    d = _dati()
    if sorgente == "riferimento":
        return {k: list(v["shots"]) for k, v in d["setups"].items()}
    if sorgente == "ricetta":
        return {k: list(v["slot"]) for k, v in d["ricetta"]["setups"].items()}
    raise ValueError(f"sorgente sconosciuta: {sorgente!r} (usa 'riferimento' o 'ricetta')")
