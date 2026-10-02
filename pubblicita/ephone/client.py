"""Client HTTP per il gateway ePhone (stile new-api).

Due famiglie di endpoint, selezionabili con ``api``:

- ``unified`` (predefinita, raccomandata dal gateway): ``POST /v1/task/submit`` con
  ``{"model", "input", "callback_url"?}`` e ``GET /v1/task/{id}``;
- ``native``: mirror dell'API Volcengine Ark, ``POST/GET/DELETE
  /doubao/api/v3/contents/generations/tasks[/{id}]``.

Regole di robustezza:

- la chiave non compare mai in log, eccezioni, ledger o sidecar (``redigi``);
- le GET si ripetono con backoff su 429/5xx/errori di rete;
- il submit NON si ripete quando l'esito è ambiguo (timeout in lettura, connessione caduta,
  502/504/500): il task potrebbe essere stato creato e pagato. Si solleva ``SubmitIncerto``
  e si lascia decidere all'utente. Si ripete solo se la richiesta non è mai partita
  (connessione rifiutata, timeout di connessione) o se il gateway l'ha respinta (429/503);
- le risposte si leggono in modo tollerante (involucro ``{"data": ...}``, ``code``/``message``,
  stati di entrambe le famiglie). Una forma inattesa produce ``RispostaInattesa`` con la
  risposta grezza allegata, da salvare nel ledger.
"""
from __future__ import annotations

import base64
import json
import logging
import os
import random
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse

import requests

log = logging.getLogger("pubblicita.ephone")

URL_BASE_PREDEFINITO = "https://api.ephone.ai"
API_AMMESSE = ("unified", "native")
RADICE_PUBBLICITA = Path(__file__).resolve().parents[1]
FILE_ENV_PREDEFINITO = RADICE_PUBBLICITA / ".env"

STATI_ATTIVI = ("queued", "running")
STATI_FINALI = ("succeeded", "failed")

# Stati di entrambe le famiglie (unificata e Ark) più qualche sinonimo visto nei gateway new-api.
_MAPPA_STATI = {
    "queued": "queued", "queueing": "queued", "pending": "queued", "submitted": "queued",
    "not_start": "queued", "not_started": "queued", "waiting": "queued", "created": "queued",
    "in_progress": "running", "running": "running", "processing": "running",
    "generating": "running", "started": "running",
    "completed": "succeeded", "succeeded": "succeeded", "success": "succeeded",
    "succeed": "succeeded", "finished": "succeeded", "done": "succeeded",
    "failed": "failed", "failure": "failed", "fail": "failed", "error": "failed",
    "cancelled": "failed", "canceled": "failed", "expired": "failed", "timeout": "failed",
}

_ESTENSIONI_VIDEO = (".mp4", ".mov", ".webm", ".m4v")
_ESTENSIONI_IMMAGINE = (".png", ".jpg", ".jpeg", ".webp")


# --- redazione dei segreti ------------------------------------------------------------------

_SEGRETI: set[str] = set()
_LOCK_SEGRETI = threading.Lock()


def registra_segreto(valore: str | None) -> None:
    if valore and len(valore) >= 4:
        with _LOCK_SEGRETI:
            _SEGRETI.add(valore)


def redigi(testo) -> str:
    """Sostituisce ogni segreto registrato con ``***``."""
    s = testo if isinstance(testo, str) else str(testo)
    for segreto in sorted(_SEGRETI, key=len, reverse=True):
        if segreto in s:
            s = s.replace(segreto, "***")
    return s


def redigi_oggetto(obj):
    """Copia profonda di dict/liste con i segreti redatti (anche nelle chiavi)."""
    if isinstance(obj, str):
        return redigi(obj)
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            if str(k).lower() in ("authorization", "api_key", "apikey", "x-api-key"):
                out[redigi(k)] = "***"
            else:
                out[redigi(k)] = redigi_oggetto(v)
        return out
    if isinstance(obj, (list, tuple)):
        return [redigi_oggetto(v) for v in obj]
    return obj


