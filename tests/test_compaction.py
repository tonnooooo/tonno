"""Test della compattazione: qui vivono le regressioni dei bug segnalati.

Ogni test corrisponde a un sintomo reale descritto dall'utente.
"""
from __future__ import annotations

import pytest

from app.compaction import (
    SUMMARY_HEADER, build_context, compact, ensure_fits, needs_compaction, select_range,
)
from app.config import get_settings
from app.tokens import count_messages
from tests.conftest import long_text


async def _riempi(db, cid, turni: int, marker: str = "t") -> None:
    for i in range(turni):
        db.add_message(cid, "user", long_text(f"{marker}-user-{i}"))
        db.add_message(cid, "assistant", long_text(f"{marker}-assistant-{i}"))


# --------------------------------------------------------------- sintomo A
@pytest.mark.asyncio
async def test_dieci_compattazioni_di_fila_non_svuotano_la_chat(db, llm):
    """SINTOMO: «dopo due compattazioni elimina la chat e non funziona piu'».

    Si compatta dieci volte di seguito: la conversazione deve restare
    utilizzabile, con almeno il turno recente e il riassunto sempre presenti.
    """
    cid = db.create_conversation(system_prompt="sei un assistente")
    await _riempi(db, cid, 12)
    totale_iniziale = len(db.get_messages(cid, active_only=False))

    for giro in range(10):
        await _riempi(db, cid, 2, marker=f"g{giro}")
        res = await compact(db, llm, cid, force=True)
        attivi = db.get_messages(cid, active_only=True)

        assert attivi, f"giro {giro}: la conversazione si e' svuotata ({res.status}: {res.reason})"
        assert build_context(db, cid), f"giro {giro}: contesto vuoto verso il modello"
        # nessun messaggio e' mai stato cancellato davvero
        assert len(db.get_messages(cid, active_only=False)) >= totale_iniziale

    finali = db.get_messages(cid, active_only=True)
    assert any(m.get("kind") == "summary" for m in finali), "il riassunto e' andato perso"
    assert any(m["role"] == "user" for m in finali), "i messaggi utente recenti sono spariti"


@pytest.mark.asyncio
async def test_compattazione_ricorsiva_incrementa_il_livello(db, llm):
    """Compattare un riassunto gia' esistente deve produrre un riassunto di
    livello superiore, non cancellare il precedente."""
    cid = db.create_conversation()
    await _riempi(db, cid, 10)
    r1 = await compact(db, llm, cid, force=True)
    assert r1.ok and r1.level == 1
    await _riempi(db, cid, 10)
    r2 = await compact(db, llm, cid, force=True)
    assert r2.ok and r2.level == 2, "il secondo riassunto non ha assorbito il primo"
    assert len(db.get_messages(cid, active_only=False)) > 40  # storico integro


# --------------------------------------------------------------- sintomo B
@pytest.mark.asyncio
async def test_riassunto_a_blocchi_non_supera_mai_la_finestra(db, llm):
    """SINTOMO: «non riesce a compattare».

    Causa: si mandava tutta la cronologia in un'unica richiesta di riassunto.
    Ogni chiamata al modello deve stare nel budget configurato.
    """
    cid = db.create_conversation()
    await _riempi(db, cid, 40)
    s = get_settings()
    res = await compact(db, llm, cid, force=True)
    assert res.ok
    assert llm.summary_calls > 1, "il riassunto non e' stato spezzato in blocchi"
    for call in llm.calls:
        tok = count_messages(call["messages"])
        assert tok <= s.context_window, f"richiesta da {tok} token oltre la finestra"


@pytest.mark.asyncio
async def test_se_il_riassunto_fallisce_la_chat_resta_intatta(db, llm):
    """Il modello non produce nulla di utilizzabile: NON si deve archiviare."""
    cid = db.create_conversation()
    await _riempi(db, cid, 10)
    prima = [m["id"] for m in db.get_messages(cid, active_only=True)]
    llm.empty_summaries = True

    res = await compact(db, llm, cid, force=True)

    assert res.status == "failed"
    assert [m["id"] for m in db.get_messages(cid, active_only=True)] == prima
    assert db.list_compactions(cid)[-1]["status"] == "failed"  # tracciato per la diagnosi


@pytest.mark.asyncio
async def test_backend_llm_giu_degrada_senza_perdere_contenuto(db, llm):
    """Se il backend e' irraggiungibile durante il riassunto si degrada a un
    estratto testuale: meglio un contesto compresso alla buona che una chat
    che non risponde piu'."""
    cid = db.create_conversation()
    await _riempi(db, cid, 12)
    llm.fail_summaries = True
    res = await compact(db, llm, cid, force=True)
    assert res.status in {"ok", "noop"}
    assert db.get_messages(cid, active_only=True)


