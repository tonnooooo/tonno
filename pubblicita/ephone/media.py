"""Preparazione dei media di input per Seedance/Seedream.

- immagini: URL pubblico, ``asset://ID``, data URI oppure file locale (convertito in data URI
  dopo i controlli di peso, lato e rapporto richiesti dal modello);
- video e audio: solo URL pubblico o ``asset://ID``. Il gateway non accetta video in base64 e
  un file locale non è raggiungibile dal fornitore: si dà un errore che spiega come ospitarlo.
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import io
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, UnidentifiedImageError

LIMITE_IMMAGINE_BYTE = 30 * 1024 * 1024
LATO_MIN, LATO_MAX = 300, 6000
RAPPORTO_MIN, RAPPORTO_MAX = 0.4, 2.5
FORMATI_DIRETTI = {"PNG": "image/png", "JPEG": "image/jpeg", "WEBP": "image/webp"}

SPIEGAZIONE_HOSTING = (
    "Il fornitore deve poter scaricare il file da solo: carica il file su uno storage con link "
    "pubblico HTTPS (bucket S3/R2/GCS, release GitHub, CDN…) e usa quell'URL, oppure registralo "
    "nella libreria asset con `python3 -m pubblicita.ephone asset upload --url <URL> --type {tipo}` "
    "e usa `asset://<ID>` (obbligatorio se il materiale contiene volti reali)."
)


class ErroreMedia(ValueError):
    pass


@dataclass
class InfoImmagine:
    larghezza: int
    altezza: int
    byte: int
    formato: str

    @property
    def rapporto(self) -> float:
        return self.larghezza / self.altezza


def e_url(valore: str) -> bool:
    return valore.startswith(("https://", "http://"))


def e_asset(valore: str) -> bool:
    return valore.startswith("asset://") and len(valore) > len("asset://")


def e_data_uri(valore: str) -> bool:
    return valore.startswith("data:")


def controlla_immagine(img: Image.Image, nbyte: int, origine: str) -> InfoImmagine:
    w, h = img.size
    problemi = []
    if nbyte > LIMITE_IMMAGINE_BYTE:
        problemi.append(f"pesa {nbyte / 1048576:.1f} MB (massimo 30 MB)")
    if min(w, h) < LATO_MIN or max(w, h) > LATO_MAX:
        problemi.append(f"è {w}×{h} px (ogni lato deve stare fra {LATO_MIN} e {LATO_MAX} px)")
    r = w / h if h else 0
    if not RAPPORTO_MIN <= r <= RAPPORTO_MAX:
        problemi.append(f"ha rapporto {r:.2f} (ammesso fra {RAPPORTO_MIN} e {RAPPORTO_MAX})")
    if problemi:
        raise ErroreMedia(f"immagine {origine}: " + "; ".join(problemi))
    return InfoImmagine(w, h, nbyte, img.format or "")


def _apri(dati: bytes, origine: str) -> Image.Image:
    try:
        img = Image.open(io.BytesIO(dati))
        img.load()
        return img
    except (UnidentifiedImageError, OSError) as e:
        raise ErroreMedia(f"immagine {origine}: formato non leggibile ({e})") from None


def immagine_in_data_uri(percorso: Path) -> tuple[str, InfoImmagine]:
    """File locale -> data URI base64, con controlli; i formati insoliti diventano PNG."""
    if not percorso.is_file():
        raise ErroreMedia(f"immagine non trovata: {percorso}")
    dati = percorso.read_bytes()
    img = _apri(dati, str(percorso))
    formato = (img.format or "").upper()
    if formato not in FORMATI_DIRETTI:
        buf = io.BytesIO()
        img.convert("RGBA" if "A" in img.getbands() else "RGB").save(buf, format="PNG")
        dati, formato = buf.getvalue(), "PNG"
    info = controlla_immagine(img, len(dati), str(percorso))
    info.formato = formato
    b64 = base64.b64encode(dati).decode("ascii")
    return f"data:{FORMATI_DIRETTI[formato]};base64,{b64}", info


def _decodifica_data_uri(valore: str) -> tuple[str, bytes]:
    try:
        intestazione, corpo = valore.split(",", 1)
    except ValueError:
        raise ErroreMedia("data URI malformato (manca la virgola)") from None
    mime = intestazione[5:].split(";")[0]
    if ";base64" not in intestazione:
        raise ErroreMedia("data URI senza codifica base64")
    try:
        return mime, base64.b64decode(corpo, validate=True)
    except (binascii.Error, ValueError):
        raise ErroreMedia("data URI con base64 non valido") from None


def prepara_immagine(valore, base: Path) -> tuple[str, InfoImmagine | None]:
    """Normalizza un riferimento immagine. Restituisce (valore da inviare, info se nota)."""
    if not isinstance(valore, str) or not valore.strip():
        raise ErroreMedia(f"riferimento immagine non valido: {valore!r}")
    valore = valore.strip()
    if e_url(valore) or e_asset(valore):
        return valore, None
    if e_data_uri(valore):
        mime, dati = _decodifica_data_uri(valore)
        if not mime.startswith("image/"):
            raise ErroreMedia(f"data URI di tipo {mime!r}: serve un'immagine")
        info = controlla_immagine(_apri(dati, "(data URI)"), len(dati), "(data URI)")
        return valore, info
    percorso = Path(valore).expanduser()
    if not percorso.is_absolute():
        percorso = base / percorso
    return immagine_in_data_uri(percorso)


def prepara_remoto(valore, tipo: str) -> str:
    """Video/audio: ammessi solo URL pubblici e ``asset://`` (audio anche come data URI)."""
    if not isinstance(valore, str) or not valore.strip():
        raise ErroreMedia(f"riferimento {tipo} non valido: {valore!r}")
    valore = valore.strip()
    if e_url(valore) or e_asset(valore):
        return valore
    tipo_asset = "Video" if tipo == "video" else "Audio"
    if e_data_uri(valore):
        if tipo == "audio":
            mime, dati = _decodifica_data_uri(valore)
            if not mime.startswith("audio/"):
                raise ErroreMedia(f"data URI di tipo {mime!r}: serve un audio")
            if len(dati) > 15 * 1024 * 1024:
                raise ErroreMedia("audio in data URI oltre 15 MB")
            return valore
        raise ErroreMedia("i video non si possono inviare in base64. "
                          + SPIEGAZIONE_HOSTING.format(tipo=tipo_asset))
    raise ErroreMedia(f"{tipo} locale non utilizzabile: {valore}. "
                      + SPIEGAZIONE_HOSTING.format(tipo=tipo_asset))


def riassumi_data_uri(valore: str) -> str:
    """Rappresentazione compatta di un data URI per ledger e sidecar."""
    intestazione = valore.split(",", 1)[0]
    corpo = valore[len(intestazione) + 1:]
    impronta = hashlib.sha256(corpo.encode("ascii", "ignore")).hexdigest()[:12]
    return f"{intestazione},<{len(corpo)} caratteri base64, sha256 {impronta}>"


def compatta(obj):
    """Copia profonda con i data URI sostituiti dal loro riassunto."""
    if isinstance(obj, str):
        return riassumi_data_uri(obj) if obj.startswith("data:") and len(obj) > 256 else obj
    if isinstance(obj, dict):
        return {k: compatta(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [compatta(v) for v in obj]
    return obj
