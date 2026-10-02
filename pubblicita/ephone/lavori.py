"""Esecuzione dei task: submit, polling, download, sidecar, ripresa.

Flusso di un clip:

1. voce nel ledger con stato ``submitting`` e payload (senza chiave, data URI compattati);
2. submit; il task id finisce subito nel ledger (``queued``), prima del polling;
3. polling ogni 5 s con backoff fino a 15 s, timeout per task (30 min di default);
4. a completamento: download immediato in ``output/seedance/<id>.mp4`` (+ ``<id>_last.png``
   se richiesto) e sidecar ``<id>.json``; il ledger passa a ``downloaded``.

Al massimo ``concorrenza`` task attivi insieme (submit + attesa). Se qualcosa si interrompe,
``riprendi`` riparte dai task id registrati senza nuovi submit.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

from . import pricing
from .client import (
    ClientEphone, ErroreAPI, ErroreEphone, ErroreRete, RispostaInattesa, StatoTask, SubmitIncerto,
    log, redigi, redigi_oggetto,
)
from .ledger import (
    DOWNLOADED, SUBMIT_REJECTED, SUBMIT_UNCERTAIN, SUBMITTING, Ledger, adesso,
)
from .media import compatta
from .modelli import modello_video
from .richieste import RichiestaImmagine, RichiestaVideo

CARTELLA_OUTPUT = Path(__file__).resolve().parents[1] / "output"


class Interrotto(Exception):
    pass


@dataclass
class Piano:
    richiesta: RichiestaVideo | RichiestaImmagine
    azione: str            # invia | riprendi | salta
    motivo: str = ""


@dataclass
class Esito:
    id: str
    # scaricato | inviato | saltato | fallito | incerto | rifiutato | timeout | errore | interrotto
    esito: str
    messaggio: str = ""
    file: str | None = None
    costo_usd: float | None = None
    extra: dict = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.esito in ("scaricato", "saltato", "inviato")


def sonda_video(percorso: Path) -> dict | None:
    """Metadati del clip con ffprobe, se installato (fps, durata, risoluzione)."""
    if not shutil.which("ffprobe"):
        return None
    try:
        r = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=codec_name,width,height,r_frame_rate,nb_frames",
             "-show_entries", "format=duration", "-of", "json", str(percorso)],
            capture_output=True, text=True, timeout=60, check=True)
        dati = json.loads(r.stdout)
    except (subprocess.SubprocessError, OSError, json.JSONDecodeError):
        return None
    flusso = (dati.get("streams") or [{}])[0]
    num, _, den = str(flusso.get("r_frame_rate", "0/1")).partition("/")
    try:
        fps = float(num) / float(den or 1)
    except (ValueError, ZeroDivisionError):
        fps = None
    durata = (dati.get("format") or {}).get("duration")
    return {
        "codec": flusso.get("codec_name"), "width": flusso.get("width"), "height": flusso.get("height"),
        "fps": round(fps, 3) if fps else None,
        "frames": int(flusso["nb_frames"]) if str(flusso.get("nb_frames", "")).isdigit() else None,
        "duration_s": float(durata) if durata else None,
    }


class Esecutore:
    def __init__(self, client: ClientEphone, cartella: Path | None = None, *, api: str | None = None,
                 concorrenza: int = 3, poll_iniziale_s: float = 5.0, poll_max_s: float = 15.0,
                 timeout_s: float = 1800.0, notifica=None, sleep=None, orologio=time.monotonic,
                 sonda=sonda_video):
        self.client = client
        self.api = api or client.api
        self.cartella = Path(cartella or CARTELLA_OUTPUT)
        self.cartella_video = self.cartella / "seedance"
        self.cartella_immagini = self.cartella / "seedream"
        self.ledger_video = Ledger(self.cartella_video / "jobs.json")
        self.ledger_immagini = Ledger(self.cartella_immagini / "jobs.json")
        self.concorrenza = max(1, int(concorrenza))
        self.poll_iniziale_s = poll_iniziale_s
        self.poll_max_s = max(poll_max_s, poll_iniziale_s)
        self.timeout_s = timeout_s
        self._notifica = notifica or _stampa
        self._sleep = sleep
        self._orologio = orologio
        self._sonda = sonda
        self._stop = threading.Event()

    # -- utilità --

    def notifica(self, testo: str) -> None:
        self._notifica(redigi(testo))

    def interrompi(self) -> None:
        self._stop.set()

    def _dormi(self, secondi: float) -> None:
        if self._sleep is not None:
            self._sleep(secondi)
        else:
            self._stop.wait(secondi)
        if self._stop.is_set():
            raise Interrotto()

    def ledger_per(self, tipo: str) -> Ledger:
        return self.ledger_immagini if tipo == "immagine" else self.ledger_video

    def file_output(self, richiesta) -> Path:
        cartella = self.cartella_immagini if richiesta.tipo == "immagine" else self.cartella_video
        return cartella / f"{richiesta.id}.{richiesta.estensione}"

    # -- pianificazione --

    def pianifica(self, richieste, forza: bool = False) -> list[Piano]:
        """Decide per ogni richiesta se inviarla, riprenderla o saltarla (batch idempotente)."""
        piano = []
        for r in richieste:
            voce = self.ledger_per(r.tipo).leggi(r.id) or {}
            stato = voce.get("status")
            if forza:
                piano.append(Piano(r, "invia", "--force"))
            elif self.file_output(r).exists():
                piano.append(Piano(r, "salta", f"output già presente ({self.file_output(r).name})"))
            elif voce.get("task_id") and stato in ("queued", "running", "succeeded", DOWNLOADED):
                piano.append(Piano(r, "riprendi", f"task {voce['task_id']} già creato ({stato})"))
            elif stato in (SUBMITTING, SUBMIT_UNCERTAIN):
                piano.append(Piano(r, "salta", "invio precedente dall'esito incerto: verifica sulla console "
                                               "ePhone, poi `resume --assign ID=TASK` oppure --force"))
            else:
                piano.append(Piano(r, "invia"))
        return piano

    # -- esecuzione --

    def esegui(self, piano: list[Piano], attendi: bool = True) -> list[Esito]:
        """Esegue il piano. Con ``attendi=False`` si limita ai submit (poi ``resume``)."""
        if not attendi:
            return [self._solo_invio(p) for p in piano]
        esiti: dict[int, Esito] = {}
        lavori = []
        for i, p in enumerate(piano):
            if p.azione == "salta":
                esiti[i] = Esito(p.richiesta.id, "saltato", p.motivo)
                self.notifica(f"[{p.richiesta.id}] saltato: {p.motivo}")
            else:
                lavori.append((i, p))
        self._esegui_in_parallelo(lavori, lambda p: self._lavora(p), esiti)
        return [esiti[i] for i in sorted(esiti)]

    def _esegui_in_parallelo(self, lavori, funzione, esiti: dict) -> None:
        if not lavori:
            return
        pool = ThreadPoolExecutor(max_workers=min(self.concorrenza, len(lavori)),
                                  thread_name_prefix="ephone")
        try:
            futuri = {i: pool.submit(funzione, elemento) for i, elemento in lavori}
            for i, futuro in futuri.items():
                esiti[i] = futuro.result()
        except KeyboardInterrupt:
            self._stop.set()
            pool.shutdown(wait=True, cancel_futures=True)
            raise
        finally:
            pool.shutdown(wait=True)

    def _solo_invio(self, p: Piano) -> Esito:
        r = p.richiesta
        if p.azione == "salta":
            return Esito(r.id, "saltato", p.motivo)
        if p.azione == "riprendi":
            return Esito(r.id, "inviato", p.motivo)
        esito = self.invia(r)
        if esito is not None:
            return esito
        voce = self.ledger_per(r.tipo).leggi(r.id) or {}
        if voce.get("status") == DOWNLOADED:  # immagine sincrona: già scaricata
            return Esito(r.id, "scaricato", "", (voce.get("files") or {}).get("main"))
        return Esito(r.id, "inviato", f"task {voce.get('task_id')}: scarica più tardi con resume")

    def _lavora(self, p: Piano) -> Esito:
        r = p.richiesta
        try:
            if p.azione == "invia":
                esito = self.invia(r)
                if esito is not None:
                    return esito
            return self.attendi(r.id, r.tipo)
        except Interrotto:
            return Esito(r.id, "interrotto", "interrotto: riprendi con `python3 -m pubblicita.ephone resume`")
        except Exception as e:  # un errore su uno shot non deve fermare gli altri
            log.exception("errore imprevisto su %s", r.id)
            self.ledger_per(r.tipo).aggiorna(r.id, error=redigi(f"{type(e).__name__}: {e}"))
            return Esito(r.id, "errore", redigi(f"{type(e).__name__}: {e}"))

    def _voce_iniziale(self, r, percorso: str, corpo: dict) -> dict:
        stima = r.stima()
        voce = {
            "kind": r.tipo, "model": r.modello.nome, "api": self.api, "status": SUBMITTING,
            "endpoint": percorso, "payload": compatta(corpo), "estimate": stima.come_dict(),
            "ext": r.estensione, "warnings": list(r.avvisi), "prompt": r.input.get("prompt"),
        }
        if r.tipo == "video":
            voce["pricing_basis"] = {"resolution": r.input.get("resolution", "720p"), "with_video": r.con_video}
        return voce

    def invia(self, r) -> Esito | None:
        """Submit con ledger scritto prima e dopo. Restituisce un Esito solo se il submit non riesce.

        Per le immagini in modalità ``native`` (endpoint sincrono) completa anche il download.
        """
        ledger = self.ledger_per(r.tipo)
        percorso, corpo = r.payload(self.api)
        ledger.nuova(r.id, self._voce_iniziale(r, percorso, corpo))
        self.notifica(f"[{r.id}] invio a {r.modello.etichetta} ({self.api})")
        try:
            if r.tipo == "immagine" and self.api == "native":
                risposta = self.client.immagini_sincrone(percorso, corpo)
                return self._salva_immagine_sincrona(r, risposta)
            task_id, stato, risposta = self.client.invia(percorso, corpo)
        except SubmitIncerto as e:
            ledger.aggiorna(r.id, status=SUBMIT_UNCERTAIN, error=str(e))
            self.notifica(f"[{r.id}] ESITO INCERTO: {e}")
            return Esito(r.id, "incerto", str(e))
        except RispostaInattesa as e:
            ledger.aggiorna(r.id, status=SUBMIT_UNCERTAIN, error=str(e), raw_response=e.grezzo)
            self.notifica(f"[{r.id}] risposta al submit non riconosciuta (salvata nel ledger): {e}")
            return Esito(r.id, "incerto", f"{e} (risposta grezza nel ledger)")
        except (ErroreAPI, ErroreRete) as e:
            ledger.aggiorna(r.id, status=SUBMIT_REJECTED, error=str(e),
                            raw_response=getattr(e, "grezzo", None))
            self.notifica(f"[{r.id}] rifiutato: {e}")
            return Esito(r.id, "rifiutato", str(e))
        ledger.aggiorna(r.id, task_id=task_id, status=stato, submitted_at=adesso(), submit_response=risposta)
        self.notifica(f"[{r.id}] task {task_id} creato")
        return None

    def attendi(self, job_id: str, tipo: str = "video") -> Esito:
        """Polling fino a conclusione o timeout; a completamento scarica subito."""
        ledger = self.ledger_per(tipo)
        voce = ledger.leggi(job_id) or {}
        task_id = voce.get("task_id")
        if not task_id:
            return Esito(job_id, "errore", "nessun task id nel ledger")
        api = voce.get("api") or self.api
        intervallo = self.poll_iniziale_s
        inizio = self._orologio()
        ultimo = voce.get("status")
        while True:
            try:
                st = self.client.stato(task_id, api)
            except RispostaInattesa as e:
                ledger.aggiorna(job_id, error=str(e), raw_response=e.grezzo)
                return Esito(job_id, "errore", f"{e} (risposta grezza nel ledger; riprova con resume)")
            except ErroreEphone as e:
                ledger.aggiorna(job_id, error=str(e))
                return Esito(job_id, "errore", f"{e} (il task resta registrato: riprendi con resume)")
            if st.stato != ultimo:
                ledger.aggiorna(job_id, status=st.stato, raw_status=st.stato_grezzo)
                if st.stato != "succeeded":
                    self.notifica(f"[{job_id}] {st.stato} ({st.stato_grezzo})")
                ultimo = st.stato
            if st.stato == "succeeded":
                return self._scarica(job_id, tipo, st)
            if st.stato == "failed":
                ledger.aggiorna(job_id, error=st.errore or "task fallito", completed_at=adesso(),
                                raw_response=st.grezzo)
                self.notifica(f"[{job_id}] FALLITO: {st.errore or st.stato_grezzo}")
                return Esito(job_id, "fallito", st.errore or st.stato_grezzo)
            if self._orologio() - inizio + intervallo > self.timeout_s:
                ledger.aggiorna(job_id, error=f"polling oltre {self.timeout_s:.0f} s: il task continua sul "
                                              "server, riprendi più tardi con resume")
                return Esito(job_id, "timeout", f"ancora {st.stato} dopo {self.timeout_s:.0f} s (task {task_id})")
            self._dormi(intervallo)
            intervallo = min(intervallo * 1.5, self.poll_max_s)

    def _costo_effettivo(self, voce: dict, usage: dict | None) -> dict | None:
        if not usage or voce.get("kind") != "video":
            return None
        token = usage.get("completion_tokens") or usage.get("total_tokens")
        base = voce.get("pricing_basis") or {}
        if not isinstance(token, (int, float)):
            return None
        try:
            m = modello_video(voce.get("model"))
        except ValueError:
            return None
        cny, usd = pricing.costo_token(m, base.get("resolution", "720p"), bool(base.get("with_video")), int(token))
        return {"tokens": int(token), "cny": round(cny, 4), "usd": round(usd, 4)}

    def _scarica(self, job_id: str, tipo: str, st: StatoTask) -> Esito:
        ledger = self.ledger_per(tipo)
        voce = ledger.leggi(job_id) or {}
        ext = voce.get("ext") or ("png" if tipo == "immagine" else "mp4")
        cartella = self.cartella_immagini if tipo == "immagine" else self.cartella_video
        destinazione = cartella / f"{job_id}.{ext}"
        url = (st.immagini[0] if (tipo == "immagine" and st.immagini) else st.video_url) or st.outputs[0]
        ledger.aggiorna(job_id, status="succeeded", outputs=st.outputs, usage=st.usage)
        try:
            n = self.client.scarica(url, destinazione)
        except ErroreEphone as e:
            ledger.aggiorna(job_id, error=f"download: {e}")
            return Esito(job_id, "errore", f"download non riuscito: {e} (riprova con resume entro 24 ore)")
        file = {"main": str(destinazione)}
        avvisi = list(voce.get("warnings") or [])
        if tipo == "video" and st.ultimo_frame_url:
            frame = cartella / f"{job_id}_last.png"
            try:
                self.client.scarica(st.ultimo_frame_url, frame)
                file["last_frame"] = str(frame)
            except ErroreEphone as e:
                avvisi.append(f"ultimo frame non scaricato: {e}")
        sonda = self._sonda(destinazione) if (tipo == "video" and self._sonda) else None
        if sonda and sonda.get("fps") and abs(sonda["fps"] - pricing.FPS) > 0.01:
            avvisi.append(f"il clip è a {sonda['fps']} fps: va conformato a 24 fps nel montaggio")
        costo = self._costo_effettivo(voce, st.usage)
        completato = adesso()
        sidecar = {
            "id": job_id, "kind": tipo, "model": voce.get("model"), "api": voce.get("api"),
            "task_id": st.task_id, "prompt": voce.get("prompt"),
            "params": (voce.get("payload") or {}).get("input", voce.get("payload")),
            "endpoint": voce.get("endpoint"), "status": DOWNLOADED, "outputs": st.outputs,
            "files": file, "bytes": n, "usage": st.usage, "estimate": voce.get("estimate"),
            "cost": costo, "submitted_at": voce.get("submitted_at"), "completed_at": completato,
            "probe": sonda, "warnings": avvisi,
        }
        percorso_sidecar = cartella / f"{job_id}.json"
        _scrivi_json(percorso_sidecar, sidecar)
        file["sidecar"] = str(percorso_sidecar)
        ledger.aggiorna(job_id, status=DOWNLOADED, files=file, cost=costo, completed_at=completato,
                        warnings=avvisi, error=None)
        prezzo = f", costo effettivo ${costo['usd']:.2f}" if costo else ""
        self.notifica(f"[{job_id}] scaricato {destinazione.name} ({n / 1e6:.1f} MB{prezzo})")
        return Esito(job_id, "scaricato", "", str(destinazione), costo["usd"] if costo else None)

    def _salva_immagine_sincrona(self, r: RichiestaImmagine, risposta) -> Esito:
        """Risposta OpenAI-compatibile ``{"data": [{"url"|"b64_json"}], "usage": ...}``."""
        ledger = self.ledger_immagini
        elenco = risposta.get("data") if isinstance(risposta, dict) else None
        url = None
        if isinstance(elenco, list) and elenco and isinstance(elenco[0], dict):
            primo = elenco[0]
            url = primo.get("url") or (("data:image/png;base64," + primo["b64_json"]) if primo.get("b64_json") else None)
        if not url:
            ledger.aggiorna(r.id, status=SUBMIT_UNCERTAIN, error="risposta immagini senza url",
                            raw_response=redigi_oggetto(risposta))
            return Esito(r.id, "incerto", "risposta senza immagine (salvata nel ledger)")
        st = StatoTask(task_id="(sincrono)", stato="succeeded", stato_grezzo="sync", immagini=[url],
                       outputs=[url], usage=risposta.get("usage") if isinstance(risposta.get("usage"), dict) else None)
        ledger.aggiorna(r.id, task_id="(sincrono)", status="succeeded", submitted_at=adesso())
        return self._scarica(r.id, "immagine", st)

    # -- ripresa --

    def assegna(self, job_id: str, task_id: str) -> None:
        """Collega a mano un task id (trovato sulla console) a uno shot dall'esito incerto."""
        for ledger in (self.ledger_video, self.ledger_immagini):
            if ledger.leggi(job_id) is not None:
                ledger.aggiorna(job_id, task_id=task_id, status="queued", error=None,
                                note="task id assegnato a mano")
                return
        raise KeyError(f"{job_id} non è nel ledger")

    def da_riprendere(self) -> tuple[list[tuple[str, str]], list[str]]:
        """(lavori da riprendere [(id, tipo)], avvisi sugli shot dall'esito incerto)."""
        lavori, incerti = [], []
        for tipo, ledger in (("video", self.ledger_video), ("immagine", self.ledger_immagini)):
            for job_id, voce in ledger.voci().items():
                stato, task_id = voce.get("status"), voce.get("task_id")
                principale = (voce.get("files") or {}).get("main")
                if task_id and task_id != "(sincrono)" and (
                        stato in ("queued", "running", "succeeded")
                        or (stato == DOWNLOADED and principale and not Path(principale).exists())):
                    lavori.append((job_id, tipo))
                elif stato in (SUBMITTING, SUBMIT_UNCERTAIN):
                    incerti.append(f"{job_id}: esito del submit incerto ({voce.get('error') or stato}). "
                                   "Verifica sulla console ePhone; se il task esiste usa "
                                   f"`resume --assign {job_id}=<task_id>`, altrimenti rilancia con --force.")
        return lavori, incerti

    def riprendi(self) -> list[Esito]:
        lavori, incerti = self.da_riprendere()
        for testo in incerti:
            self.notifica(testo)
        esiti: dict[int, Esito] = {}

        def funzione(elemento):
            job_id, tipo = elemento
            try:
                return self.attendi(job_id, tipo)
            except Interrotto:
                return Esito(job_id, "interrotto", "interrotto")

        self._esegui_in_parallelo(list(enumerate(lavori)), funzione, esiti)
        return [esiti[i] for i in sorted(esiti)]


def _scrivi_json(percorso: Path, dati: dict) -> None:
    percorso.parent.mkdir(parents=True, exist_ok=True)
    temporaneo = percorso.with_name(percorso.name + ".tmp")
    temporaneo.write_text(json.dumps(redigi_oggetto(compatta(dati)), ensure_ascii=False, indent=2) + "\n",
                          encoding="utf-8")
    temporaneo.replace(percorso)


_LOCK_STAMPA = threading.Lock()


def _stampa(testo: str) -> None:
    with _LOCK_STAMPA:
        print(testo, file=sys.stderr, flush=True)
