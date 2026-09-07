#!/usr/bin/env python3
"""Test approfondito di una chat LLM in funzione, per far emergere i bug reali.

Va eseguito da una macchina che RAGGIUNGE il servizio (la VM stessa, o il PC
dove gira l'agente con accesso). Non modifica nulla lato server se non creando
conversazioni di prova, e non cancella niente.

    python3 test_chat_live.py --url http://IP:PORTA --api-key CHIAVE

Cosa verifica, in ordine:

  FASE 0  che API espone il servizio e con quale modello
  FASE 1  finestra di contesto dichiarata contro finestra reale
  FASE 2  a quale lunghezza la conversazione si rompe, e con quale errore
  FASE 3  la compattazione: si fa crescere la chat oltre la soglia piu' volte
          di seguito e si controlla che sopravviva e che non perda i dati
  FASE 4  tenuta sotto richieste concorrenti
  FASE 5  persistenza: la cronologia si rilegge dopo?

Stampa un rapporto finale con i difetti trovati, classificati.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.error
import urllib.request
from typing import Any

# Fatto piantato all'inizio della conversazione: se dopo le compattazioni il
# modello non sa piu' rispondere, la compattazione sta perdendo informazione.
CANARINO_DOMANDA = "Come ti ho detto all'inizio, qual e' il mio codice cliente?"
CANARINO_VALORE = "ZX-7741-QUERCIA"
CANARINO_TESTO = (
    f"Informazione importante da ricordare per tutta la conversazione: "
    f"il mio codice cliente e' {CANARINO_VALORE}. "
    f"Ripetimelo ogni volta che te lo chiedo, alla lettera."
)

RIEMPITIVO = (
    "Continuiamo l'analisi. Elenca e commenta in dettaglio i seguenti aspetti "
    "del tema di cui stiamo parlando, con esempi concreti e passaggi intermedi, "
    "in modo esteso: "
)

rapporto: list[dict[str, Any]] = []


def nota(gravita: str, titolo: str, dettaglio: str = "") -> None:
    rapporto.append({"gravita": gravita, "titolo": titolo, "dettaglio": dettaglio})
    simbolo = {"BLOCCANTE": "[!!]", "GRAVE": "[!]", "AVVISO": "[~]", "OK": "[ok]", "INFO": "[i]"}[gravita]
    print(f"  {simbolo} {titolo}" + (f"\n        {dettaglio}" if dettaglio else ""), flush=True)


class Client:
    def __init__(self, base: str, api_key: str, timeout: float = 180.0):
        self.base = base.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout
        self.ultimo_errore = ""

    def chiama(self, percorso: str, dati: dict | None = None, metodo: str = "GET",
               timeout: float | None = None) -> tuple[int, Any, float]:
        url = percorso if percorso.startswith("http") else self.base + percorso
        corpo = json.dumps(dati).encode() if dati is not None else None
        req = urllib.request.Request(url, data=corpo, method=metodo if corpo is None else "POST")
        req.add_header("Content-Type", "application/json")
        if self.api_key:
            req.add_header("Authorization", f"Bearer {self.api_key}")
            req.add_header("X-API-Key", self.api_key)          # alcune UI usano questo
        t0 = time.perf_counter()
        try:
            with urllib.request.urlopen(req, timeout=timeout or self.timeout) as r:
                grezzo = r.read().decode("utf-8", "replace")
                dt = time.perf_counter() - t0
                try:
                    return r.status, json.loads(grezzo), dt
                except ValueError:
                    return r.status, grezzo, dt
        except urllib.error.HTTPError as e:
            grezzo = e.read().decode("utf-8", "replace")
            self.ultimo_errore = grezzo[:600]
            dt = time.perf_counter() - t0
            try:
                return e.code, json.loads(grezzo), dt
            except ValueError:
                return e.code, grezzo, dt
        except Exception as e:  # noqa: BLE001
            self.ultimo_errore = repr(e)
            return 0, repr(e), time.perf_counter() - t0


# ---------------------------------------------------------------- FASE 0
def fase0_scoperta(c: Client) -> dict[str, Any]:
    print("\nFASE 0 — Che cosa risponde il servizio")
    trovato: dict[str, Any] = {"api": None, "modello": None, "endpoint": {}}

    sonde = [
        ("openai",   "/v1/models"),
        ("openai",   "/api/v1/models"),
        ("kobold",   "/api/v1/model"),
        ("kobold",   "/api/extra/version"),
        ("kobold",   "/api/extra/true_max_context_length"),
        ("ollama",   "/api/tags"),
        ("generico", "/health"),
        ("generico", "/api/config"),
        ("generico", "/config"),
    ]
    for tipo, percorso in sonde:
        stato, corpo, _ = c.chiama(percorso, timeout=25)
        if stato and stato < 400:
            trovato["endpoint"][percorso] = corpo
            estratto = json.dumps(corpo, ensure_ascii=False)[:180] if not isinstance(corpo, str) else corpo[:180]
            nota("INFO", f"{percorso} -> {stato}", estratto)
            if trovato["api"] is None and tipo != "generico":
                trovato["api"] = tipo

    # nome del modello
    for percorso, chiave in (("/v1/models", "data"), ("/api/v1/model", "result"), ("/api/tags", "models")):
        corpo = trovato["endpoint"].get(percorso)
        if not corpo:
            continue
        try:
            if chiave == "data":
                trovato["modello"] = corpo["data"][0]["id"]
            elif chiave == "result":
                trovato["modello"] = corpo["result"]
            else:
                trovato["modello"] = corpo["models"][0]["name"]
            break
        except Exception:  # noqa: BLE001
            continue

    if trovato["api"] is None:
        nota("BLOCCANTE", "Nessuna API riconosciuta",
             "Ne' OpenAI-compatible, ne' KoboldCpp, ne' Ollama rispondono. "
             "Verificare URL, porta e che la chiave sia accettata.")
    else:
        nota("OK", f"API riconosciuta: {trovato['api']}", f"modello dichiarato: {trovato['modello']}")
    return trovato


# ---------------------------------------------------------------- FASE 1
def fase1_contesto(c: Client, scoperta: dict[str, Any]) -> dict[str, Any]:
    print("\nFASE 1 — Finestra di contesto")
    info: dict[str, Any] = {"dichiarata": None, "vera": None}

    vera = scoperta["endpoint"].get("/api/extra/true_max_context_length")
    if isinstance(vera, dict):
        info["vera"] = vera.get("value")
        nota("INFO", f"Il motore dichiara true_max_context_length = {info['vera']}")

    for percorso in ("/api/config", "/config"):
        corpo = scoperta["endpoint"].get(percorso)
        if isinstance(corpo, dict):
            for k, v in corpo.items():
                if re.search(r"context|max_?tok|max_?len", str(k), re.I) and isinstance(v, int):
                    info["dichiarata"] = v
                    nota("INFO", f"La UI usa {k} = {v}")

    if info["vera"] and info["dichiarata"] and info["dichiarata"] > info["vera"]:
        nota("BLOCCANTE", "DISALLINEAMENTO DELLA FINESTRA DI CONTESTO",
             f"La UI crede di avere {info['dichiarata']} token, il motore ne serve {info['vera']}. "
             f"Il motore tronca in silenzio dalla testa: si perde il system prompt e la chat "
             f"sembra impazzita. E' la causa piu' comune del sintomo riferito.")
    elif info["vera"]:
        nota("OK", "Nessun disallineamento rilevabile dagli endpoint pubblici")
    else:
        nota("AVVISO", "Finestra reale non interrogabile",
             "Da verificare a mano sul comando di avvio del motore (--contextsize).")
    return info


# ------------------------------------------------------------ invio chat
def invia(c: Client, messaggi: list[dict[str, str]], api: str, modello: str | None,
          max_tokens: int = 256) -> tuple[int, str, str, float]:
    """Ritorna (stato, testo_risposta, errore_grezzo, secondi)."""
    if api == "kobold":
        prompt = "".join(
            f"### {'Istruzione' if m['role'] != 'assistant' else 'Risposta'}:\n{m['content']}\n\n"
            for m in messaggi
        ) + "### Risposta:\n"
        stato, corpo, dt = c.chiama("/api/v1/generate", {"prompt": prompt, "max_length": max_tokens})
        if stato and stato < 400 and isinstance(corpo, dict):
            try:
                return stato, corpo["results"][0]["text"], "", dt
            except Exception:  # noqa: BLE001
                return stato, "", json.dumps(corpo)[:400], dt
        return stato, "", (corpo if isinstance(corpo, str) else json.dumps(corpo))[:600], dt

    dati = {"messages": messaggi, "max_tokens": max_tokens, "temperature": 0.3}
    if modello:
        dati["model"] = modello
    stato, corpo, dt = c.chiama("/v1/chat/completions", dati)
    if stato and stato < 400 and isinstance(corpo, dict):
        try:
            return stato, corpo["choices"][0]["message"]["content"], "", dt
        except Exception:  # noqa: BLE001
            return stato, "", json.dumps(corpo)[:400], dt
    return stato, "", (corpo if isinstance(corpo, str) else json.dumps(corpo))[:600], dt


# ---------------------------------------------------------------- FASE 2
def fase2_limite(c: Client, api: str, modello: str | None) -> int:
    print("\nFASE 2 — A che lunghezza si rompe")
    ultimo_ok = 0
    for parole in (200, 800, 2000, 5000, 10000, 20000, 40000):
        messaggi = [
            {"role": "system", "content": "Sei un assistente conciso."},
            {"role": "user", "content": RIEMPITIVO + ("dettaglio " * parole) + "\nRispondi solo: OK"},
        ]
        stato, testo, errore, dt = invia(c, messaggi, api, modello, max_tokens=16)
        approx = int(parole * 1.4) + 30
        if stato and stato < 400:
            ultimo_ok = approx
            print(f"    ~{approx:>6} token -> OK ({dt:.1f}s)", flush=True)
        else:
            print(f"    ~{approx:>6} token -> ERRORE {stato} ({dt:.1f}s)", flush=True)
            basso = errore.lower()
            if any(x in basso for x in ("context", "too long", "max_len", "exceed", "token")):
                nota("INFO", f"Limite reale di contesto tra ~{ultimo_ok} e ~{approx} token",
                     f"errore del server: {errore[:250]}")
            elif stato == 0:
                nota("GRAVE", f"Nessuna risposta oltre ~{ultimo_ok} token (timeout o connessione chiusa)",
                     "Il server muore o resta appeso invece di rispondere con un errore: "
                     "lato client sembra che la chat si sia piantata. " + errore[:200])
            else:
                nota("GRAVE", f"Errore {stato} oltre ~{ultimo_ok} token", errore[:250])
            break
    else:
        nota("OK", f"Nessuna rottura fino a ~{ultimo_ok} token")
    return ultimo_ok


# ---------------------------------------------------------------- FASE 3
def fase3_compattazione(c: Client, api: str, modello: str | None, limite: int, giri: int) -> None:
    print(f"\nFASE 3 — Compattazione: {giri} cicli oltre soglia (il test che conta)")
    messaggi: list[dict[str, str]] = [
        {"role": "system", "content": "Sei un assistente conciso. Rispondi in massimo 40 parole."},
        {"role": "user", "content": CANARINO_TESTO},
        {"role": "assistant", "content": f"Annotato: il tuo codice cliente e' {CANARINO_VALORE}."},
    ]
    # blocco di riempimento calibrato per riempire la finestra in pochi giri
    parole_blocco = max(400, int(limite / 6)) if limite else 800
    canarino_perso_al_giro = None
    morti = 0

    for giro in range(1, giri + 1):
        messaggi.append({"role": "user", "content": RIEMPITIVO + ("argomento " * parole_blocco)})
        stato, testo, errore, dt = invia(c, messaggi, api, modello, max_tokens=120)
        if stato and stato < 400:
            # Si rimuove il valore del canarino dalle risposte prima di
            # rimetterle nella cronologia: se il modello lo ripete, resterebbe
            # nel contesto recente e il test direbbe "sopravvive" per il motivo
            # sbagliato. Cosi' il dato esiste SOLO nel messaggio iniziale.
            pulito = (testo or "")[:2000].replace(CANARINO_VALORE, "[omesso]")
            messaggi.append({"role": "assistant", "content": pulito})
        else:
            morti += 1
            print(f"    giro {giro}: riempimento -> ERRORE {stato}", flush=True)
            if morti == 1:
                nota("GRAVE", f"La conversazione si rompe al giro {giro} di riempimento",
                     f"stato {stato}: {errore[:250]}")

        # verifica del canarino: l'informazione iniziale sopravvive?
        # La domanda di controllo non entra nella cronologia: si interroga
        # una copia, cosi' il test non altera lo stato che sta misurando.
        prova = messaggi + [{"role": "user", "content": CANARINO_DOMANDA}]
        stato_c, testo_c, errore_c, _ = invia(c, prova, api, modello, max_tokens=60)
        if stato_c and stato_c < 400:
            ok = CANARINO_VALORE.split("-")[0] in (testo_c or "").upper()
            print(f"    giro {giro}: canarino {'PRESENTE' if ok else 'PERSO'} "
                  f"| risposta: {(testo_c or '').strip()[:70]!r}", flush=True)
            if not ok and canarino_perso_al_giro is None:
                canarino_perso_al_giro = giro
        else:
            print(f"    giro {giro}: canarino non verificabile (errore {stato_c})", flush=True)

    if morti:
        nota("BLOCCANTE", f"La chat ha smesso di rispondere in {morti} giri su {giri}",
             "Il contesto non viene ridotto prima dell'invio: la richiesta parte comunque "
             "e il server la rifiuta. Serve compattare PRIMA di chiamare il modello.")
    else:
        nota("OK", f"La chat ha risposto in tutti i {giri} giri")

    if canarino_perso_al_giro:
        nota("GRAVE", f"Informazione iniziale persa dal giro {canarino_perso_al_giro}",
             f"Il codice {CANARINO_VALORE} era stato dichiarato all'inizio e il modello non lo "
             f"sa piu' ripetere: il taglio del contesto butta via i messaggi vecchi senza "
             f"riassumerli, oppure il riassunto non conserva i dati concreti.")
    else:
        nota("OK", "L'informazione iniziale sopravvive a tutti i cicli")


# ---------------------------------------------------------------- FASE 4
def fase4_concorrenza(c: Client, api: str, modello: str | None) -> None:
    print("\nFASE 4 — Richieste in parallelo")
    import threading

    esiti: list[tuple[int, float]] = []
    blocco = threading.Lock()

    def una(n: int) -> None:
        messaggi = [{"role": "user", "content": f"Rispondi solo con il numero {n}."}]
        stato, _, _, dt = invia(c, messaggi, api, modello, max_tokens=16)
        with blocco:
            esiti.append((stato, dt))

    th = [threading.Thread(target=una, args=(i,)) for i in range(5)]
    t0 = time.perf_counter()
    for t in th:
        t.start()
    for t in th:
        t.join()
    totale = time.perf_counter() - t0

    falliti = [s for s, _ in esiti if not s or s >= 400]
    print(f"    5 richieste in {totale:.1f}s, fallite: {len(falliti)}", flush=True)
    if falliti:
        nota("GRAVE", f"{len(falliti)} richieste su 5 falliscono in parallelo",
             "Doppio invio dal browser o due schede aperte bastano a rompere la sessione.")
    else:
        nota("OK", "Le richieste in parallelo vengono servite tutte")


# ---------------------------------------------------------------- FASE 5
def fase5_persistenza(c: Client, scoperta: dict[str, Any]) -> None:
    print("\nFASE 5 — Persistenza della cronologia")
    trovato = False
    for percorso in ("/api/conversations", "/conversations", "/api/chats", "/api/v1/conversations",
                     "/api/sessions", "/api/history"):
        stato, corpo, _ = c.chiama(percorso, timeout=25)
        if stato and stato < 400:
            trovato = True
            n = len(corpo) if isinstance(corpo, list) else "?"
            nota("INFO", f"{percorso} -> {stato}, elementi: {n}")
    if not trovato:
        nota("AVVISO", "Nessun endpoint di cronologia lato server",
             "Probabile che le conversazioni stiano nel localStorage del browser: in quel caso "
             "il server non compatta niente e il taglio lo fa la UI lato client. "
             "Da verificare nel codice della WebUI.")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--url", required=True, help="es. http://213.181.123.31:38108")
    ap.add_argument("--api-key", default="", help="chiave per l'API della chat")
    ap.add_argument("--giri", type=int, default=6, help="cicli di riempimento nella fase 3")
    ap.add_argument("--timeout", type=float, default=180.0)
    a = ap.parse_args()

    print("=" * 72)
    print(f"TEST APPROFONDITO — {a.url}")
    print(f"avvio: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 72)

    c = Client(a.url, a.api_key, a.timeout)
    scoperta = fase0_scoperta(c)
    if scoperta["api"] is None:
        print("\nImpossibile proseguire: il servizio non espone un'API riconosciuta.")
        return 2

    fase1_contesto(c, scoperta)
    limite = fase2_limite(c, scoperta["api"], scoperta["modello"])
    fase3_compattazione(c, scoperta["api"], scoperta["modello"], limite, a.giri)
    fase4_concorrenza(c, scoperta["api"], scoperta["modello"])
    fase5_persistenza(c, scoperta)

    print("\n" + "=" * 72)
    print("RAPPORTO FINALE")
    print("=" * 72)
    for livello in ("BLOCCANTE", "GRAVE", "AVVISO", "OK", "INFO"):
        voci = [r for r in rapporto if r["gravita"] == livello]
        if not voci:
            continue
        print(f"\n{livello} ({len(voci)}):")
        for v in voci:
            print(f"  - {v['titolo']}")
            if v["dettaglio"]:
                print(f"      {v['dettaglio']}")

    bloccanti = sum(1 for r in rapporto if r["gravita"] == "BLOCCANTE")
    gravi = sum(1 for r in rapporto if r["gravita"] == "GRAVE")
    print(f"\nESITO: {bloccanti} problemi bloccanti, {gravi} gravi.")
    print("Incolla TUTTO questo output per l'analisi.")
    return 1 if (bloccanti or gravi) else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\ninterrotto")
        sys.exit(130)
