"""Test della persistenza: e' il livello dove nascevano le chat corrotte."""
from __future__ import annotations

import pytest

from app.db import SEQ_STEP, Database


def test_seq_monotono_e_unico(db):
    cid = db.create_conversation()
    for i in range(10):
        db.add_message(cid, "user", f"m{i}")
    seqs = [m["seq"] for m in db.get_messages(cid)]
    assert seqs == sorted(seqs) and len(set(seqs)) == 10
    assert seqs[1] - seqs[0] == SEQ_STEP  # spazio per inserire i riassunti


def test_rollback_transazione_non_lascia_meta_scritture(db):
    cid = db.create_conversation()
    db.add_message(cid, "user", "primo")
    with pytest.raises(RuntimeError):
        with db.tx() as c:
            db.add_message(cid, "user", "secondo", conn=c)
            raise RuntimeError("boom a meta' transazione")
    assert [m["content"] for m in db.get_messages(cid)] == ["primo"]
    assert db.integrity_check() == "ok"


def test_cancellazione_e_logica_e_reversibile(db):
    cid = db.create_conversation("da cancellare")
    db.add_message(cid, "user", "contenuto importante")
    assert db.soft_delete_conversation(cid) is True
    assert db.get_conversation(cid) is None                  # invisibile
    assert db.get_conversation(cid, include_deleted=True)    # ma non persa
    assert db.restore_conversation(cid) is True
    assert len(db.get_messages(cid)) == 1


def test_archiviazione_non_cancella_mai(db):
    cid = db.create_conversation()
    ids = [db.add_message(cid, "user", f"m{i}") for i in range(5)]
    sid = db.add_message(cid, "system", "riassunto", kind="summary")
    with db.tx() as c:
        assert db.archive_messages(cid, ids[:3], sid, c) == 3
    assert len(db.get_messages(cid, active_only=True)) == 3   # 2 residui + riassunto
    assert len(db.get_messages(cid, active_only=False)) == 6  # niente e' sparito


def test_free_seq_after_inserisce_in_mezzo(db):
    cid = db.create_conversation()
    db.add_message(cid, "user", "a")
    db.add_message(cid, "user", "b")
    with db.tx() as c:
        s = db.free_seq_after(cid, SEQ_STEP, c)
        mid = db.add_message(cid, "system", "riassunto", kind="summary", seq=s, conn=c)
    ordine = [m["id"] for m in db.get_messages(cid)]
    assert ordine.index(mid) == 1  # il riassunto sta in mezzo, non in coda


def test_wal_attivo_e_integrita(db):
    mode = db._conn.execute("PRAGMA journal_mode").fetchone()[0]
    assert mode.lower() == "wal"
    assert db.integrity_check() == "ok"


def test_messaggio_su_conversazione_inesistente_non_scrive(db):
    with pytest.raises(KeyError):
        db.add_message("non-esiste", "user", "ciao")
    assert db.stats()["messages_total"] == 0


def test_riavvio_del_processo_non_perde_messaggi(tmp_path):
    """SINTOMO: si riavvia il servizio (o la VM) e la chat non si apre piu'.

    Con un file JSON riscritto a ogni turno bastava un riavvio nel momento
    sbagliato. Con SQLite in WAL i dati confermati sono sempre rileggibili.
    """
    percorso = str(tmp_path / "riavvio.db")
    primo = Database(percorso)
    cid = primo.create_conversation("prima del riavvio")
    for i in range(50):
        primo.add_message(cid, "user" if i % 2 == 0 else "assistant", f"messaggio {i}")
    primo.close()  # riavvio pulito

    secondo = Database(percorso)
    assert secondo.integrity_check() == "ok"
    assert len(secondo.get_messages(cid)) == 50
    assert secondo.get_conversation(cid)["title"] == "prima del riavvio"
    secondo.close()


def test_riavvio_brutale_senza_close_recupera_dal_wal(tmp_path):
    """Riavvio senza chiusura pulita (kill -9, VM staccata): il WAL viene
    riprodotto all'apertura successiva, i messaggi confermati ci sono."""
    percorso = str(tmp_path / "kill9.db")
    primo = Database(percorso)
    cid = primo.create_conversation("kill -9")
    for i in range(30):
        primo.add_message(cid, "user", f"m{i}")
    del primo  # nessun close(): simula la terminazione brutale

    secondo = Database(percorso)
    assert secondo.integrity_check() == "ok"
    assert len(secondo.get_messages(cid)) == 30
    secondo.close()


def test_scritture_concorrenti_da_piu_thread(tmp_path):
    """Doppio invio dal browser / piu' worker: nessuna scrittura persa,
    nessun seq duplicato, nessun 'database is locked'."""
    import threading

    database = Database(str(tmp_path / "concorrenza.db"))
    cid = database.create_conversation()
    errori: list[Exception] = []

    def scrivi(n: int) -> None:
        try:
            for i in range(40):
                database.add_message(cid, "user", f"t{n}-m{i}")
        except Exception as exc:  # noqa: BLE001
            errori.append(exc)

    threads = [threading.Thread(target=scrivi, args=(n,)) for n in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errori, f"errori in scrittura concorrente: {errori[:3]}"
    messaggi = database.get_messages(cid)
    assert len(messaggi) == 320
    seqs = [m["seq"] for m in messaggi]
    assert len(set(seqs)) == 320 and seqs == sorted(seqs)
    assert database.integrity_check() == "ok"
    database.close()
