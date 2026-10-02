"""Validazione delle richieste e costruzione dei payload (formato unificato e nativo Ark).

Tutto quello che si può verificare senza spendere si verifica qui, prima di qualsiasi
chiamata: modalità esclusive, limiti del modello, durate, media locali.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from . import media, pricing
from .modelli import (
    DIMENSIONI_IMMAGINE, FORMATI_VIDEO, RAPPORTI_IMMAGINE, RAPPORTI_VIDEO, TIPI_TASK_OMNI,
    ModelloImmagine, ModelloVideo, modello_immagine, modello_video,
)

LIMITE_PROMPT = 2000
LIMITE_CORPO_BYTE = 64 * 1024 * 1024
RE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")

PARAMETRI_VIDEO = (
    "prompt", "first_frame", "last_frame",
    "reference_images", "reference_videos", "reference_audio", "omni_reference_task_type",
    "duration", "resolution", "aspect_ratio", "generate_audio", "watermark",
    "return_last_frame", "output_format", "execution_expires_after", "priority",
    "safety_identifier", "web_search",
)
CAMPI_VIDEO = frozenset(PARAMETRI_VIDEO) | {"id", "model", "callback_url"}

PARAMETRI_IMMAGINE = (
    "prompt", "images", "size", "aspect_ratio", "output_format", "response_format",
    "watermark", "seed",
)
CAMPI_IMMAGINE = frozenset(PARAMETRI_IMMAGINE) | {"id", "model"}

PERCORSO_UNIFICATO = "/v1/task/submit"
PERCORSO_NATIVO = "/doubao/api/v3/contents/generations/tasks"


class ErroreValidazione(ValueError):
    """Raccoglie tutti i problemi trovati, così si correggono in un colpo solo."""

    def __init__(self, problemi: list[str], contesto: str = ""):
        self.problemi = list(problemi)
        self.contesto = contesto
        prefisso = f"{contesto}: " if contesto else ""
        super().__init__(prefisso + "; ".join(self.problemi))


def _e_intero(x) -> bool:
    return isinstance(x, int) and not isinstance(x, bool)


def _e_numero(x) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool)


@dataclass
class RichiestaVideo:
    id: str
    modello: ModelloVideo
    input: dict
    callback_url: str | None = None
    durate_ref_video: list = field(default_factory=list)   # secondi o None se ignota
    durate_ref_audio: list = field(default_factory=list)
    rapporto_input: float | None = None
    avvisi: list[str] = field(default_factory=list)

    tipo = "video"

    @property
    def modalita(self) -> str:
        if "first_frame" in self.input:
            return "immagine"
        if any(k in self.input for k in ("reference_images", "reference_videos", "reference_audio")):
            return "omni"
        return "testo"

    @property
    def con_video(self) -> bool:
        return bool(self.input.get("reference_videos"))

    @property
    def estensione(self) -> str:
        return self.input.get("output_format", "mp4")

    def secondi_video_input(self) -> tuple[float, bool]:
        """(secondi totali dei video di riferimento, True se tutti noti)."""
        if not self.durate_ref_video:
            return 0.0, True
        if all(d is not None for d in self.durate_ref_video):
            return float(sum(self.durate_ref_video)), True
        return float(self.modello.ref_totale_max_s), False

    def payload_unificato(self) -> dict:
        corpo = {"model": self.modello.nome, "input": dict(self.input)}
        if self.callback_url:
            corpo["callback_url"] = self.callback_url
        return corpo

    def payload_nativo(self) -> dict:
        p = self.input
        contenuto = []
        if p.get("prompt"):
            contenuto.append({"type": "text", "text": p["prompt"]})
        for chiave in ("first_frame", "last_frame"):
            if p.get(chiave):
                contenuto.append({"type": "image_url", "image_url": {"url": p[chiave]}, "role": chiave})
        for url in p.get("reference_images", []):
            contenuto.append({"type": "image_url", "image_url": {"url": url}, "role": "reference_image"})
        for url in p.get("reference_videos", []):
            contenuto.append({"type": "video_url", "video_url": {"url": url}, "role": "reference_video"})
        for url in p.get("reference_audio", []):
            contenuto.append({"type": "audio_url", "audio_url": {"url": url}, "role": "reference_audio"})
        corpo = {"model": self.modello.nome, "content": contenuto}
        for chiave in ("resolution", "duration", "generate_audio", "watermark", "return_last_frame",
                       "output_format", "execution_expires_after", "priority", "safety_identifier",
                       "omni_reference_task_type"):
            if chiave in p:
                corpo[chiave] = p[chiave]
        if "aspect_ratio" in p:
            corpo["ratio"] = p["aspect_ratio"]
        if p.get("web_search"):
            corpo["tools"] = [{"type": "web_search"}]
        if self.callback_url:
            corpo["callback_url"] = self.callback_url
        return corpo

    def payload(self, api: str) -> tuple[str, dict]:
        """(percorso, corpo) per l'API scelta."""
        if api == "native":
            return PERCORSO_NATIVO, self.payload_nativo()
        return PERCORSO_UNIFICATO, self.payload_unificato()

    def stima(self, durata_auto_s: float | None = None) -> pricing.Stima:
        secondi_in, noti = self.secondi_video_input()
        s = pricing.stima_video(
            self.modello, self.input.get("resolution", "720p"), self.input.get("aspect_ratio", "adaptive"),
            self.input.get("duration"), durata_input_s=secondi_in, con_video=self.con_video,
            rapporto_input=self.rapporto_input, durata_auto_s=durata_auto_s,
        )
        s.descrizione = f"{self.id}: {s.descrizione}"
        if not noti:
            s.note.append(f"durata dei video di riferimento non nota: stimati {secondi_in:g} s")
        return s


