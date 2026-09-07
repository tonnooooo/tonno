#!/usr/bin/env python3
"""Soak test: simula ore di chat in pochi secondi e verifica le invarianti.

Il punto non e' "funziona con tre messaggi": e' che dopo centinaia di turni,
decine di compattazioni, errori del backend, incollate enormi e disconnessioni
la conversazione sia ANCORA integra e utilizzabile.

Il backend LLM e' simulato in modo AVVERSO: risponde a caso, ogni tanto va in
errore, ogni tanto produce riassunti vuoti, ogni tanto restituisce output di
tool giganteschi e argomenti JSON malformati. Se un'invariante salta, lo
script lo dice e ritorna exit code 1.

Uso:
    python3 scripts/stress_test.py                 # 300 turni, 8 conversazioni
    python3 scripts/stress_test.py --turns 2000 --conversations 20 --seed 7
"""
from __future__ import annotations

import argparse
import asyncio
import os
import random
import sys
import time
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import config, db as db_module                       # noqa: E402
from app.agents.loop import run_agent_turn                    # noqa: E402
from app.compaction import build_context, compact, conversation_lock  # noqa: E402
from app.llm import ContextLengthError, LLMError              # noqa: E402
from app.tokens import count_messages                         # noqa: E402

PAROLE = ("contesto compattazione modello agente ricerca osint indirizzo dominio "
          "target report analisi verifica risultato query fonte").split()


class BackendAvverso:
    """Backend LLM finto che si comporta male apposta."""

    def __init__(self, rng: random.Random, tasso_errore: float = 0.12):
        self.rng = rng
        self.tasso_errore = tasso_errore
        self.chiamate = 0
        self.errori = 0
        self.riassunti = 0

    def _testo(self, n: int) -> str:
        return " ".join(self.rng.choice(PAROLE) for _ in range(n))

    async def chat(self, messages: list[dict[str, Any]], **kw: Any) -> dict[str, Any]:
        self.chiamate += 1
        await asyncio.sleep(0)
        e_riassunto = bool(messages) and "compressore di contesto" in (messages[0].get("content") or "")

        r = self.rng.random()
        if r < self.tasso_errore * 0.4:
            self.errori += 1
            raise LLMError("504 dal backend", kind="server", retryable=True)
        if r < self.tasso_errore * 0.55:
            self.errori += 1
            raise ContextLengthError("maximum context length exceeded", 400)

        if e_riassunto:
            self.riassunti += 1
            if self.rng.random() < 0.15:          # riassunto vuoto
                return {"choices": [{"message": {"role": "assistant", "content": ""}}]}
            return {"choices": [{"message": {"role": "assistant",
                                             "content": "- " + self._testo(60)}}]}

        msg: dict[str, Any] = {"role": "assistant", "content": self._testo(self.rng.randint(20, 200))}
        if kw.get("tools") and self.rng.random() < 0.35:
            n = self.rng.randint(1, 2)
            msg["tool_calls"] = [
                {"id": f"call_{self.chiamate}_{i}", "type": "function",
                 "function": {"name": self.rng.choice(["web_search", "fetch_url", "tool_inesistente"]),
                              # argomenti volutamente sporchi
                              "arguments": self.rng.choice(
                                  ['{"query": "roma"}', "{'query': 'roma'}", "", "non json", '{"url": "http://x"}'])}}
                for i in range(n)
            ]
            msg["content"] = ""
        return {"choices": [{"message": msg}], "usage": {"total_tokens": 100}}

    async def chat_text(self, messages, **kw) -> str:
        data = await self.chat(messages, **kw)
        return (data["choices"][0]["message"].get("content") or "").strip()

    async def stream_chat(self, messages, **kw):
        data = await self.chat(messages, **kw)
        for w in (data["choices"][0]["message"].get("content") or "").split():
            yield {"choices": [{"delta": {"content": w + " "}}]}

    async def health(self):
        return {"reachable": True}

    async def aclose(self):
        return None


