"""Test end-to-end dell'API con backend LLM finto."""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from app import db as db_module, llm as llm_module


@pytest.fixture
def client(db, llm, monkeypatch):
    from app.main import app

    db_module.set_db(db)
    llm_module.set_llm(llm)
    with TestClient(app) as c:
        yield c
    llm_module.set_llm(None)


def _nuova(client, **kw) -> str:
    r = client.post("/conversations", json={"title": "prova", "system_prompt": "sei utile", **kw})
    assert r.status_code == 201
    return r.json()["id"]


def test_ciclo_completo(client, llm):
    cid = _nuova(client)
    llm.reply = "risposta del modello"
    r = client.post(f"/conversations/{cid}/messages", json={"content": "ciao"})
    assert r.status_code == 200, r.text
    assert r.json()["content"] == "risposta del modello"

    r = client.get(f"/conversations/{cid}")
    ruoli = [m["role"] for m in r.json()["messages"]]
    assert ruoli == ["user", "assistant"]


def test_conversazione_inesistente_da_404_non_500(client):
    assert client.post("/conversations/xxx/messages", json={"content": "ciao"}).status_code == 404
    assert client.get("/conversations/xxx").status_code == 404


def test_errore_llm_torna_strutturato_e_non_perde_il_messaggio(client, llm, monkeypatch):
    cid = _nuova(client)

    async def esplode(*a, **k):
        raise llm_module.LLMError("backend spento", kind="network", retryable=True)

    monkeypatch.setattr(llm, "chat", esplode)
    r = client.post(f"/conversations/{cid}/messages", json={"content": "domanda importante"})
    assert r.status_code == 503
    body = r.json()["detail"]
    assert body["error_kind"] == "network" and body["retryable"] is True

    # il messaggio dell'utente e' comunque salvato: al retry non si riscrive
    messaggi = client.get(f"/conversations/{cid}").json()["messages"]
    assert messaggi[-1]["content"] == "domanda importante"


def test_cancellazione_e_ripristino(client):
    cid = _nuova(client)
    client.post(f"/conversations/{cid}/messages", json={"content": "ciao"})
    assert client.delete(f"/conversations/{cid}").json()["recoverable"] is True
    assert client.get(f"/conversations/{cid}").status_code == 404
    assert client.post(f"/conversations/{cid}/restore").status_code == 200
    assert len(client.get(f"/conversations/{cid}").json()["messages"]) == 2


def test_stats_e_compattazione_manuale(client, llm):
    cid = _nuova(client)
    for i in range(14):
        llm.reply = f"risposta lunga numero {i} " + "parola " * 60
        client.post(f"/conversations/{cid}/messages", json={"content": f"domanda {i} " + "testo " * 60})

    stats = client.get(f"/conversations/{cid}/stats").json()
    assert stats["messages_active"] >= 1
    assert stats["context_tokens"] > 0

    r = client.post(f"/conversations/{cid}/compact", json={"force": True})
    assert r.status_code == 200
    body = r.json()
    assert body["status"] in {"ok", "noop"}

    dopo = client.get(f"/conversations/{cid}/stats").json()
    assert dopo["messages_total"] >= stats["messages_total"]  # nulla e' stato cancellato
    if body["status"] == "ok":
        assert dopo["messages_archived"] > 0
        assert dopo["summaries"] >= 1


def test_undo_compattazione(client, llm):
    cid = _nuova(client)
    for i in range(14):
        llm.reply = "risposta " + "parola " * 60
        client.post(f"/conversations/{cid}/messages", json={"content": f"domanda {i} " + "testo " * 60})
    assert client.post(f"/conversations/{cid}/compact", json={"force": True}).json()["status"] == "ok"
    r = client.post(f"/conversations/{cid}/compact/undo")
    assert r.status_code == 200 and r.json()["restored_messages"] > 0


def test_anteprima_contesto(client, llm):
    cid = _nuova(client)
    client.post(f"/conversations/{cid}/messages", json={"content": "ciao"})
    r = client.get(f"/conversations/{cid}/context").json()
    assert r["messages"][0]["role"] == "system"
    assert r["tokens"] > 0


def test_streaming_salva_la_risposta(client, llm):
    cid = _nuova(client)
    llm.reply = "questa risposta arriva a pezzi"
    with client.stream("POST", f"/conversations/{cid}/messages/stream", json={"content": "ciao"}) as r:
        assert r.status_code == 200
        pezzi = [json.loads(line[5:])["delta"]
                 for line in r.iter_lines()
                 if line.startswith("data:") and "[DONE]" not in line]
    assert "".join(pezzi).strip() == llm.reply
    messaggi = client.get(f"/conversations/{cid}").json()["messages"]
    assert messaggi[-1]["role"] == "assistant" and messaggi[-1]["content"] == llm.reply


def test_health_profonda(client):
    r = client.get("/health/deep").json()
    assert r["db"]["integrity"] == "ok"
    assert r["llm"]["reachable"] is True
    assert r["problems"] == []


def test_validazione_input(client):
    cid = _nuova(client)
    assert client.post(f"/conversations/{cid}/messages", json={"content": ""}).status_code == 422
    assert client.post(f"/conversations/{cid}/messages",
                       json={"content": "ok", "temperature": 9}).status_code == 422
