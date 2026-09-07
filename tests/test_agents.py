"""Test del ciclo agente: le invarianti che, se violate, restano scritte a DB
e rompono la conversazione per sempre."""
from __future__ import annotations

import pytest

from app.agents.loop import _parse_arguments, run_agent_turn
from app.agents import tools as tools_mod
from app.config import get_settings


def _call(cid: str, name: str = "web_search", args: str = '{"query": "test"}') -> dict:
    return {"id": cid, "type": "function", "function": {"name": name, "arguments": args}}


@pytest.fixture(autouse=True)
def _fake_tool(monkeypatch):
    async def fake_run_tool(name, arguments):
        return f"risultato finto di {name} con {arguments}"

    monkeypatch.setattr("app.agents.loop.run_tool", fake_run_tool)


@pytest.mark.asyncio
async def test_ogni_tool_call_ha_sempre_il_suo_risultato(db, llm):
    """Invariante 1: nessuna tool_call resta orfana, nemmeno al limite di
    iterazioni. Una tool_call orfana fa rifiutare OGNI richiesta successiva."""
    s = get_settings()
    cid = db.create_conversation()
    db.add_message(cid, "user", "cerca una cosa")
    # il modello chiede tool all'infinito
    llm.next_tool_calls = [[_call(f"c{i}")] for i in range(s.max_tool_iterations + 5)]

    res = await run_agent_turn(db, llm, cid, use_tools=True)

    assert res.content, "il turno deve chiudersi con una risposta all'utente"
    messaggi = db.get_messages(cid, active_only=False)
    richieste = [c["id"] for m in messaggi if m.get("tool_calls") for c in m["tool_calls"]]
    risposte = [m["tool_call_id"] for m in messaggi if m["role"] == "tool"]
    assert sorted(richieste) == sorted(risposte), "tool_call senza risultato salvato a DB"


@pytest.mark.asyncio
async def test_limite_di_iterazioni_rispettato(db, llm):
    """Invariante 2: niente loop infinito di chiamate a strumenti."""
    s = get_settings()
    cid = db.create_conversation()
    db.add_message(cid, "user", "cerca")
    llm.next_tool_calls = [[_call(f"c{i}")] for i in range(50)]

    res = await run_agent_turn(db, llm, cid, use_tools=True)

    assert res.tool_rounds <= s.max_tool_iterations
    assert "limite di iterazioni" in " ".join(res.warnings)


@pytest.mark.asyncio
async def test_turno_semplice_senza_tool(db, llm):
    cid = db.create_conversation()
    db.add_message(cid, "user", "ciao")
    llm.reply = "ciao, come posso aiutarti?"
    res = await run_agent_turn(db, llm, cid)
    assert res.content == "ciao, come posso aiutarti?"
    assert db.get_messages(cid)[-1]["role"] == "assistant"


@pytest.mark.asyncio
async def test_recupero_su_errore_di_contesto_del_server(db, llm):
    """Il server risponde 'context length exceeded': si compatta e si riprova,
    invece di restituire errore all'utente."""
    cid = db.create_conversation()
    for i in range(20):
        db.add_message(cid, "user", f"messaggio numero {i} " + "x" * 200)
        db.add_message(cid, "assistant", f"risposta numero {i} " + "y" * 200)
    llm.raise_context_length_once = True

    res = await run_agent_turn(db, llm, cid)

    assert res.content, "il turno doveva concludersi dopo la compattazione di recupero"
    assert any(c["status"] in {"ok", "noop"} for c in res.compactions)


@pytest.mark.parametrize(
    "raw,atteso",
    [
        ('{"query": "roma"}', {"query": "roma"}),
        ({"query": "roma"}, {"query": "roma"}),
        ("{'query': 'roma'}", {"query": "roma"}),                    # virgolette singole
        ('```json\n{"query": "roma"}\n```', {"query": "roma"}),      # code fence
        ("", {}),
        ("roma", {"query": "roma"}),                                  # testo grezzo
    ],
)
def test_argomenti_tool_malformati_vengono_recuperati(raw, atteso):
    """I modelli locali sbagliano spesso il JSON: non deve far cadere il turno."""
    assert _parse_arguments(raw) == atteso


@pytest.mark.asyncio
async def test_output_tool_troncato():
    """Un output enorme di un tool non deve entrare intero nel contesto."""
    testo = tools_mod._truncate("A" * 100_000)
    assert len(testo) < 100_000
    assert "troncato" in testo


@pytest.mark.asyncio
async def test_tool_sconosciuto_non_solleva():
    out = await tools_mod.run_tool("non_esiste", {})
    assert out.startswith("ERRORE")


@pytest.mark.asyncio
async def test_ricerca_senza_searxng_da_messaggio_chiaro():
    out = await tools_mod.run_tool("web_search", {"query": "test"})
    assert "SEARXNG_URL" in out