async def tool_finto(name: str, arguments: dict[str, Any]) -> str:
    """Output di tool sproporzionato: e' lo scenario che fa esplodere il contesto."""
    rng = random.Random(hash((name, str(arguments))) & 0xFFFF)
    n = rng.choice([50, 200, 5000, 40000])
    return f"[{name}] " + "dato " * n


# ----------------------------------------------------------------- invarianti
def verifica_invarianti(db, cid: str, s) -> list[str]:
    problemi: list[str] = []
    attivi = db.get_messages(cid, active_only=True)
    tutti = db.get_messages(cid, active_only=False)

    if not tutti:
        problemi.append("la conversazione ha ZERO messaggi salvati")
    if not attivi:
        problemi.append("nessun messaggio attivo: la chat e' inutilizzabile")

    seqs = [m["seq"] for m in tutti]
    if seqs != sorted(seqs) or len(set(seqs)) != len(seqs):
        problemi.append("ordine dei messaggi rotto (seq non monotoni o duplicati)")

    # tool_call orfane a DB (il killer permanente della conversazione)
    richieste = {c.get("id") for m in tutti if m.get("tool_calls") for c in m["tool_calls"]}
    risposte = {m.get("tool_call_id") for m in tutti if m["role"] == "tool"}
    if richieste - risposte:
        problemi.append(f"tool_call senza risultato a DB: {sorted(richieste - risposte)[:3]}")

    # payload verso il modello sempre valido e nel budget
    wire = build_context(db, cid, s)
    budget = s.context_window - s.max_output_tokens
    tok = count_messages(wire)
    if tok > budget:
        problemi.append(f"payload di {tok} token oltre il budget di {budget}")
    # Struttura delle tool call nel payload: un gruppo valido e'
    # assistant(tool_calls=[a,b]) seguito dai risultati di a e b, in ordine.
    i = 0
    while i < len(wire):
        m = wire[i]
        if m["role"] == "tool":
            problemi.append(f"risultato di tool orfano nel payload in posizione {i}")
            break
        if m["role"] == "assistant" and m.get("tool_calls"):
            attesi = [c.get("id") for c in m["tool_calls"]]
            j, ottenuti = i + 1, []
            while j < len(wire) and wire[j]["role"] == "tool":
                ottenuti.append(wire[j].get("tool_call_id"))
                j += 1
            if ottenuti != attesi:
                problemi.append(
                    f"gruppo tool incoerente in posizione {i}: attesi {attesi}, trovati {ottenuti}")
                break
            i = j
            continue
        i += 1

    if db.integrity_check() != "ok":
        problemi.append("SQLite riporta corruzione")
    return problemi


