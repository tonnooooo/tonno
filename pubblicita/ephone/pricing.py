"""Stima dei costi ePhone (Seedance a token, Seedream a immagine).

Formula pubblicata dal gateway per Seedance:

    token ≈ (durata video in input + durata output) × larghezza × altezza × fps / 1024

con fps 24 e larghezza/altezza dell'output. Il costo è ``token × prezzo per 1M``,
moltiplicato per il coefficiente del gruppo "bytedance" (0.9). Si paga solo per i
task riusciti; il conteggio esatto è ``usage.completion_tokens`` nella risposta.
Con un video in input esiste anche un minimo di token non documentato: la stima
in quel caso può essere in difetto.

Cambio e coefficiente di gruppo si possono cambiare con le variabili d'ambiente
``EPHONE_CNY_PER_USD`` ed ``EPHONE_GROUP_RATIO``.
"""
from __future__ import annotations

import math
import os
import re
from dataclasses import dataclass, field

from .modelli import ModelloImmagine, ModelloVideo

FPS = 24
CAMBIO_CNY_USD = 7.0
COEFF_GRUPPO = 0.9

# Dimensioni di riferimento a 16:9; per gli altri rapporti si conserva il numero di pixel.
PIXEL_RIFERIMENTO = {
    "480p": (854, 480),
    "720p": (1280, 720),
    "1080p": (1920, 1080),
    "4k": (3840, 2160),
}


def cambio_cny_usd() -> float:
    return _float_env("EPHONE_CNY_PER_USD", CAMBIO_CNY_USD)


def coeff_gruppo() -> float:
    return _float_env("EPHONE_GROUP_RATIO", COEFF_GRUPPO)


def _float_env(nome: str, predefinito: float) -> float:
    valore = os.environ.get(nome, "").strip()
    if not valore:
        return predefinito
    try:
        x = float(valore)
    except ValueError:
        raise ValueError(f"{nome} deve essere un numero, trovato {valore!r}") from None
    if x <= 0:
        raise ValueError(f"{nome} deve essere positivo")
    return x


def rapporto_numerico(rapporto: str | None, rapporto_input: float | None = None) -> float:
    """``"16:9"`` -> 1.777…; ``adaptive`` segue il rapporto dell'input se noto, altrimenti 16:9."""
    if not rapporto or rapporto == "adaptive":
        return rapporto_input or 16 / 9
    a, b = rapporto.split(":")
    return float(a) / float(b)


def dimensioni_output(risoluzione: str, rapporto: str | None = "16:9",
                      rapporto_input: float | None = None) -> tuple[int, int]:
    """Dimensioni stimate dell'output (pari, a pixel costanti rispetto al 16:9 di riferimento)."""
    if risoluzione not in PIXEL_RIFERIMENTO:
        raise ValueError(f"risoluzione non prevista: {risoluzione!r}")
    w0, h0 = PIXEL_RIFERIMENTO[risoluzione]
    r = rapporto_numerico(rapporto, rapporto_input)
    if abs(r - 16 / 9) < 1e-3:
        return w0, h0
    pixel = w0 * h0
    w = int(round(math.sqrt(pixel * r) / 2) * 2)
    h = int(round(math.sqrt(pixel / r) / 2) * 2)
    return w, h


def token_stimati(durata_out_s: float, durata_in_s: float, larghezza: int, altezza: int,
                  fps: int = FPS) -> int:
    return int(round((durata_out_s + durata_in_s) * larghezza * altezza * fps / 1024))


def costo_token(modello: ModelloVideo, risoluzione: str, con_video: bool, token: int,
                cambio: float | None = None, gruppo: float | None = None) -> tuple[float, float]:
    """Costo (CNY, USD) per un numero di token già noto, ad es. ``usage.completion_tokens``."""
    cambio = cambio or cambio_cny_usd()
    gruppo = gruppo or coeff_gruppo()
    cny = token * modello.prezzo_milione(risoluzione, con_video) / 1_000_000 * gruppo
    return cny, cny / cambio


