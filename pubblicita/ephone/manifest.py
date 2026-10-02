"""Manifest batch per i clip Seedance.

Struttura::

    {
      "variabili": {"soggetto": "...", "stile": "..."},      # opzionale
      "defaults": {"model": "...", "resolution": "1080p", "aspect_ratio": "16:9",
                   "duration": 5, "generate_audio": false, "watermark": false},
      "shots": [{"id": "s01", "prompt": "... $soggetto ... $stile", "duration": 5, ...}]
    }

- ogni shot eredita ``defaults`` (le liste si sostituiscono, non si uniscono);
- nei prompt ``$nome`` / ``${nome}`` si sostituiscono con ``variabili``: il soggetto dello
  spot si cambia in un punto solo;
- le chiavi che iniziano con ``_`` sono commenti e vengono ignorate;
- i percorsi relativi delle immagini sono relativi alla cartella del manifest;
- ``reference_videos``/``reference_audio`` accettano anche ``{"url": ..., "duration_s": 5}``
  per far verificare i limiti di durata e affinare la stima dei costi.
"""
from __future__ import annotations

import json
import string
from dataclasses import dataclass
from pathlib import Path

from .richieste import ErroreValidazione, RichiestaVideo, costruisci_video

CAMPI_MANIFEST = {"variabili", "defaults", "shots", "api", "descrizione", "titolo"}


@dataclass
class Manifest:
    percorso: Path | None
    richieste: list[RichiestaVideo]
    api: str | None = None

    @property
    def avvisi(self) -> list[str]:
        return [f"{r.id}: {a}" for r in self.richieste for a in r.avvisi]


def _sostituisci(testo: str, variabili: dict, problemi: list[str], ident: str) -> str:
    try:
        return string.Template(testo).substitute(variabili)
    except KeyError as e:
        problemi.append(f"{ident}: variabile ${e.args[0]} non definita in 'variabili'")
    except ValueError as e:
        problemi.append(f"{ident}: segnaposto non valido nel prompt ({e}); per un '$' letterale scrivi '$$'")
    return testo


def carica(percorso: str | Path, solo: set[str] | None = None) -> Manifest:
    """Legge e valida il manifest; ``solo`` limita la validazione agli shot indicati."""
    percorso = Path(percorso)
    try:
        dati = json.loads(percorso.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise ErroreValidazione([f"manifest non trovato: {percorso}"]) from None
    except json.JSONDecodeError as e:
        raise ErroreValidazione([f"JSON non valido in {percorso}: {e}"]) from None
    return da_dati(dati, percorso.resolve().parent, percorso, solo)


def da_dati(dati: dict, base: Path, percorso: Path | None = None, solo: set[str] | None = None) -> Manifest:
    """Valida tutto il manifest raccogliendo i problemi di ogni shot prima di fallire."""
    problemi: list[str] = []
    if not isinstance(dati, dict):
        raise ErroreValidazione(["il manifest deve essere un oggetto JSON"])
    ignoti = sorted(k for k in dati if k not in CAMPI_MANIFEST and not str(k).startswith("_"))
    if ignoti:
        problemi.append(f"campi sconosciuti nel manifest: {', '.join(ignoti)}")
    variabili = dati.get("variabili") or {}
    predefiniti = dati.get("defaults") or {}
    shots = dati.get("shots")
    api = dati.get("api")
    if not isinstance(variabili, dict) or not all(isinstance(v, (str, int, float)) for v in variabili.values()):
        problemi.append("'variabili' deve essere un oggetto di stringhe")
        variabili = {}
    if not isinstance(predefiniti, dict):
        problemi.append("'defaults' deve essere un oggetto")
        predefiniti = {}
    if "id" in predefiniti:
        problemi.append("'defaults' non può contenere 'id'")
    if api not in (None, "unified", "native"):
        problemi.append("'api' deve essere 'unified' o 'native'")
    if not isinstance(shots, list) or not shots:
        problemi.append("'shots' deve essere una lista non vuota")
        shots = []

    richieste, visti = [], set()
    for i, shot in enumerate(shots, 1):
        if not isinstance(shot, dict):
            problemi.append(f"shot #{i}: deve essere un oggetto")
            continue
        unito = {**predefiniti, **shot}
        ident = str(unito.get("id") or f"#{i}")
        if ident in visti:
            problemi.append(f"{ident}: id duplicato")
            continue
        visti.add(ident)
        if solo and ident not in solo:
            continue
        if isinstance(unito.get("prompt"), str):
            unito["prompt"] = _sostituisci(unito["prompt"], {k: str(v) for k, v in variabili.items()},
                                           problemi, ident)
        try:
            richieste.append(costruisci_video(unito, base))
        except ErroreValidazione as e:
            problemi.extend(f"{e.contesto or ident}: {p}" for p in e.problemi)
    if solo:
        mancanti = sorted(solo - visti)
        if mancanti:
            problemi.append(f"shot richiesti ma assenti nel manifest: {', '.join(mancanti)}")
    if problemi:
        raise ErroreValidazione(problemi, str(percorso) if percorso else "manifest")
    return Manifest(percorso, richieste, api)