# --------------------------------------------------------------------- soak
async def esegui(turni: int, n_conversazioni: int, seed: int, percorso_db: str) -> int:
    rng = random.Random(seed)
    os.environ.setdefault("CONTEXT_WINDOW", "8192")
    os.environ.setdefault("MAX_OUTPUT_TOKENS", "1024")
    config.reset_settings_cache()
    s = config.get_settings()

    db = db_module.Database(percorso_db)
    db_module.set_db(db)
    llm = BackendAvverso(rng)

    import app.agents.loop as loop_mod
    loop_mod.run_tool = tool_finto  # sostituisce i tool veri

    cids = [db.create_conversation(f"soak {i}", "sei un assistente di ricerca") for i in range(n_conversazioni)]
    fallimenti: list[str] = []
    errori_gestiti = 0
    eccezioni_impreviste: list[str] = []
    t0 = time.perf_counter()

    async def un_turno(cid: str, i: int) -> None:
        nonlocal errori_gestiti
        lock = await conversation_lock(cid)
        async with lock:
            # input variabile: normale, lungo, gigantesco, con caratteri strani
            scelta = rng.random()
            if scelta < 0.05:
                testo = "X" * rng.randint(50_000, 200_000)      # incollata enorme
            elif scelta < 0.15:
                testo = " ".join(rng.choice(PAROLE) for _ in range(rng.randint(300, 900)))
            elif scelta < 0.2:
                testo = "emoji 🧪 unicode àèìòù \x00 <script>alert(1)</script> " * 5
            else:
                testo = " ".join(rng.choice(PAROLE) for _ in range(rng.randint(5, 60)))
            db.add_message(cid, "user", testo, tokens=len(testo) // 3)

            try:
                await run_agent_turn(db, llm, cid, use_tools=rng.random() < 0.4)
            except LLMError:
                errori_gestiti += 1        # atteso: il backend finto sbaglia apposta
            except Exception as exc:       # noqa: BLE001
                eccezioni_impreviste.append(f"turno {i} su {cid[:8]}: {type(exc).__name__}: {exc}")

            if rng.random() < 0.08:
                try:
                    await compact(db, llm, cid, force=True)
                except Exception as exc:  # noqa: BLE001
                    eccezioni_impreviste.append(f"compact turno {i}: {type(exc).__name__}: {exc}")
            if rng.random() < 0.03:
                db.revert_last_compaction(cid)

        problemi = verifica_invarianti(db, cid, s)
        for p in problemi:
            riga = f"[turno {i}] conversazione {cid[:8]}: {p}"
            if riga not in fallimenti:
                fallimenti.append(riga)

    # meta' turni sequenziali, meta' a raffica concorrente sulla stessa chat
    for i in range(turni):
        if i % 25 == 24:  # raffica: 5 richieste insieme sulla stessa conversazione
            cid = rng.choice(cids)
            await asyncio.gather(*[un_turno(cid, i) for _ in range(5)])
        else:
            await un_turno(rng.choice(cids), i)
        if i % 50 == 0:
            print(f"  ... turno {i}/{turni} | chiamate LLM {llm.chiamate} | "
                  f"riassunti {llm.riassunti} | problemi {len(fallimenti)}", flush=True)

    durata = time.perf_counter() - t0
    stats = db.stats()
    print("\n" + "=" * 72)
    print(f"SOAK TEST: {turni} turni su {n_conversazioni} conversazioni in {durata:.1f}s")
    print(f"  chiamate al modello ......... {llm.chiamate}")
    print(f"  riassunti richiesti ......... {llm.riassunti}")
    print(f"  errori iniettati dal backend  {llm.errori} (gestiti dall'app: {errori_gestiti})")
    print(f"  compattazioni riuscite ...... {stats['compactions_ok']}")
    print(f"  compattazioni non riuscite .. {stats['compactions_failed']}")
    print(f"  messaggi totali ............. {stats['messages_total']} "
          f"(archiviati {stats['messages_archived']})")
    print(f"  integrita' SQLite ........... {db.integrity_check()}")

    # nessuna conversazione deve essere rimasta vuota o inutilizzabile
    vuote = [c for c in cids if not db.get_messages(c, active_only=True)]
    if vuote:
        fallimenti.append(f"{len(vuote)} conversazioni sono rimaste senza messaggi attivi")

    print("=" * 72)
    if eccezioni_impreviste:
        print(f"\nECCEZIONI NON GESTITE ({len(eccezioni_impreviste)}):")
        for e in eccezioni_impreviste[:15]:
            print("  -", e)
    if fallimenti:
        print(f"\nINVARIANTI VIOLATE ({len(fallimenti)}):")
        for f in fallimenti[:25]:
            print("  -", f)
        print("\nESITO: BUG TROVATI")
        return 1
    if eccezioni_impreviste:
        print("\nESITO: BUG TROVATI (eccezioni non gestite)")
        return 1
    print("\nESITO: nessuna invariante violata. La chat regge il carico.")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--turns", type=int, default=300)
    ap.add_argument("--conversations", type=int, default=8)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--db", default="/tmp/soak_chat.db")
    a = ap.parse_args()
    for suffisso in ("", "-wal", "-shm"):
        try:
            os.remove(a.db + suffisso)
        except OSError:
            pass
    return asyncio.run(esegui(a.turns, a.conversations, a.seed, a.db))


if __name__ == "__main__":
    raise SystemExit(main())