@dataclass
class RichiestaImmagine:
    id: str
    modello: ModelloImmagine
    input: dict
    avvisi: list[str] = field(default_factory=list)

    tipo = "immagine"

    @property
    def estensione(self) -> str:
        return "jpg" if self.input.get("output_format") == "jpeg" else "png"

    def payload_unificato(self) -> dict:
        return {"model": self.modello.nome, "input": dict(self.input)}

    def payload_immagini(self) -> tuple[str, dict]:
        """Endpoint OpenAI-compatibile sincrono (``/v1/images/generations`` o ``/edits``)."""
        corpo = {"model": self.modello.nome}
        for k, v in self.input.items():
            if k != "images":
                corpo[k] = v
        immagini = self.input.get("images")
        if immagini:
            corpo["image"] = immagini[0] if len(immagini) == 1 else list(immagini)
            return "/v1/images/edits", corpo
        return "/v1/images/generations", corpo

    def payload(self, api: str) -> tuple[str, dict]:
        if api == "native":
            return self.payload_immagini()
        return PERCORSO_UNIFICATO, self.payload_unificato()

    def stima(self, durata_auto_s=None) -> pricing.Stima:
        s = pricing.stima_immagine(self.modello, self.input.get("size", "2K"),
                                   self.input.get("aspect_ratio"), len(self.input.get("images", [])))
        s.descrizione = f"{self.id}: {s.descrizione}"
        return s


def _controlla_id(spec: dict, problemi: list[str]) -> str:
    ident = spec.get("id")
    if not isinstance(ident, str) or not RE_ID.match(ident):
        problemi.append("'id' mancante o non valido (lettere, cifre, '_', '-', '.', massimo 64 caratteri)")
        return str(ident or "?")
    return ident


def _campi_sconosciuti(spec: dict, ammessi, problemi: list[str]) -> None:
    ignoti = sorted(k for k in spec if k not in ammessi and not str(k).startswith("_"))
    if ignoti:
        problemi.append(f"campi sconosciuti: {', '.join(ignoti)} (ammessi: {', '.join(sorted(ammessi))})")


def _lista(spec: dict, chiave: str, problemi: list[str]) -> list:
    v = spec.get(chiave)
    if v is None:
        return []
    if isinstance(v, str):
        return [v]
    if not isinstance(v, list):
        problemi.append(f"'{chiave}' deve essere una lista")
        return []
    return v


def _riferimenti_remoti(voci: list, tipo: str, chiave: str, problemi: list[str]) -> tuple[list, list]:
    """Voci stringa oppure {"url": ..., "duration_s": ...}; restituisce (url, durate)."""
    urls, durate = [], []
    for voce in voci:
        durata = None
        if isinstance(voce, dict):
            extra = set(voce) - {"url", "duration_s"}
            if extra:
                problemi.append(f"'{chiave}': campi non previsti {sorted(extra)} (usa url e duration_s)")
            durata = voce.get("duration_s")
            if durata is not None and (not _e_numero(durata) or durata <= 0):
                problemi.append(f"'{chiave}': duration_s deve essere un numero positivo")
                durata = None
            voce = voce.get("url")
        try:
            urls.append(media.prepara_remoto(voce, tipo))
            durate.append(float(durata) if durata is not None else None)
        except media.ErroreMedia as e:
            problemi.append(str(e))
    return urls, durate