# --------------------------------------------------------------- sintomo C
@pytest.mark.asyncio
async def test_il_taglio_non_spezza_mai_una_sequenza_di_tool(db, llm):
    """SINTOMO: dopo la compattazione ogni richiesta torna 400.

    Causa: l'assistant con `tool_calls` finiva archiviato e i risultati
    `tool` restavano orfani (payload non valido per l'API OpenAI-compatible).
    """
    cid = db.create_conversation()
    await _riempi(db, cid, 6)
    for i in range(4):
        db.add_message(cid, "assistant", "", tool_calls=[
            {"id": f"call{i}", "type": "function",
             "function": {"name": "web_search", "arguments": '{"query": "x"}'}}])
        db.add_message(cid, "tool", long_text(f"risultato-{i}"), tool_call_id=f"call{i}", name="web_search")
    db.add_message(cid, "assistant", long_text("finale"))

    await compact(db, llm, cid, force=True)

    wire = build_context(db, cid)
    for i, m in enumerate(wire):
        if m["role"] == "tool":
            assert i > 0 and wire[i - 1]["role"] == "assistant" and wire[i - 1].get("tool_calls"), \
                "risultato di tool orfano: il server LLM rifiuterebbe il payload"
    for i, m in enumerate(wire[:-1]):
        if m.get("tool_calls"):
            assert wire[i + 1]["role"] == "tool", "tool_call senza risultato"


@pytest.mark.asyncio
async def test_ordine_cronologico_conservato_dopo_la_compattazione(db, llm):
    """Il riassunto va PRIMA dei messaggi recenti, non in fondo."""
    cid = db.create_conversation()
    await _riempi(db, cid, 10)
    db.add_message(cid, "user", "ULTIMO MESSAGGIO")
    await compact(db, llm, cid, force=True)

    wire = build_context(db, cid)
    posizione_riassunto = next(i for i, m in enumerate(wire) if SUMMARY_HEADER in (m.get("content") or ""))
    assert posizione_riassunto < len(wire) - 1
    assert "ULTIMO MESSAGGIO" in (wire[-1].get("content") or "")


# --------------------------------------------------------------- sintomo D
@pytest.mark.asyncio
async def test_nessuna_compattazione_sotto_soglia(db, llm):
    """Non deve compattare a ogni messaggio: brucia GPU e degrada la qualita'."""
    cid = db.create_conversation()
    db.add_message(cid, "user", "ciao")
    db.add_message(cid, "assistant", "ciao a te")
    assert needs_compaction(db, cid) is False
    res = await compact(db, llm, cid)
    assert res.status == "noop" and llm.summary_calls == 0


@pytest.mark.asyncio
async def test_chat_corta_forzata_e_noop_non_distruttivo(db, llm):
    """Compattazione forzata su chat troppo corta: noop, MAI cancellazione."""
    cid = db.create_conversation()
    db.add_message(cid, "user", "unico messaggio")
    res = await compact(db, llm, cid, force=True)
    assert res.status == "noop"
    assert len(db.get_messages(cid, active_only=True)) == 1


@pytest.mark.asyncio
async def test_ensure_fits_ha_un_tetto_di_iterazioni(db, llm):
    """Senza tetto, una chat che non si riduce manda il server in loop."""
    cid = db.create_conversation()
    await _riempi(db, cid, 30)
    llm.empty_summaries = True  # ogni compattazione fallisce
    risultati = await ensure_fits(db, llm, cid, max_rounds=4)
    assert len(risultati) <= 4
    assert db.get_messages(cid, active_only=True)


# ------------------------------------------------------- rete di sicurezza
def test_messaggio_enorme_viene_troncato_in_uscita_non_a_db(db):
    """Un incollato gigantesco non deve produrre un 400: si tronca solo il
    payload in uscita, il testo originale resta salvato."""
    s = get_settings()
    cid = db.create_conversation()
    enorme = "X" * (s.context_window * 10)
    db.add_message(cid, "user", enorme)
    db.add_message(cid, "assistant", "ok")
    db.add_message(cid, "user", "e adesso?")

    wire = build_context(db, cid)
    assert count_messages(wire) <= s.context_window - s.max_output_tokens
    assert len(db.get_messages(cid)[0]["content"]) == len(enorme)  # a DB e' integro


@pytest.mark.asyncio
async def test_undo_ripristina_i_messaggi_archiviati(db, llm):
    cid = db.create_conversation()
    await _riempi(db, cid, 10)
    attivi_prima = len(db.get_messages(cid, active_only=True))
    res = await compact(db, llm, cid, force=True)
    assert res.ok
    assert len(db.get_messages(cid, active_only=True)) < attivi_prima

    comp = db.revert_last_compaction(cid)
    assert comp is not None and comp["restored_messages"] == res.archived
    assert len(db.get_messages(cid, active_only=True)) == attivi_prima


@pytest.mark.asyncio
async def test_select_range_non_seleziona_gli_ultimi_messaggi(db, llm):
    s = get_settings()
    cid = db.create_conversation()
    await _riempi(db, cid, 12)
    blocco, _ = select_range(db, cid)
    attivi = db.get_messages(cid, active_only=True)
    ids_recenti = {m["id"] for m in attivi[-s.keep_recent_messages:]}
    assert not ({m["id"] for m in blocco} & ids_recenti), "stava per compattare il turno in corso"
