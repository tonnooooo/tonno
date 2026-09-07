"""Compattazione del contesto: la parte che si rompeva.

Bug tipici che questo modulo elimina per costruzione:

A. "dopo due compattazioni la chat sparisce"
   Causa classica: la compattazione CANCELLA i messaggi e li sostituisce con
   un riassunto; alla seconda passata il riassunto viene ri-selezionato,
   cancellato a sua volta e non resta niente. Qui i messaggi si archiviano,
   il riassunto e' un messaggio nuovo, e ogni compattazione e' una
   transazione unica: se il riassunto non viene prodotto, non si archivia
   nulla.

B. "la chat non riesce a compattare"
   Causa classica: si manda al modello l'intera cronologia da riassumere,
   che e' proprio la cosa troppo lunga per la finestra -> 400 -> loop di
   fallimenti. Qui il riassunto e' map-reduce a blocchi, ognuno entro
   MAX_SUMMARY_INPUT_TOKENS.

C. "dopo la compattazione il modello risponde errore 400"
   Causa classica: il taglio spezza una coppia assistant(tool_calls) +
   tool result, e l'API OpenAI-compatible rifiuta il payload. Qui il punto
   di taglio viene spostato su un confine sicuro.

D. compattazione a ciclo continuo (ogni messaggio ne scatena una)
   Evitato con soglia di trigger e obiettivo distinti + verifica che la
   compattazione abbia davvero liberato spazio.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any

from app.config import Settings, get_settings
from app.db import Database
from app.llm import LLMClient, LLMError
from app.tokens import count_messages, count_message, count_text

log = logging.getLogger("app.compaction")

SUMMARY_HEADER = "[RIASSUNTO AUTOMATICO DELLA CONVERSAZIONE PRECEDENTE]"

_SUMMARY_SYSTEM_PROMPT = (
    "Sei un compressore di contesto per un assistente conversazionale. "
    "Riassumi lo scambio mantenendo TUTTO cio' che serve a proseguire la conversazione: "
    "obiettivi dell'utente, decisioni prese, fatti, nomi, identificativi, URL, percorsi di file, "
    "parametri, risultati di ricerche e comandi, vincoli e preferenze espresse, "
    "e le questioni ancora aperte. "
    "Non commentare, non salutare, non aggiungere opinioni. "
    "Scrivi in italiano, in punti elenco densi. "
    "Se un dato e' un identificativo esatto (chiave, URL, indirizzo, numero) riportalo alla lettera."
)


@dataclass
class CompactionResult:
    status: str                      # "ok" | "noop" | "failed"
    reason: str = ""
    archived: int = 0
    tokens_before: int = 0
    tokens_after: int = 0
    summary_message_id: int | None = None
    level: int = 0
    details: dict[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.status == "ok"


# --------------------------------------------------------------------- payload
def to_wire(msg: dict[str, Any]) -> dict[str, Any]:
    """Converte una riga del DB nel formato messaggio OpenAI-compatible."""
    out: dict[str, Any] = {"role": msg["role"], "content": msg.get("content") or ""}
    if msg.get("name"):
        out["name"] = msg["name"]
    if msg.get("tool_call_id"):
        out["tool_call_id"] = msg["tool_call_id"]
    if msg.get("tool_calls"):
        out["tool_calls"] = msg["tool_calls"]
        # Con le tool_calls il content deve poter essere vuoto/None.
        out["content"] = msg.get("content") or None
    return out


def build_context(
    db: Database, cid: str, settings: Settings | None = None, *, extra: list[dict[str, Any]] | None = None
) -> list[dict[str, Any]]:
    """Costruisce il payload da mandare al modello a partire dallo stato attivo."""
    s = settings or get_settings()
    conv = db.get_conversation(cid)
    if conv is None:
        raise KeyError(f"conversazione inesistente: {cid}")

    wire: list[dict[str, Any]] = []
    if conv.get("system_prompt"):
        wire.append({"role": "system", "content": conv["system_prompt"]})
    for m in db.get_messages(cid, active_only=True):
        wire.append(to_wire(m))
    if extra:
        wire.extend(extra)
    # L'ordine conta: prima si fa entrare il payload nel budget (che puo'
    # scartare messaggi), POI si ripara la struttura delle tool call.
    return _sanitize_tool_pairs(_enforce_hard_limit(wire, s))


def _sanitize_tool_pairs(msgs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Garanzia finale: il payload in uscita e' SEMPRE strutturalmente valido.

    Qualunque cosa sia successa prima (compattazione, troncamento, scarto di
    messaggi vecchi, un turno interrotto a meta' salvato a DB), qui si esce
    con coppie assistant(tool_calls) -> tool complete:

    - i risultati `tool` senza la loro richiesta vengono scartati;
    - le `tool_calls` senza risultato vengono rimosse dal messaggio assistant.

    Senza questo passaggio basta UN turno interrotto male perche' il server
    OpenAI-compatible risponda 400 a ogni richiesta successiva: la chat
    risulta morta in modo permanente e l'unico rimedio sembra cancellarla.
    """
    out: list[dict[str, Any]] = []
    i, n = 0, len(msgs)
    while i < n:
        m = dict(msgs[i])
        role = m.get("role")

        if role == "tool":
            # Ogni risultato legittimo viene consumato dal ramo dell'assistant
            # qui sotto: se si arriva qui, e' orfano.
            i += 1
            continue

        if role == "assistant" and m.get("tool_calls"):
            j = i + 1
            risultati: list[dict[str, Any]] = []
            while j < n and msgs[j].get("role") == "tool":
                risultati.append(msgs[j])
                j += 1
            presenti = {r.get("tool_call_id") for r in risultati}
            valide = [c for c in m["tool_calls"] if c.get("id") in presenti]
            if not valide:
                m.pop("tool_calls", None)
                m["content"] = m.get("content") or "[richiesta di strumenti non completata]"
                out.append(m)
                i += 1
                continue
            m["tool_calls"] = valide
            ids = {c.get("id") for c in valide}
            out.append(m)
            out.extend(dict(r) for r in risultati if r.get("tool_call_id") in ids)
            i = j
            continue

        if role == "assistant" and m.get("content") is None:
            m["content"] = ""
        out.append(m)
        i += 1
    return out