class FiltroRedazione(logging.Filter):
    """Filtro per i logger: redige messaggio e argomenti già formattati."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            messaggio = record.getMessage()
        except Exception:  # formato rotto: lasciamo fare al logging
            return True
        record.msg = redigi(messaggio)
        record.args = ()
        return True


log.addFilter(FiltroRedazione())


# --- errori -----------------------------------------------------------------------------------

class ErroreEphone(Exception):
    def __init__(self, messaggio: str):
        super().__init__(redigi(messaggio))


class ErroreConfigurazione(ErroreEphone):
    pass


class ErroreRete(ErroreEphone):
    pass


class ErroreAPI(ErroreEphone):
    def __init__(self, messaggio: str, *, status: int | None = None, tipo: str = "",
                 codice: str = "", grezzo=None):
        super().__init__(messaggio)
        self.status = status
        self.tipo = tipo
        self.codice = codice
        self.grezzo = redigi_oggetto(grezzo)


class SubmitIncerto(ErroreEphone):
    """Il submit potrebbe essere andato a buon fine: non va ripetuto alla cieca."""


class RispostaInattesa(ErroreEphone):
    def __init__(self, messaggio: str, grezzo=None):
        super().__init__(messaggio)
        self.grezzo = redigi_oggetto(grezzo)


# --- configurazione ---------------------------------------------------------------------------

def leggi_env(percorso: Path) -> dict:
    """Parser minimale di file .env (``CHIAVE=valore``, commenti ``#``, ``export`` opzionale)."""
    valori = {}
    if not percorso or not Path(percorso).is_file():
        return valori
    for riga in Path(percorso).read_text(encoding="utf-8").splitlines():
        riga = riga.strip()
        if not riga or riga.startswith("#") or "=" not in riga:
            continue
        if riga.startswith("export "):
            riga = riga[7:].strip()
        chiave, valore = riga.split("=", 1)
        valore = valore.strip()
        if len(valore) >= 2 and valore[0] == valore[-1] and valore[0] in "\"'":
            valore = valore[1:-1]
        elif " #" in valore:
            valore = valore.split(" #", 1)[0].rstrip()
        valori[chiave.strip()] = valore
    return valori


@dataclass
class Configurazione:
    chiave: str | None
    url_base: str
    origine_chiave: str = ""
    modo_api: str | None = None

    def richiedi_chiave(self) -> str:
        if not self.chiave:
            raise ErroreConfigurazione(
                "chiave ePhone mancante: imposta la variabile EPHONE_API_KEY oppure scrivi "
                f"EPHONE_API_KEY=... in {FILE_ENV_PREDEFINITO} (file ignorato da git)")
        return self.chiave


def carica_configurazione(file_env: Path | None = None, ambiente=None) -> Configurazione:
    """Variabili d'ambiente prima, poi ``pubblicita/.env``. La chiave viene registrata per la redazione."""
    ambiente = os.environ if ambiente is None else ambiente
    da_file = leggi_env(Path(file_env) if file_env else FILE_ENV_PREDEFINITO)
    chiave, origine = ambiente.get("EPHONE_API_KEY", "").strip(), "ambiente"
    if not chiave:
        chiave, origine = da_file.get("EPHONE_API_KEY", "").strip(), "file .env"
    url = (ambiente.get("EPHONE_BASE_URL") or da_file.get("EPHONE_BASE_URL") or URL_BASE_PREDEFINITO).strip()
    modo = (ambiente.get("EPHONE_API_MODE") or da_file.get("EPHONE_API_MODE") or "").strip().lower() or None
    if modo is not None and modo not in API_AMMESSE:
        raise ErroreConfigurazione(f"EPHONE_API_MODE {modo!r} non valido ({'/'.join(API_AMMESSE)})")
    registra_segreto(chiave)
    return Configurazione(chiave or None, url.rstrip("/"), origine if chiave else "", modo)


# --- stato dei task ---------------------------------------------------------------------------

def normalizza_stato(grezzo) -> str | None:
    """Riduce gli stati delle due famiglie a queued/running/succeeded/failed (None se ignoto)."""
    if not isinstance(grezzo, str):
        return None
    return _MAPPA_STATI.get(grezzo.strip().lower())


@dataclass
class StatoTask:
    task_id: str
    stato: str
    stato_grezzo: str
    video_url: str | None = None
    ultimo_frame_url: str | None = None
    immagini: list = field(default_factory=list)
    outputs: list = field(default_factory=list)
    usage: dict | None = None
    errore: str | None = None
    grezzo: dict = field(default_factory=dict)

    @property
    def attivo(self) -> bool:
        return self.stato in STATI_ATTIVI

    def come_dict(self) -> dict:
        return {
            "task_id": self.task_id, "stato": self.stato, "stato_grezzo": self.stato_grezzo,
            "video_url": self.video_url, "ultimo_frame_url": self.ultimo_frame_url,
            "immagini": self.immagini, "outputs": self.outputs, "usage": self.usage,
            "errore": self.errore,
        }


def _scarta_involucro(obj):
    """Toglie gli involucri ``{"data": {...}}`` tipici di new-api, anche annidati."""
    for _ in range(3):
        if (isinstance(obj, dict) and isinstance(obj.get("data"), dict)
                and not ({"status", "task_status"} & set(obj))):
            obj = obj["data"]
        else:
            break
    return obj


def _url_da(voce) -> str | None:
    if isinstance(voce, str):
        return voce
    if isinstance(voce, dict):
        for k in ("url", "video_url", "image_url", "file_url", "b64_json"):
            v = voce.get(k)
            if isinstance(v, str):
                return v if k != "b64_json" else "data:image/png;base64," + v
            if isinstance(v, dict) and isinstance(v.get("url"), str):
                return v["url"]
    return None


def _tipo_da_url(url: str) -> str:
    if url.startswith("data:image/"):
        return "immagine"
    percorso = urlparse(url).path.lower()
    if percorso.endswith(_ESTENSIONI_VIDEO):
        return "video"
    if percorso.endswith(_ESTENSIONI_IMMAGINE):
        return "immagine"
    return "?"


def _testo_errore(err) -> str | None:
    if err in (None, "", {}):
        return None
    if isinstance(err, str):
        return err
    if isinstance(err, dict):
        parti = [str(err.get(k)) for k in ("code", "type", "message") if err.get(k)]
        return " - ".join(parti) or json.dumps(err, ensure_ascii=False)
    return str(err)


def _raccogli_url(dati: dict) -> list:
    """Coppie (tipo o None, url) da tutti i campi dove i gateway mettono gli output."""
    candidati = []
    contenuto = dati.get("content")
    if isinstance(contenuto, dict):
        if contenuto.get("video_url"):
            candidati.append(("video", _url_da(contenuto["video_url"])))
        if contenuto.get("last_frame_url"):
            candidati.append(("frame", _url_da(contenuto["last_frame_url"])))
    for chiave in ("outputs", "output", "results", "result"):
        voce = dati.get(chiave)
        if isinstance(voce, dict):
            for k in ("video_url", "last_frame_url", "url", "urls", "images"):
                if voce.get(k):
                    sotto = voce[k] if isinstance(voce[k], list) else [voce[k]]
                    tipo = "frame" if k == "last_frame_url" else None
                    candidati += [(tipo, _url_da(x)) for x in sotto]
        elif isinstance(voce, (list, str)):
            elenco = voce if isinstance(voce, list) else [voce]
            candidati += [(None, _url_da(x)) for x in elenco]
    for chiave in ("video_url", "result_url"):
        if isinstance(dati.get(chiave), str):
            candidati.append(("video", dati[chiave]))
    if isinstance(dati.get("last_frame_url"), str):
        candidati.append(("frame", dati["last_frame_url"]))
    return candidati


def analizza_stato(risposta, task_id_atteso: str = "") -> StatoTask:
    """Legge la risposta di ``GET /v1/task/{id}`` o del mirror Ark e la normalizza."""
    dati = _scarta_involucro(risposta)
    if not isinstance(dati, dict):
        raise RispostaInattesa("risposta allo stato del task non è un oggetto JSON", risposta)
    grezzo = dati.get("status", dati.get("task_status", dati.get("state")))
    stato = normalizza_stato(grezzo)
    if stato is None:
        raise RispostaInattesa(f"stato del task non riconosciuto: {grezzo!r}", risposta)
    task_id = str(dati.get("id") or dati.get("task_id") or task_id_atteso)

    candidati = _raccogli_url(dati)
    interno = dati.get("data")
    if isinstance(interno, dict):  # new-api: risposta del fornitore annidata in "data"
        candidati += _raccogli_url(interno)

    outputs, video, frame, immagini = [], None, None, []
    for tipo, url in candidati:
        if not url or url in outputs:
            continue
        outputs.append(url)
        tipo = tipo or _tipo_da_url(url)
        if tipo == "video" and video is None:
            video = url
        elif tipo == "frame" and frame is None:
            frame = url
        elif tipo == "immagine":
            immagini.append(url)
    sconosciuti = [u for u in outputs if u not in (video, frame) and u not in immagini]
    if video is None and sconosciuti:
        video = sconosciuti[0]
    if video and frame is None and immagini:
        # formato unificato: accanto al video, un'immagine è l'ultimo frame (return_last_frame)
        frame = immagini[0]

    usage = dati.get("usage") if isinstance(dati.get("usage"), dict) else None
    errore = _testo_errore(dati.get("error") or dati.get("fail_reason") or dati.get("message")
                           if stato == "failed" else dati.get("error"))
    if stato == "failed" and grezzo and str(grezzo).lower() in ("cancelled", "canceled", "expired"):
        errore = errore or f"task {str(grezzo).lower()}"
    if stato == "succeeded" and not outputs:
        raise RispostaInattesa("task completato ma senza URL di output", risposta)
    return StatoTask(task_id, stato, str(grezzo), video, frame, immagini, outputs, usage, errore,
                     redigi_oggetto(dati))


def analizza_submit(risposta) -> tuple[str, str]:
    """(task_id, stato normalizzato) dalla risposta di creazione del task."""
    if isinstance(risposta, dict) and isinstance(risposta.get("data"), str) and risposta["data"].strip():
        return risposta["data"].strip(), "queued"
    dati = _scarta_involucro(risposta)
    if isinstance(dati, dict):
        task_id = dati.get("id") or dati.get("task_id") or dati.get("taskId")
        if isinstance(task_id, (str, int)) and str(task_id).strip():
            return str(task_id).strip(), normalizza_stato(dati.get("status")) or "queued"
    raise RispostaInattesa("la risposta al submit non contiene un id di task", risposta)


def errore_in_corpo(dati) -> ErroreAPI | None:
    """Errori segnalati con HTTP 200 (``success: false``, ``code`` non zero, ``error`` senza task)."""
    if not isinstance(dati, dict):
        return None
    interno = dati.get("data")
    ha_task = (bool({"id", "task_id", "status"} & set(dati)) or isinstance(interno, (dict, list))
               or (isinstance(interno, str) and bool(interno.strip())))
    meta = dati.get("ResponseMetadata")
    if isinstance(meta, dict) and isinstance(meta.get("Error"), dict):
        e = meta["Error"]
        return ErroreAPI(str(e.get("Message") or e.get("Code") or "errore"), codice=str(e.get("Code") or ""),
                         grezzo=dati)
    err = dati.get("error")
    if isinstance(err, dict) and not ha_task:
        return ErroreAPI(_messaggio_errore(dati), tipo=str(err.get("type") or ""),
                         codice=str(err.get("code") or ""), grezzo=dati)
    if dati.get("success") is False:
        return ErroreAPI(_messaggio_errore(dati), codice=str(dati.get("code") or ""), grezzo=dati)
    codice = dati.get("code")
    if codice not in (None, 0, "0", 200, "200", "", "success", "ok", "OK", "Success") and not ha_task:
        return ErroreAPI(_messaggio_errore(dati), codice=str(codice), grezzo=dati)
    return None


def _messaggio_errore(dati, testo: str = "") -> str:
    if isinstance(dati, dict):
        err = dati.get("error")
        if isinstance(err, dict) and err.get("message"):
            return str(err["message"])
        if isinstance(err, str) and err:
            return err
        for k in ("message", "msg", "detail"):
            if dati.get(k):
                return str(dati[k])
    return (testo or "").strip()[:300] or "errore senza messaggio"


# --- client -----------------------------------------------------------------------------------

class ClientEphone:
    """Accesso al gateway. ``sessione`` iniettabile per i test (oggetto con ``request``)."""

    def __init__(self, chiave: str | None, url_base: str = URL_BASE_PREDEFINITO, api: str = "unified",
                 sessione=None, timeout=(10.0, 60.0), tentativi: int = 5, attesa_base_s: float = 2.0,
                 attesa_max_s: float = 30.0, sleep=time.sleep):
        if api not in API_AMMESSE:
            raise ErroreConfigurazione(f"api {api!r} non valida ({'/'.join(API_AMMESSE)})")
        registra_segreto(chiave)
        self._chiave = chiave
        self.url_base = url_base.rstrip("/")
        self.api = api
        self._sessione = sessione
        self._locale = threading.local()
        self.timeout = timeout
        self.tentativi = max(1, tentativi)
        self.attesa_base_s = attesa_base_s
        self.attesa_max_s = attesa_max_s
        self.sleep = sleep

    def __repr__(self) -> str:  # niente chiave nemmeno nel repr
        return f"ClientEphone(url_base={self.url_base!r}, api={self.api!r})"

    # -- trasporto --

    def _http(self):
        if self._sessione is not None:
            return self._sessione
        s = getattr(self._locale, "sessione", None)
        if s is None:
            s = self._locale.sessione = requests.Session()
        return s

    def _intestazioni(self, url: str, json_atteso: bool = True) -> dict:
        h = {"User-Agent": "pubblicita-ephone/1.0"}
        if json_atteso:
            h["Accept"] = "application/json"
        # la chiave va solo all'host del gateway, mai ai CDN da cui si scaricano gli output
        if self._chiave and urlparse(url).netloc == urlparse(self.url_base).netloc:
            h["Authorization"] = f"Bearer {self._chiave}"
        return h

    def _attesa(self, tentativo: int, risposta=None) -> float:
        if risposta is not None:
            ra = (getattr(risposta, "headers", None) or {}).get("Retry-After")
            try:
                if ra is not None:
                    return min(float(ra), 60.0)
            except ValueError:
                pass
        base = min(self.attesa_max_s, self.attesa_base_s * (2 ** tentativo))
        return base * (0.8 + 0.4 * random.random())

    @staticmethod
    def _mai_partita(exc: Exception) -> bool:
        """True se la richiesta sicuramente non ha raggiunto il server."""
        if isinstance(exc, requests.exceptions.ConnectTimeout):
            return True
        if isinstance(exc, requests.exceptions.ConnectionError):
            testo = repr(exc)
            return any(s in testo for s in ("NewConnectionError", "NameResolutionError",
                                             "Failed to resolve", "Connection refused"))
        return False

    def richiesta(self, metodo: str, percorso: str, corpo=None, *, idempotente: bool | None = None):
        """Chiamata JSON al gateway con retry e gestione errori. Restituisce il JSON decodificato."""
        metodo = metodo.upper()
        if idempotente is None:
            idempotente = metodo in ("GET", "DELETE")
        url = percorso if percorso.startswith("http") else self.url_base + percorso
        ultimo = None
        for tentativo in range(self.tentativi):
            try:
                kwargs = {"headers": self._intestazioni(url), "timeout": self.timeout}
                if corpo is not None:
                    kwargs["json"] = corpo
                r = self._http().request(metodo, url, **kwargs)
            except requests.exceptions.RequestException as e:
                ultimo = e
                if idempotente or self._mai_partita(e):
                    log.warning("%s %s: errore di rete (%s), nuovo tentativo", metodo, percorso,
                                type(e).__name__)
                    if tentativo + 1 < self.tentativi:
                        self.sleep(self._attesa(tentativo))
                    continue
                raise SubmitIncerto(
                    f"{metodo} {percorso}: connessione interrotta dopo l'invio ({type(e).__name__}). "
                    "Il task potrebbe essere stato creato e verrà addebitato se va a buon fine: "
                    "controlla la console ePhone prima di ripetere (nessun nuovo tentativo automatico)."
                ) from None
            status = r.status_code
            if status == 429 or (status >= 500 and (idempotente or status == 503)):
                ultimo = r
                log.warning("%s %s: HTTP %s, nuovo tentativo", metodo, percorso, status)
                if tentativo + 1 < self.tentativi:
                    self.sleep(self._attesa(tentativo, r))
                continue
            if status >= 500:
                raise SubmitIncerto(
                    f"{metodo} {percorso}: il gateway ha risposto HTTP {status} "
                    f"({_messaggio_errore(_json_o_none(r), _testo(r))}). Il task potrebbe essere stato "
                    "creato comunque: controlla la console ePhone prima di ripetere.")
            dati = _json_o_none(r)
            if status >= 400:
                err = dati.get("error") if isinstance(dati, dict) else None
                raise ErroreAPI(
                    f"HTTP {status} da {metodo} {percorso}: {_messaggio_errore(dati, _testo(r))}",
                    status=status,
                    tipo=str(err.get("type") or "") if isinstance(err, dict) else "",
                    codice=str(err.get("code") or "") if isinstance(err, dict) else "",
                    grezzo=dati if dati is not None else _testo(r)[:2000])
            if dati is None:
                raise RispostaInattesa(f"{metodo} {percorso}: risposta non JSON", _testo(r)[:2000])
            errore = errore_in_corpo(dati)
            if errore is not None:
                errore.status = status
                raise errore
            return dati
        if isinstance(ultimo, Exception):
            raise ErroreRete(f"{metodo} {percorso}: rete non disponibile dopo {self.tentativi} tentativi "
                             f"({type(ultimo).__name__})")
        status = getattr(ultimo, "status_code", "?")
        dati = _json_o_none(ultimo) if ultimo is not None else None
        raise ErroreAPI(f"{metodo} {percorso}: HTTP {status} anche dopo {self.tentativi} tentativi "
                        f"({_messaggio_errore(dati, _testo(ultimo) if ultimo is not None else '')})",
                        status=status if isinstance(status, int) else None, grezzo=dati)

    # -- operazioni --

    def modelli(self) -> list[str]:
        dati = self.richiesta("GET", "/v1/models")
        elenco = dati.get("data") if isinstance(dati, dict) else dati
        if not isinstance(elenco, list):
            raise RispostaInattesa("/v1/models: lista dei modelli non trovata", dati)
        nomi = []
        for voce in elenco:
            nome = voce.get("id") or voce.get("model_name") if isinstance(voce, dict) else voce
            if isinstance(nome, str):
                nomi.append(nome)
        return nomi

    def saldo(self) -> dict | None:
        """Saldo dal endpoint di fatturazione compatibile OpenAI, se il gateway lo espone (best effort)."""
        try:
            dati = self.richiesta("GET", "/v1/dashboard/billing/subscription")
        except ErroreEphone:
            return None
        if isinstance(dati, dict):
            return {k: dati[k] for k in ("hard_limit_usd", "soft_limit_usd", "system_hard_limit_usd",
                                         "access_until") if k in dati} or None
        return None

    def invia(self, percorso: str, corpo: dict) -> tuple[str, str, dict]:
        """Crea un task. Restituisce (task_id, stato, risposta grezza redatta)."""
        dati = self.richiesta("POST", percorso, corpo, idempotente=False)
        task_id, stato = analizza_submit(dati)
        return task_id, stato, redigi_oggetto(dati)

    def percorso_stato(self, task_id: str, api: str | None = None) -> str:
        api = api or self.api
        if api == "native":
            return f"/doubao/api/v3/contents/generations/tasks/{task_id}"
        return f"/v1/task/{task_id}"

    def stato(self, task_id: str, api: str | None = None) -> StatoTask:
        dati = self.richiesta("GET", self.percorso_stato(task_id, api))
        return analizza_stato(dati, task_id)

    def annulla(self, task_id: str) -> dict:
        """Annulla (in coda) o elimina (concluso) un task Seedance tramite il mirror Ark.

        Il formato unificato non documenta un endpoint di annullamento: si usa sempre il mirror.
        """
        dati = self.richiesta("DELETE", f"/doubao/api/v3/contents/generations/tasks/{task_id}")
        return redigi_oggetto(dati) if isinstance(dati, (dict, list)) else {"risposta": dati}

    def immagini_sincrone(self, percorso: str, corpo: dict) -> dict:
        """``/v1/images/generations`` o ``/edits``: chiamata sincrona, non ripetuta in caso di dubbio."""
        dati = self.richiesta("POST", percorso, corpo, idempotente=False)
        return dati

    def asset(self, input_asset: dict) -> dict:
        """Libreria asset (``model: doubao-asset``): upload/query/list/delete/validazione volti."""
        dati = self.richiesta("POST", "/v1/task/submit", {"model": "doubao-asset", "input": input_asset},
                              idempotente=input_asset.get("action") in ("query", "list", "get_validate_result"))
        return redigi_oggetto(dati)

    def scarica(self, url: str, destinazione: Path) -> int:
        """Scarica un output su file (scrittura atomica). Restituisce i byte scritti."""
        destinazione = Path(destinazione)
        destinazione.parent.mkdir(parents=True, exist_ok=True)
        if url.startswith("data:"):
            dati = base64.b64decode(url.split(",", 1)[1])
            _scrivi_atomico(destinazione, dati)
            return len(dati)
        ultimo = None
        temporaneo = destinazione.with_name(destinazione.name + ".part")
        for tentativo in range(self.tentativi):
            r = None
            try:
                r = self._http().request("GET", url, headers=self._intestazioni(url, json_atteso=False),
                                         timeout=(self.timeout[0], 300), stream=True)
                if r.status_code == 429 or r.status_code >= 500:
                    ultimo = f"HTTP {r.status_code}"
                    if tentativo + 1 < self.tentativi:
                        self.sleep(self._attesa(tentativo, r))
                    continue
                if r.status_code >= 400:
                    raise ErroreAPI(f"download fallito: HTTP {r.status_code} (link scaduto? gli URL "
                                    "valgono 24 ore e al massimo 100 download)", status=r.status_code)
                tipo = (getattr(r, "headers", None) or {}).get("Content-Type", "")
                if tipo.startswith(("text/html", "application/json")):
                    raise ErroreAPI(f"download fallito: il server ha restituito {tipo} invece del file",
                                    status=r.status_code, grezzo=_testo(r)[:500])
                scritti = 0
                with open(temporaneo, "wb") as f:
                    for blocco in r.iter_content(chunk_size=1 << 20):
                        if blocco:
                            f.write(blocco)
                            scritti += len(blocco)
                if scritti == 0:
                    raise ErroreAPI("download fallito: file vuoto")
                os.replace(temporaneo, destinazione)
                return scritti
            except requests.exceptions.RequestException as e:
                ultimo = type(e).__name__
                if tentativo + 1 < self.tentativi:
                    self.sleep(self._attesa(tentativo))
            finally:
                if r is not None and hasattr(r, "close"):
                    r.close()
                if temporaneo.exists():
                    temporaneo.unlink()
        raise ErroreRete(f"download non riuscito dopo {self.tentativi} tentativi ({ultimo})")


def _json_o_none(r):
    try:
        return r.json()
    except (ValueError, AttributeError):
        return None


def _testo(r) -> str:
    try:
        return redigi(r.text or "")
    except Exception:
        return ""


def _scrivi_atomico(percorso: Path, dati: bytes) -> None:
    temporaneo = percorso.with_name(percorso.name + ".part")
    temporaneo.write_bytes(dati)
    os.replace(temporaneo, percorso)