def _controlla_durate(durate: list, tipo: str, m: ModelloVideo, minimo: float,
                      problemi: list[str], avvisi: list[str]) -> None:
    note = [d for d in durate if d is not None]
    for d in note:
        if not minimo <= d <= m.clip_ref_max_s:
            problemi.append(f"{tipo} di riferimento di {d:g} s: ogni clip deve durare "
                            f"fra {minimo:g} e {m.clip_ref_max_s:g} s")
    if sum(note) > m.ref_totale_max_s:
        problemi.append(f"{tipo} di riferimento per {sum(note):g} s in totale (massimo {m.ref_totale_max_s:g} s)")
    if len(note) < len(durate):
        avvisi.append(f"durata di alcuni {tipo} di riferimento non indicata (duration_s): "
                      "limiti di durata non verificati")


def costruisci_video(spec: dict, base: Path | None = None, modello: str | None = None) -> RichiestaVideo:
    """Valida una specifica di shot e prepara i media. Solleva ``ErroreValidazione``."""
    base = Path(base or ".")
    problemi: list[str] = []
    avvisi: list[str] = []
    if not isinstance(spec, dict):
        raise ErroreValidazione(["la specifica deve essere un oggetto JSON"])
    ident = _controlla_id(spec, problemi)
    _campi_sconosciuti(spec, CAMPI_VIDEO, problemi)
    try:
        m = modello_video(spec.get("model") or modello)
    except ValueError as e:
        raise ErroreValidazione([str(e)], ident) from None

    p: dict = {}
    prompt = spec.get("prompt")
    if prompt is not None:
        if not isinstance(prompt, str):
            problemi.append("'prompt' deve essere una stringa")
        elif len(prompt) > LIMITE_PROMPT:
            problemi.append(f"'prompt' di {len(prompt)} caratteri (massimo {LIMITE_PROMPT})")
        elif prompt.strip():
            p["prompt"] = prompt.strip()

    # --- media e modalità -------------------------------------------------------------
    rapporto_input = None
    ha_ff = spec.get("first_frame") not in (None, "")
    ha_lf = spec.get("last_frame") not in (None, "")
    rif_img = _lista(spec, "reference_images", problemi)
    rif_vid = _lista(spec, "reference_videos", problemi)
    rif_aud = _lista(spec, "reference_audio", problemi)
    ha_rif = bool(rif_img or rif_vid or rif_aud)

    if (ha_ff or ha_lf) and ha_rif:
        problemi.append("first_frame/last_frame e reference_* si escludono: scegli una sola modalità")
    if ha_lf and not ha_ff:
        problemi.append("last_frame richiede anche first_frame")

    for chiave in ("first_frame", "last_frame"):
        if spec.get(chiave) in (None, ""):
            continue
        try:
            valore, info = media.prepara_immagine(spec[chiave], base)
            p[chiave] = valore
            if chiave == "first_frame" and info:
                rapporto_input = info.rapporto
        except media.ErroreMedia as e:
            problemi.append(f"{chiave}: {e}")

    if len(rif_img) > m.max_ref_immagini:
        problemi.append(f"{len(rif_img)} reference_images (massimo {m.max_ref_immagini} per {m.etichetta})")
    if len(rif_vid) > m.max_ref_video:
        problemi.append(f"{len(rif_vid)} reference_videos (massimo {m.max_ref_video} per {m.etichetta})")
    if len(rif_aud) > m.max_ref_audio:
        problemi.append(f"{len(rif_aud)} reference_audio (massimo {m.max_ref_audio} per {m.etichetta})")

    immagini = []
    for voce in rif_img:
        try:
            valore, info = media.prepara_immagine(voce, base)
            immagini.append(valore)
        except media.ErroreMedia as e:
            problemi.append(f"reference_images: {e}")
    if immagini:
        p["reference_images"] = immagini
    video_urls, durate_video = _riferimenti_remoti(rif_vid, "video", "reference_videos", problemi)
    audio_urls, durate_audio = _riferimenti_remoti(rif_aud, "audio", "reference_audio", problemi)
    if video_urls:
        p["reference_videos"] = video_urls
    if audio_urls:
        p["reference_audio"] = audio_urls
    if rif_aud and not (rif_img or rif_vid) and not m.solo_audio:
        problemi.append(f"{m.etichetta} non accetta solo audio: aggiungi un'immagine o un video di riferimento")

    tipo_task = spec.get("omni_reference_task_type")
    if tipo_task is not None:
        if not m.supporta_tipo_task:
            problemi.append(f"omni_reference_task_type non è supportato da {m.etichetta}")
        elif tipo_task not in TIPI_TASK_OMNI:
            problemi.append(f"omni_reference_task_type {tipo_task!r} non valido ({'/'.join(TIPI_TASK_OMNI)})")
        elif not ha_rif:
            problemi.append("omni_reference_task_type si usa solo con reference_images/videos/audio")
        else:
            p["omni_reference_task_type"] = tipo_task

    minimo_video = m.clip_ref_min_s
    if tipo_task in ("edit", "extend"):
        if not rif_vid:
            problemi.append(f"il task '{tipo_task}' richiede almeno un reference_video")
        if spec.get("aspect_ratio", "adaptive") != "adaptive":
            problemi.append(f"il task '{tipo_task}' richiede aspect_ratio 'adaptive'")
        if tipo_task == "edit":
            minimo_video = 4
            if spec.get("duration", -1) != -1:
                problemi.append("il task 'edit' richiede duration -1 (durata dal video di partenza)")
    _controlla_durate(durate_video, "video", m, minimo_video, problemi, avvisi)
    _controlla_durate(durate_audio, "audio", m, m.clip_ref_min_s, problemi, avvisi)

    if "prompt" not in p and not (ha_ff or ha_rif):
        problemi.append("serve un 'prompt' (oppure first_frame / reference_*)")

    # --- parametri di generazione -------------------------------------------------------
    durata = spec.get("duration")
    if durata is not None:
        if not _e_intero(durata) or not (durata == -1 or m.durata_min <= durata <= m.durata_max):
            problemi.append(f"'duration' {durata!r} non valida: -1 oppure un intero fra "
                            f"{m.durata_min} e {m.durata_max} per {m.etichetta}")
        else:
            p["duration"] = durata
    ris = spec.get("resolution")
    if ris is not None:
        if ris not in m.risoluzioni:
            problemi.append(f"'resolution' {ris!r} non disponibile per {m.etichetta} ({', '.join(m.risoluzioni)})")
        else:
            p["resolution"] = ris
    rapporto = spec.get("aspect_ratio")
    if rapporto is not None:
        if rapporto not in RAPPORTI_VIDEO:
            problemi.append(f"'aspect_ratio' {rapporto!r} non valido ({', '.join(RAPPORTI_VIDEO)})")
        else:
            p["aspect_ratio"] = rapporto
            if rapporto_input and rapporto != "adaptive":
                atteso = pricing.rapporto_numerico(rapporto)
                if abs(rapporto_input - atteso) / atteso > 0.05:
                    avvisi.append(f"first_frame con rapporto {rapporto_input:.2f} diverso da {rapporto}: "
                                  "il modello adatterà l'inquadratura")
    for chiave in ("generate_audio", "watermark", "return_last_frame", "web_search"):
        v = spec.get(chiave)
        if v is None:
            continue
        if not isinstance(v, bool):
            problemi.append(f"'{chiave}' deve essere true/false")
        else:
            p[chiave] = v
    p.setdefault("watermark", False)
    formato = spec.get("output_format")
    if formato is not None:
        if not m.supporta_formato:
            problemi.append(f"output_format non è supportato da {m.etichetta} (solo mp4)")
        elif formato not in FORMATI_VIDEO:
            problemi.append(f"'output_format' {formato!r} non valido (mp4/mov)")
        else:
            p["output_format"] = formato
    scadenza = spec.get("execution_expires_after")
    if scadenza is not None:
        if not _e_intero(scadenza) or not 3600 <= scadenza <= 259200:
            problemi.append("'execution_expires_after' deve essere un intero fra 3600 e 259200")
        else:
            p["execution_expires_after"] = scadenza
    priorita = spec.get("priority")
    if priorita is not None:
        if not _e_intero(priorita) or not 0 <= priorita <= 9:
            problemi.append("'priority' deve essere un intero fra 0 e 9")
        else:
            p["priority"] = priorita
    ident_utente = spec.get("safety_identifier")
    if ident_utente is not None:
        if not isinstance(ident_utente, str) or len(ident_utente) > 64:
            problemi.append("'safety_identifier' deve essere una stringa di massimo 64 caratteri")
        else:
            p["safety_identifier"] = ident_utente
    callback = spec.get("callback_url")
    if callback is not None and not (isinstance(callback, str) and media.e_url(callback)):
        problemi.append("'callback_url' deve essere un URL http(s)")

    peso = sum(len(v) for v in _stringhe(p) if v.startswith("data:"))
    if peso > LIMITE_CORPO_BYTE * 0.95:
        problemi.append(f"immagini incorporate per {peso / 1048576:.0f} MB: il corpo della richiesta "
                        "supera il limite di 64 MB (usa URL pubblici)")

    if problemi:
        raise ErroreValidazione(problemi, ident)
    ordinato = {k: p[k] for k in PARAMETRI_VIDEO if k in p}
    return RichiestaVideo(ident, m, ordinato, callback, durate_video, durate_audio, rapporto_input, avvisi)