@dataclass
class Stima:
    descrizione: str
    token: int = 0
    prezzo_milione_cny: float = 0.0
    cny: float = 0.0
    usd: float = 0.0
    larghezza: int = 0
    altezza: int = 0
    durata_out_s: float = 0.0
    durata_in_s: float = 0.0
    note: list[str] = field(default_factory=list)

    def come_dict(self) -> dict:
        return {
            "descrizione": self.descrizione,
            "token": self.token,
            "prezzo_milione_cny": self.prezzo_milione_cny,
            "cny": round(self.cny, 4),
            "usd": round(self.usd, 4),
            "output": [self.larghezza, self.altezza] if self.larghezza else None,
            "durata_out_s": self.durata_out_s,
            "durata_in_s": self.durata_in_s,
            "note": list(self.note),
        }


def stima_video(modello: ModelloVideo, risoluzione: str, rapporto: str | None, durata: int | None,
                durata_input_s: float = 0.0, con_video: bool = False,
                rapporto_input: float | None = None, durata_auto_s: float | None = None,
                cambio: float | None = None, gruppo: float | None = None) -> Stima:
    """Stima di un singolo task video.

    ``durata`` None o -1 (scelta dal modello): si usa ``durata_auto_s`` se dato, altrimenti la
    durata del video in input (caso edit) o, in mancanza, il massimo del modello (stima prudente).
    """
    note = []
    if durata in (None, -1):
        if durata_auto_s:
            durata_out = float(durata_auto_s)
        elif con_video and durata_input_s:
            durata_out = float(durata_input_s)
        else:
            durata_out = float(modello.durata_max)
        note.append(f"durata scelta dal modello: stimati {durata_out:g} s")
    else:
        durata_out = float(durata)
    if rapporto in (None, "adaptive") and not rapporto_input:
        note.append("rapporto adaptive senza immagine di partenza: stimato 16:9")
    w, h = dimensioni_output(risoluzione, rapporto, rapporto_input)
    tok = token_stimati(durata_out, durata_input_s if con_video else 0.0, w, h)
    cny, usd = costo_token(modello, risoluzione, con_video, tok, cambio, gruppo)
    if con_video:
        note.append("input con video: il gateway applica un minimo di token non documentato")
    return Stima(
        descrizione=f"{modello.etichetta} {risoluzione} {rapporto or 'adaptive'} {durata_out:g}s",
        token=tok, prezzo_milione_cny=modello.prezzo_milione(risoluzione, con_video),
        cny=cny, usd=usd, larghezza=w, altezza=h,
        durata_out_s=durata_out, durata_in_s=durata_input_s if con_video else 0.0, note=note,
    )


_RE_WXH = re.compile(r"^(\d{2,5})x(\d{2,5})$")


def pixel_immagine(size: str | None, rapporto: str | None = None) -> int:
    """Numero di pixel atteso per ``size`` (1K/2K/4K oppure LxA)."""
    size = (size or "2K").strip()
    m = _RE_WXH.match(size.lower())
    if m:
        return int(m.group(1)) * int(m.group(2))
    lato = {"1K": 1024, "2K": 2048, "4K": 4096}.get(size.upper())
    if lato is None:
        raise ValueError(f"size non prevista: {size!r}")
    # con un rapporto diverso da 1:1 il modello mantiene circa lo stesso numero di pixel
    return lato * lato


def stima_immagine(modello: ModelloImmagine, size: str | None, rapporto: str | None = None,
                   n_riferimenti: int = 0, quante: int = 1,
                   cambio: float | None = None, gruppo: float | None = None) -> Stima:
    cambio = cambio or cambio_cny_usd()
    gruppo = gruppo or coeff_gruppo()
    px = pixel_immagine(size, rapporto)
    unitario = modello.prezzo_grande_cny if px > modello.soglia_pixel else modello.prezzo_piccola_cny
    extra = max(0, n_riferimenti - 1) * modello.prezzo_ref_extra_cny
    cny = (unitario + extra) * quante * gruppo
    note = [f"{px / 1e6:.2f} Mpx: fascia {'grande' if px > modello.soglia_pixel else 'piccola'}"]
    return Stima(
        descrizione=f"{modello.etichetta} {size or '2K'} ×{quante}",
        cny=cny, usd=cny / cambio, note=note,
    )


def somma(stime: list[Stima]) -> tuple[float, float]:
    return sum(s.cny for s in stime), sum(s.usd for s in stime)
