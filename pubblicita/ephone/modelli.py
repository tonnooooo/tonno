"""Catalogo dei modelli ePhone usati dalla pipeline: limiti di input e prezzi di listino.

I valori vengono dalle schede pubbliche del gateway
(``GET https://platform.ephone.ai/api/pricing/model_detail?model_name=...`` e
``GET https://platform.ephone.ai/api/pricing``), consultate a ottobre 2026.
Se il listino cambia basta aggiornare questa tabella: il resto del codice non
contiene numeri del fornitore.
"""
from __future__ import annotations

from dataclasses import dataclass, field

RAPPORTI_VIDEO = ("16:9", "9:16", "1:1", "4:3", "3:4", "21:9", "adaptive")
TIPI_TASK_OMNI = ("auto", "reference", "edit", "extend")
FORMATI_VIDEO = ("mp4", "mov")

DIMENSIONI_IMMAGINE = (
    "1K", "2K", "4K",
    "1024x1024", "2048x2048", "4096x4096",
    "2304x1728", "1728x2304", "2560x1440", "1440x2560",
)
RAPPORTI_IMMAGINE = ("1:1", "4:3", "3:4", "16:9", "9:16", "3:2", "2:3", "21:9")


@dataclass(frozen=True)
class ModelloVideo:
    nome: str
    etichetta: str
    alias: tuple[str, ...]
    risoluzioni: tuple[str, ...]
    durata_min: int
    durata_max: int
    max_ref_immagini: int
    max_ref_video: int
    max_ref_audio: int
    clip_ref_min_s: float
    clip_ref_max_s: float
    ref_totale_max_s: float
    # 2.5 accetta anche solo audio come riferimento; la serie 2.0 vuole almeno un'immagine o un video
    solo_audio: bool
    # campi presenti solo nello schema di 2.5
    supporta_tipo_task: bool
    supporta_formato: bool
    # CNY per 1M token: risoluzione -> (input senza video, input con video); "*" = tutte le altre
    prezzi_cny: dict = field(default_factory=dict)
    latenza_media_s: float = 0.0

    tipo = "video"

    def prezzo_milione(self, risoluzione: str, con_video: bool) -> float:
        coppia = self.prezzi_cny.get(risoluzione) or self.prezzi_cny["*"]
        return float(coppia[1] if con_video else coppia[0])


@dataclass(frozen=True)
class ModelloImmagine:
    nome: str
    etichetta: str
    alias: tuple[str, ...]
    max_riferimenti: int
    # prezzo a immagine in CNY: fino a ``soglia_pixel`` / oltre
    prezzo_piccola_cny: float
    prezzo_grande_cny: float
    soglia_pixel: int
    # riferimenti: il primo è gratuito, i successivi costano questo
    prezzo_ref_extra_cny: float
    watermark_predefinito: bool = True
    latenza_media_s: float = 0.0

    tipo = "immagine"


SEEDANCE_25 = ModelloVideo(
    nome="doubao-seedance-2-5-260628",
    etichetta="Seedance 2.5",
    alias=("doubao-seedance-2.5", "seedance-2.5", "seedance25"),
    risoluzioni=("480p", "720p", "1080p"),
    durata_min=4, durata_max=30,
    max_ref_immagini=30, max_ref_video=10, max_ref_audio=10,
    clip_ref_min_s=2, clip_ref_max_s=30, ref_totale_max_s=30,
    solo_audio=True, supporta_tipo_task=True, supporta_formato=True,
    prezzi_cny={"1080p": (77, 46), "*": (70, 42)},
    latenza_media_s=170,
)

SEEDANCE_20 = ModelloVideo(
    nome="doubao-seedance-2-0-260128",
    etichetta="Seedance 2.0",
    alias=("doubao-seedance-2.0", "seedance-2.0"),
    risoluzioni=("480p", "720p", "1080p", "4k"),
    durata_min=4, durata_max=15,
    max_ref_immagini=9, max_ref_video=3, max_ref_audio=3,
    clip_ref_min_s=2, clip_ref_max_s=15, ref_totale_max_s=15,
    solo_audio=False, supporta_tipo_task=False, supporta_formato=False,
    prezzi_cny={"4k": (26, 16), "1080p": (51, 31), "*": (46, 28)},
    latenza_media_s=280,
)

