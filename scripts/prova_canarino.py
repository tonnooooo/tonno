#!/usr/bin/env python3
"""Prova del canarino in UNA sola richiesta.

Perche' esiste: test_chat_live.py e' fatto per un endpoint di chat. Puntato su
un endpoint agente (un ciclo che per ogni richiesta fa piu' passi, chiama il
modello piu' volte ed esegue comandi) diventa impraticabile: decine di
richieste, ore di attesa, e quasi tutte scadute in timeout.

Questo script fa la stessa domanda in modo diretto. Invece di costruire la
conversazione lunga a forza di giri, la costruisce IN LOCALE e la manda in
una richiesta sola:

    [canarino all'inizio] + [zavorra fino a superare il budget] + [domanda]

Se il codice cliente torna nella risposta, la compattazione conserva i dati.
Se non torna, li sta buttando. Due minuti invece di cinque ore.

    python3 prova_canarino.py --url http://IP:PORTA --api-key CHIAVE \
        --chat-path /agent --sse --ctx 49152

Sul server, in parallelo, guarda cosa fa la compattazione:

    tail -f /tmp/apex-webui.log | grep -E 'ctx-fit|oai-guard'
"""
from __future__ import annotations

import argparse
import json
import re
import time
import urllib.error
import urllib.request

CODICE = "ZX-7741-QUERCIA"
APERTURA = (
    f"Informazione da conservare per tutta la conversazione: il mio codice "
    f"cliente e' {CODICE}. Quando te lo chiedo, riportalo alla lettera. "
    f"Per ora rispondi solo: ricevuto."
)
DOMANDA = ("Senza eseguire nessun comando: qual e' il mio codice cliente, "
           "quello che ti ho dato all'inizio della conversazione?")


def zavorra(n: int) -> str:
    return ("Nota operativa numero %d. " % n) + " ".join(
        "paragrafo dettagliato di analisi tecnica riga %d" % i for i in range(28))


def costruisci(ctx: int, oltre: float) -> list[dict[str, str]]:
    """Cronologia che supera il budget del fattore richiesto."""
    bersaglio = int(ctx * oltre)
    msgs = [
        {"role": "user", "content": APERTURA},
        {"role": "assistant", "content": f"Ricevuto: il tuo codice cliente e' {CODICE}."},
    ]
    caratteri = sum(len(m["content"]) for m in msgs)
    i = 0
    while caratteri < bersaglio * 3:      # ~3 caratteri per token
        i += 1
        u = zavorra(i)
        a = "Annotato il punto %d, procedo con l'analisi successiva." % i
        msgs.append({"role": "user", "content": u})
        msgs.append({"role": "assistant", "content": a})
        caratteri += len(u) + len(a)
    msgs.append({"role": "user", "content": DOMANDA})
    return msgs


def leggi_sse(grezzo: str) -> str:
    pezzi = []
    for riga in grezzo.splitlines():
        riga = riga.strip()
        if not riga.startswith("data:"):
            continue
        d = riga[5:].strip()
        if d in ("", "[DONE]"):
            continue
        try:
            j = json.loads(d)
            pezzi.append((j["choices"][0]["delta"] or {}).get("content") or "")
        except Exception:  # noqa: BLE001
            continue
    return "".join(pezzi)


def ripulisci(t: str) -> str:
    t = re.sub(r"(?is)<think>.*?</think>", "", t)
    t = re.sub(r"(?s)@@(THINK|EXEC).*?@@END", "", t)   # schede dell'agente
    return t.strip()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--url", required=True)
    ap.add_argument("--api-key", default="")
    ap.add_argument("--chat-path", default="/agent")
    ap.add_argument("--sse", action="store_true")
    ap.add_argument("--ctx", type=int, default=49152, help="finestra del motore")
    ap.add_argument("--oltre", type=float, default=1.4,
                    help="quanto superare il budget (1.4 = 40%% oltre)")
    ap.add_argument("--max-tokens", type=int, default=256)
    ap.add_argument("--timeout", type=float, default=900.0)
    a = ap.parse_args()

    msgs = costruisci(a.ctx, a.oltre)
    stima = sum(len(m["content"]) for m in msgs) // 3
    print("=" * 66)
    print("PROVA DEL CANARINO — una sola richiesta")
    print("=" * 66)
    print(f"endpoint .......... {a.url.rstrip('/')}{a.chat_path}" + ("  (SSE)" if a.sse else ""))
    print(f"messaggi inviati .. {len(msgs)}")
    print(f"token stimati ..... ~{stima:,} (finestra dichiarata {a.ctx:,})")
    print(f"codice piantato ... {CODICE}, nel PRIMO messaggio")
    print()
    print("Sul server, in un'altra shell:")
    print("  tail -f /tmp/apex-webui.log | grep -E 'ctx-fit|oai-guard'")
    print()
    print("invio in corso, puo' richiedere qualche minuto...", flush=True)

    corpo = {"messages": msgs, "max_tokens": a.max_tokens, "temperature": 0.1}
    if a.sse:
        corpo["stream"] = True
    req = urllib.request.Request(a.url.rstrip("/") + a.chat_path,
                                 data=json.dumps(corpo).encode(), method="POST")
    req.add_header("Content-Type", "application/json")
    if a.api_key:
        req.add_header("Authorization", "Bearer " + a.api_key)

    t0 = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=a.timeout) as r:
            grezzo = r.read().decode("utf-8", "replace")
            stato = r.status
    except urllib.error.HTTPError as e:
        grezzo = e.read().decode("utf-8", "replace")
        stato = e.code
    except Exception as e:  # noqa: BLE001
        print(f"\nNESSUNA RISPOSTA dopo {time.perf_counter()-t0:.0f}s: {e!r}")
        print("Se e' un timeout, il ciclo agente sta ancora girando: rilancia")
        print("con --max-tokens 64 e --oltre 1.2, oppure guarda il log sul server.")
        return 2

    dt = time.perf_counter() - t0
    testo = ripulisci(leggi_sse(grezzo) if ("data:" in grezzo) else grezzo)
    print(f"\nrisposta in {dt:.0f}s (HTTP {stato})")
    print("-" * 66)
    print(testo[:700] if testo else "(vuota)")
    print("-" * 66)

    if stato >= 400:
        print("\nESITO: il server ha rifiutato la richiesta.")
        print(grezzo[:400])
        return 1
    if CODICE in testo.upper() or "ZX-7741" in testo.upper():
        print("\nESITO: CANARINO VIVO — la compattazione conserva i dati concreti.")
        return 0
    print("\nESITO: CANARINO PERSO — l'informazione del primo messaggio non e'")
    print("       sopravvissuta. La riduzione del contesto sta scartando invece")
    print("       di riassumere, oppure il riassunto non conserva gli identificativi.")
    print("       Controlla nel log se 'ctx-fit' e' comparso: se non c'e', la")
    print("       compattazione non e' nemmeno scattata e ha tagliato il motore.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