def _stringhe(obj):
    if isinstance(obj, str):
        yield obj
    elif isinstance(obj, dict):
        for v in obj.values():
            yield from _stringhe(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _stringhe(v)


_RE_WXH = re.compile(r"^\d{3,5}x\d{3,5}$")


def costruisci_immagine(spec: dict, base: Path | None = None, modello: str | None = None) -> RichiestaImmagine:
    """Valida una richiesta Seedream. Il watermark è sempre esplicito (il default del modello è true)."""
    base = Path(base or ".")
    problemi: list[str] = []
    if not isinstance(spec, dict):
        raise ErroreValidazione(["la specifica deve essere un oggetto JSON"])
    ident = _controlla_id(spec, problemi)
    _campi_sconosciuti(spec, CAMPI_IMMAGINE, problemi)
    try:
        m = modello_immagine(spec.get("model") or modello)
    except ValueError as e:
        raise ErroreValidazione([str(e)], ident) from None
    p: dict = {}
    prompt = spec.get("prompt")
    if not isinstance(prompt, str) or not prompt.strip():
        problemi.append("serve un 'prompt'")
    else:
        p["prompt"] = prompt.strip()
    riferimenti = _lista(spec, "images", problemi)
    if len(riferimenti) > m.max_riferimenti:
        problemi.append(f"{len(riferimenti)} immagini di riferimento (massimo {m.max_riferimenti})")
    immagini = []
    for voce in riferimenti:
        try:
            immagini.append(media.prepara_immagine(voce, base)[0])
        except media.ErroreMedia as e:
            problemi.append(f"images: {e}")
    if immagini:
        p["images"] = immagini
    size = spec.get("size")
    if size is not None:
        if size not in DIMENSIONI_IMMAGINE and not (isinstance(size, str) and _RE_WXH.match(size)):
            problemi.append(f"'size' {size!r} non valida ({', '.join(DIMENSIONI_IMMAGINE)} oppure LxA)")
        else:
            p["size"] = size
    rapporto = spec.get("aspect_ratio")
    if rapporto is not None:
        if rapporto not in RAPPORTI_IMMAGINE:
            problemi.append(f"'aspect_ratio' {rapporto!r} non valido ({', '.join(RAPPORTI_IMMAGINE)})")
        else:
            p["aspect_ratio"] = rapporto
    for chiave, ammessi in (("output_format", ("png", "jpeg")), ("response_format", ("url", "b64_json"))):
        v = spec.get(chiave)
        if v is not None:
            if v not in ammessi:
                problemi.append(f"'{chiave}' {v!r} non valido ({'/'.join(ammessi)})")
            else:
                p[chiave] = v
    wm = spec.get("watermark", False)
    if not isinstance(wm, bool):
        problemi.append("'watermark' deve essere true/false")
    else:
        p["watermark"] = wm
    seme = spec.get("seed")
    if seme is not None:
        if not _e_intero(seme) or seme < 0:
            problemi.append("'seed' deve essere un intero non negativo")
        else:
            p["seed"] = seme
    if problemi:
        raise ErroreValidazione(problemi, ident)
    ordinato = {k: p[k] for k in PARAMETRI_IMMAGINE if k in p}
    return RichiestaImmagine(ident, m, ordinato)