SEEDANCE_20_FAST = ModelloVideo(
    nome="doubao-seedance-2-0-fast-260128",
    etichetta="Seedance 2.0 Fast",
    alias=("doubao-seedance-2.0-fast", "seedance-2.0-fast"),
    risoluzioni=("480p", "720p"),
    durata_min=4, durata_max=15,
    max_ref_immagini=9, max_ref_video=3, max_ref_audio=3,
    clip_ref_min_s=2, clip_ref_max_s=15, ref_totale_max_s=15,
    solo_audio=False, supporta_tipo_task=False, supporta_formato=False,
    prezzi_cny={"*": (37, 22)},
)

SEEDANCE_20_MINI = ModelloVideo(
    nome="doubao-seedance-2-0-mini-260615",
    etichetta="Seedance 2.0 Mini",
    alias=("doubao-seedance-2.0-mini", "seedance-2.0-mini"),
    risoluzioni=("480p", "720p"),
    durata_min=4, durata_max=15,
    max_ref_immagini=9, max_ref_video=3, max_ref_audio=3,
    clip_ref_min_s=2, clip_ref_max_s=15, ref_totale_max_s=15,
    solo_audio=False, supporta_tipo_task=False, supporta_formato=False,
    prezzi_cny={"*": (23, 14)},
    latenza_media_s=93,
)

SEEDREAM_5_PRO = ModelloImmagine(
    nome="doubao-seedream-5-0-pro-260628",
    etichetta="Seedream 5.0 Pro",
    alias=("doubao-seedream-5.0-pro", "seedream-5-pro", "seedream-5.0-pro"),
    max_riferimenti=10,
    prezzo_piccola_cny=0.30,
    prezzo_grande_cny=0.60,
    soglia_pixel=2_360_000,
    prezzo_ref_extra_cny=0.02,
    watermark_predefinito=True,
    latenza_media_s=24,
)

# Modello "di servizio" per la libreria asset (gratuito, sincrono).
MODELLO_ASSET = "doubao-asset"

MODELLI_VIDEO = (SEEDANCE_25, SEEDANCE_20, SEEDANCE_20_FAST, SEEDANCE_20_MINI)
MODELLI_IMMAGINE = (SEEDREAM_5_PRO,)

VIDEO_PREDEFINITO = SEEDANCE_25
IMMAGINE_PREDEFINITA = SEEDREAM_5_PRO


def _indice(modelli) -> dict:
    indice = {}
    for m in modelli:
        indice[m.nome.lower()] = m
        for a in m.alias:
            indice[a.lower()] = m
    return indice


_INDICE_VIDEO = _indice(MODELLI_VIDEO)
_INDICE_IMMAGINE = _indice(MODELLI_IMMAGINE)


def modello_video(nome: str | None) -> ModelloVideo:
    """Risolve nome completo o alias; errore leggibile se il modello non è in catalogo."""
    if not nome:
        return VIDEO_PREDEFINITO
    m = _INDICE_VIDEO.get(str(nome).strip().lower())
    if m is None:
        noti = ", ".join(x.nome for x in MODELLI_VIDEO)
        raise ValueError(f"modello video sconosciuto: {nome!r} (noti: {noti})")
    return m


def modello_immagine(nome: str | None) -> ModelloImmagine:
    if not nome:
        return IMMAGINE_PREDEFINITA
    m = _INDICE_IMMAGINE.get(str(nome).strip().lower())
    if m is None:
        noti = ", ".join(x.nome for x in MODELLI_IMMAGINE)
        raise ValueError(f"modello immagine sconosciuto: {nome!r} (noti: {noti})")
    return m


def nomi_accettati(modello) -> set[str]:
    """Nome e alias in minuscolo, utili per cercare il modello nella lista di /v1/models."""
    return {modello.nome.lower(), *(a.lower() for a in modello.alias)}
