"""Registro JSON dei task (``pubblicita/output/seedance/jobs.json``).

Ogni voce è indicizzata dall'id dello shot e si scrive PRIMA del submit (stato
``submitting``) e subito dopo (task id, ``queued``), quindi prima del polling: se il
processo si interrompe, ``resume`` sa sempre quali task esistono e non si paga due volte.
Scrittura atomica (file temporaneo + ``os.replace``) con lock fra thread e, su Linux,
fra processi. Tutto ciò che entra nel registro passa dalla redazione dei segreti e i
data URI vengono compattati.
"""
from __future__ import annotations

import json
import os
import threading
import time
from contextlib import contextmanager
from pathlib import Path

from .client import redigi_oggetto
from .media import compatta

try:  # lock fra processi dove disponibile
    import fcntl
except ImportError:  # pragma: no cover - non-Linux
    fcntl = None

VERSIONE = 1

# Stati locali oltre a quelli normalizzati del fornitore (queued/running/succeeded/failed).
SUBMITTING = "submitting"            # voce scritta, submit in corso
SUBMIT_UNCERTAIN = "submit_uncertain"  # esito del submit ignoto: verificare prima di ripetere
SUBMIT_REJECTED = "submit_rejected"    # rifiutato dal gateway: nessun addebito
DOWNLOADED = "downloaded"            # output scaricato in locale


def adesso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S%z")


class Ledger:
    def __init__(self, percorso: Path):
        self.percorso = Path(percorso)
        self._lock = threading.RLock()

    @contextmanager
    def _bloccato(self):
        with self._lock:
            self.percorso.parent.mkdir(parents=True, exist_ok=True)
            if fcntl is None:
                yield
                return
            with open(self.percorso.with_name(self.percorso.name + ".lock"), "a") as f:
                fcntl.flock(f, fcntl.LOCK_EX)
                try:
                    yield
                finally:
                    fcntl.flock(f, fcntl.LOCK_UN)

    def _leggi_file(self) -> dict:
        if not self.percorso.is_file():
            return {"version": VERSIONE, "jobs": {}}
        try:
            dati = json.loads(self.percorso.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            raise RuntimeError(f"ledger illeggibile ({self.percorso}): {e}. "
                               "Correggilo a mano o spostalo prima di continuare.") from None
        dati.setdefault("version", VERSIONE)
        dati.setdefault("jobs", {})
        return dati

    def _scrivi_file(self, dati: dict) -> None:
        testo = json.dumps(redigi_oggetto(dati), ensure_ascii=False, indent=2, sort_keys=False)
        temporaneo = self.percorso.with_name(f"{self.percorso.name}.{os.getpid()}.{threading.get_ident()}.tmp")
        with open(temporaneo, "w", encoding="utf-8") as f:
            f.write(testo + "\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(temporaneo, self.percorso)

    def voci(self) -> dict:
        with self._bloccato():
            return self._leggi_file()["jobs"]

    def leggi(self, job_id: str) -> dict | None:
        return self.voci().get(job_id)

    def aggiorna(self, job_id: str, **campi) -> dict:
        """Unisce ``campi`` alla voce (creandola se manca) e salva."""
        with self._bloccato():
            dati = self._leggi_file()
            voce = dati["jobs"].get(job_id, {"id": job_id, "created_at": adesso()})
            voce.update(compatta(campi))
            voce["updated_at"] = adesso()
            dati["jobs"][job_id] = voce
            self._scrivi_file(dati)
            return dict(voce)

    def nuova(self, job_id: str, voce: dict) -> dict:
        """Sostituisce la voce; quella precedente (se aveva un task) finisce nello storico."""
        with self._bloccato():
            dati = self._leggi_file()
            vecchia = dati["jobs"].get(job_id)
            storico = []
            if vecchia:
                storico = vecchia.pop("history", [])
                if vecchia.get("task_id") or vecchia.get("status") not in (None, SUBMITTING):
                    storico.append({k: vecchia.get(k) for k in
                                    ("task_id", "status", "submitted_at", "updated_at", "error", "files")})
            nuova = {"id": job_id, "created_at": adesso(), **compatta(voce), "updated_at": adesso()}
            if storico:
                nuova["history"] = storico
            dati["jobs"][job_id] = nuova
            self._scrivi_file(dati)
            return dict(nuova)