TRUNC_MARK = "\n[...troncato per limiti di contesto...]"


def _base_content(content: str | None) -> str:
    """Testo senza i marcatori di troncamento gia' applicati."""
    return (content or "").split(TRUNC_MARK)[0]


def _enforce_hard_limit(wire: list[dict[str, Any]], s: Settings) -> list[dict[str, Any]]:
    """Ultima rete di sicurezza prima di uscire verso il modello.

    Se anche dopo la compattazione il payload non entra (un singolo messaggio
    enorme incollato dall'utente, o un output di tool gigante), si tronca il
    CONTENUTO in uscita - non quello salvato a DB - invece di lasciare che il
    server risponda 400 e la chat sembri morta.

    Garanzia: la funzione ritorna SEMPRE un payload che sta nel budget, e non
    lascia mai un risultato di tool orfano.
    """
    budget = s.context_window - s.max_output_tokens
    if count_messages(wire) <= budget:
        return wire

    trimmed = [dict(m) for m in wire]
    has_system = bool(trimmed) and trimmed[0].get("role") == "system"

    def over() -> bool:
        return count_messages(trimmed) > budget

    def shrink(protected: set[int], floor: int) -> None:
        """Dimezza ripetutamente il contenuto piu' pesante finche' non rientra."""
        for _ in range(400):
            if not over():
                return
            cands = [
                i for i in range(len(trimmed))
                if i not in protected and len(_base_content(trimmed[i].get("content"))) > floor
            ]
            if not cands:
                return
            i = max(cands, key=lambda j: count_message(trimmed[j]))
            base = _base_content(trimmed[i].get("content"))
            keep = max(floor, len(base) // 2)
            trimmed[i]["content"] = base[:keep] + TRUNC_MARK

    # Fase 1: si tronca, proteggendo il system prompt e l'ultimo messaggio
    # (il turno in corso: se lo si mutila, il modello risponde a vuoto).
    protected = ({0} if has_system else set()) | {len(trimmed) - 1}
    shrink(protected, 200)

    # Fase 2: si scartano dal payload i turni piu' vecchi, a gruppi interi,
    # per non lasciare tool_calls senza risultato (400 garantito).
    floor_idx = 1 if has_system else 0
    while over() and len(trimmed) > floor_idx + 1:
        idx = floor_idx
        if idx >= len(trimmed) - 1:
            break
        trimmed.pop(idx)
        while idx < len(trimmed) - 1 and trimmed[idx].get("role") == "tool":
            trimmed.pop(idx)  # i risultati seguono l'assistant appena rimosso

    # Fase 3: resta poco, si tronca anche cio' che era protetto.
    shrink(set(), 100)

    # Fase 4: caso estremo (un solo messaggio piu' grande dell'intera finestra).
    if over() and trimmed:
        last = trimmed[-1]
        others = count_messages(trimmed) - count_message(last)
        room = max(64, budget - others - 32)
        last["content"] = _truncate_to_tokens(_base_content(last.get("content")), room)
    if over() and has_system and len(trimmed) > 1:
        head = trimmed[0]
        others = count_messages(trimmed) - count_message(head)
        head["content"] = _truncate_to_tokens(_base_content(head.get("content")),
                                              max(32, budget - others - 32))
    return trimmed


# ------------------------------------------------------------------- decisione
def active_tokens(db: Database, cid: str, s: Settings | None = None) -> int:
    s = s or get_settings()
    return count_messages(build_context(db, cid, s))


def needs_compaction(db: Database, cid: str, s: Settings | None = None) -> bool:
    s = s or get_settings()
    budget = s.context_window - s.max_output_tokens
    return active_tokens(db, cid, s) > budget * s.compaction_trigger_ratio


def _is_safe_cut(messages: list[dict[str, Any]], i: int) -> bool:
    """Un taglio a `i` (archivia [0:i], tiene [i:]) e' sicuro se non lascia
    un risultato di tool orfano dell'assistant che lo ha richiesto."""
    if i <= 0 or i >= len(messages):
        return False
    return messages[i].get("role") != "tool"


def select_range(db: Database, cid: str, s: Settings | None = None) -> tuple[list[dict[str, Any]], str]:
    """Sceglie i messaggi da compattare. Ritorna (messaggi, motivo_se_vuoto)."""
    s = s or get_settings()
    active = db.get_messages(cid, active_only=True)
    if len(active) < s.min_messages_to_compact + s.keep_recent_messages:
        return [], (
            f"troppo pochi messaggi attivi ({len(active)}): servono almeno "
            f"{s.min_messages_to_compact + s.keep_recent_messages}"
        )

    # Punto di taglio ideale: lascia attivi gli ultimi keep_recent_messages,
    # poi si arretra fino al primo confine sicuro.
    cut = len(active) - s.keep_recent_messages
    while cut > 0 and not _is_safe_cut(active, cut):
        cut -= 1
    if cut < s.min_messages_to_compact:
        return [], "nessun punto di taglio sicuro senza spezzare una sequenza di tool call"

    # Se il blocco selezionato pesa meno del riassunto che produrrebbe,
    # compattare peggiorerebbe la situazione.
    block = active[:cut]
    block_tokens = sum(count_message(to_wire(m)) for m in block)
    if block_tokens <= s.summary_max_tokens * 1.2:
        return [], f"il blocco da compattare ({block_tokens} token) non e' piu' grande del riassunto"
    return block, ""


# -------------------------------------------------------------------- riassunto
def _render_block(messages: list[dict[str, Any]]) -> str:
    lines: list[str] = []
    for m in messages:
        role = m["role"].upper()
        if m.get("kind") == "summary":
            role = "RIASSUNTO-PRECEDENTE"
        content = (m.get("content") or "").strip()
        if m.get("tool_calls"):
            content = (content + "\n" if content else "") + f"[richiesta strumenti: {m['tool_calls']}]"
        if not content:
            continue
        lines.append(f"{role}: {content}")
    return "\n\n".join(lines)


def _chunk(messages: list[dict[str, Any]], max_tokens: int) -> list[list[dict[str, Any]]]:
    """Spezza il blocco in pezzi che stanno nel budget del riassunto."""
    chunks: list[list[dict[str, Any]]] = []
    current: list[dict[str, Any]] = []
    current_tokens = 0
    for m in messages:
        t = count_message(to_wire(m))
        if t > max_tokens:
            # Messaggio singolo enorme: entra da solo, verra' troncato dopo.
            if current:
                chunks.append(current)
                current, current_tokens = [], 0
            chunks.append([m])
            continue
        if current and current_tokens + t > max_tokens:
            chunks.append(current)
            current, current_tokens = [], 0
        current.append(m)
        current_tokens += t
    if current:
        chunks.append(current)
    return chunks


def _truncate_to_tokens(text: str, max_tokens: int) -> str:
    if count_text(text) <= max_tokens:
        return text
    # ricerca binaria sulla lunghezza in caratteri
    lo, hi = 0, len(text)
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if count_text(text[:mid]) <= max_tokens:
            lo = mid
        else:
            hi = mid - 1
    return text[:lo] + "\n[...troncato...]"


async def summarize_block(
    llm: LLMClient, messages: list[dict[str, Any]], s: Settings | None = None, *, previous_summary: str = ""
) -> str:
    """Riassunto map-reduce. Non solleva se un blocco fallisce: degrada."""
    s = s or get_settings()
    chunks = _chunk(messages, s.max_summary_input_tokens)
    partials: list[str] = []

    for idx, chunk in enumerate(chunks, start=1):
        body = _truncate_to_tokens(_render_block(chunk), s.max_summary_input_tokens)
        if not body.strip():
            continue
        prefix = ""
        if previous_summary and idx == 1:
            prefix = (
                "Contesto gia' riassunto in precedenza (da integrare, non ripetere alla lettera):\n"
                + _truncate_to_tokens(previous_summary, s.max_summary_input_tokens // 3)
                + "\n\n"
            )
        prompt = (
            f"{prefix}Riassumi il seguente estratto di conversazione "
            f"(parte {idx} di {len(chunks)}):\n\n{body}"
        )
        try:
            text = await llm.chat_text(
                [{"role": "system", "content": _SUMMARY_SYSTEM_PROMPT},
                 {"role": "user", "content": prompt}],
                max_tokens=s.summary_max_tokens,
                temperature=0.2,
            )
        except LLMError as exc:
            log.error("riassunto parte %d/%d fallito: %s", idx, len(chunks), exc)
            # Degrado controllato: si tiene una traccia testuale del blocco
            # invece di perdere il contenuto. Meglio un estratto che il nulla.
            text = _truncate_to_tokens(body, s.summary_max_tokens // 2)
        if text.strip():
            partials.append(text.strip())

    if not partials:
        return ""
    if len(partials) == 1:
        return partials[0]

    # reduce: fonde i riassunti parziali in uno solo
    joined = _truncate_to_tokens("\n\n---\n\n".join(partials), s.max_summary_input_tokens)
    try:
        merged = await llm.chat_text(
            [{"role": "system", "content": _SUMMARY_SYSTEM_PROMPT},
             {"role": "user", "content":
              "Unisci questi riassunti parziali in un unico riassunto coerente e senza ripetizioni, "
              f"mantenendo tutti i dati concreti:\n\n{joined}"}],
            max_tokens=s.summary_max_tokens,
            temperature=0.2,
        )
    except LLMError as exc:
        log.error("fase di merge del riassunto fallita: %s", exc)
        merged = ""
    return (merged or joined).strip()


# ------------------------------------------------------------------- esecuzione
_locks: dict[str, asyncio.Lock] = {}
_locks_guard = asyncio.Lock()


async def conversation_lock(cid: str) -> asyncio.Lock:
    """Un lock per conversazione: impedisce che due richieste in parallelo
    compattino la stessa chat (l'altra causa storica della corruzione)."""
    async with _locks_guard:
        lock = _locks.get(cid)
        if lock is None:
            lock = asyncio.Lock()
            _locks[cid] = lock
        return lock


async def compact(
    db: Database, llm: LLMClient, cid: str, s: Settings | None = None, *, force: bool = False
) -> CompactionResult:
    """Esegue una compattazione. Atomica: o riesce del tutto, o non tocca nulla."""
    s = s or get_settings()
    conv = db.get_conversation(cid)
    if conv is None:
        return CompactionResult("failed", reason="conversazione inesistente")

    tokens_before = active_tokens(db, cid, s)
    budget = s.context_window - s.max_output_tokens
    if not force and tokens_before <= budget * s.compaction_trigger_ratio:
        return CompactionResult("noop", reason="sotto la soglia di compattazione",
                                tokens_before=tokens_before, tokens_after=tokens_before)

    block, why = select_range(db, cid, s)
    if not block:
        # NIENTE da compattare non e' un errore e soprattutto non deve
        # portare a cancellare la chat: si esce senza toccare i dati.
        log.info("compattazione non necessaria per %s: %s", cid, why)
        return CompactionResult("noop", reason=why, tokens_before=tokens_before, tokens_after=tokens_before)

    previous_summary = "\n\n".join(
        (m.get("content") or "") for m in block if m.get("kind") == "summary"
    )
    level = max([int(m.get("compaction_level") or 0) for m in block], default=0) + 1

    summary_text = await summarize_block(llm, block, s, previous_summary=previous_summary)
    if not summary_text.strip():
        with db.tx() as c:
            db.record_compaction(
                c, conversation_id=cid, summary_message_id=None,
                from_seq=block[0]["seq"], to_seq=block[-1]["seq"],
                archived_count=0, tokens_before=tokens_before, tokens_after=tokens_before,
                level=level, status="failed", detail="riassunto vuoto: nessun messaggio archiviato",
            )
        log.error("compattazione %s abortita: riassunto vuoto. Conversazione intatta.", cid)
        return CompactionResult("failed", reason="il modello non ha prodotto un riassunto utilizzabile",
                                tokens_before=tokens_before, tokens_after=tokens_before)

    summary_content = f"{SUMMARY_HEADER}\n{summary_text.strip()}"
    summary_tokens = count_message({"role": "system", "content": summary_content})

    # Verifica di guadagno: se il riassunto non libera spazio, non si archivia.
    block_tokens = sum(count_message(to_wire(m)) for m in block)
    if summary_tokens >= block_tokens:
        with db.tx() as c:
            db.record_compaction(
                c, conversation_id=cid, summary_message_id=None,
                from_seq=block[0]["seq"], to_seq=block[-1]["seq"],
                archived_count=0, tokens_before=tokens_before, tokens_after=tokens_before,
                level=level, status="noop", detail=f"riassunto ({summary_tokens}t) non piu' corto del blocco ({block_tokens}t)",
            )
        return CompactionResult("noop", reason="il riassunto non liberava spazio",
                                tokens_before=tokens_before, tokens_after=tokens_before)

    ids = [int(m["id"]) for m in block]
    with db.tx() as c:
        # Il riassunto prende il posto cronologico del blocco che sostituisce:
        # cosi' resta PRIMA dei messaggi recenti anche dopo compattazioni
        # ripetute, e l'ordine della chat non si scombina mai.
        summary_seq = db.free_seq_after(cid, int(block[-1]["seq"]), c)
        summary_id = db.add_message(
            cid, "system", summary_content, tokens=summary_tokens,
            kind="summary", compaction_level=level, seq=summary_seq, conn=c,
        )
        archived = db.archive_messages(cid, ids, summary_id, c)
        if archived != len(ids):
            # Qualcuno ha modificato lo stato nel frattempo: si annulla tutto.
            raise RuntimeError(
                f"archiviazione incoerente: attesi {len(ids)}, effettuati {archived}"
            )
        db.record_compaction(
            c, conversation_id=cid, summary_message_id=summary_id,
            from_seq=block[0]["seq"], to_seq=block[-1]["seq"],
            archived_count=archived, tokens_before=tokens_before,
            tokens_after=0, level=level, status="ok",
        )

    tokens_after = active_tokens(db, cid, s)
    with db.tx() as c:
        c.execute(
            "UPDATE compactions SET tokens_after=? WHERE conversation_id=? AND summary_message_id=?",
            (tokens_after, cid, summary_id),
        )
    log.info("compattazione %s livello %d: %d messaggi archiviati, %d -> %d token",
             cid, level, archived, tokens_before, tokens_after)
    return CompactionResult(
        "ok", archived=archived, tokens_before=tokens_before, tokens_after=tokens_after,
        summary_message_id=summary_id, level=level,
    )


async def ensure_fits(
    db: Database, llm: LLMClient, cid: str, s: Settings | None = None, *, max_rounds: int = 4
) -> list[CompactionResult]:
    """Compatta finche' il contesto rientra, con un tetto di iterazioni.

    Il tetto e' essenziale: senza, una conversazione che non riesce a
    ridursi manda il server in loop infinito (sintomo: chat che si blocca
    e CPU/GPU a palla)."""
    s = s or get_settings()
    results: list[CompactionResult] = []
    budget = s.context_window - s.max_output_tokens
    for _ in range(max_rounds):
        if active_tokens(db, cid, s) <= budget * s.compaction_target_ratio:
            break
        res = await compact(db, llm, cid, s, force=True)
        results.append(res)
        if res.status != "ok":
            break  # inutile insistere: interviene _enforce_hard_limit
    return results
