"""API FastAPI della chat.

Punti chiave rispetto ai problemi segnalati:
- un lock per conversazione: due invii contemporanei (doppio click, retry del
  browser) non possono piu' corrompere l'ordine dei messaggi;
- ogni errore torna come JSON strutturato con `error_kind`: il frontend puo'
  distinguere "backend LLM giu'" da "conversazione inesistente" invece di
  mostrare una schermata vuota;
- lo streaming salva SEMPRE quello che ha generato, anche se il client si
  disconnette a meta': niente turni fantasma che sbilanciano la cronologia;
- endpoint di diagnostica e di ripristino della compattazione.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any, AsyncIterator

from fastapi import APIRouter, Body, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from app.agents.loop import run_agent_turn
from app.compaction import (
    SUMMARY_HEADER, active_tokens, build_context, compact, conversation_lock,
    ensure_fits, needs_compaction,
)
from app.config import get_settings
from app.db import Database, get_db
from app.llm import ContextLengthError, LLMClient, LLMError, get_llm
from app.tokens import count_message

log = logging.getLogger("app.api")
router = APIRouter()


# --------------------------------------------------------------------- schemi
class ConversationCreate(BaseModel):
    title: str = Field(default="Nuova chat", max_length=300)
    system_prompt: str = Field(default="", max_length=20000)
    model: str | None = None


class ConversationUpdate(BaseModel):
    title: str | None = Field(default=None, max_length=300)
    system_prompt: str | None = Field(default=None, max_length=20000)
    model: str | None = None


class MessageIn(BaseModel):
    content: str = Field(min_length=1, max_length=200000)
    use_tools: bool = False
    tools: list[str] | None = None
    temperature: float = Field(default=0.7, ge=0.0, le=2.0)


def db_dep() -> Database:
    return get_db()


def llm_dep() -> LLMClient:
    return get_llm()


def _conv_or_404(db: Database, cid: str) -> dict[str, Any]:
    conv = db.get_conversation(cid)
    if conv is None:
        raise HTTPException(status_code=404, detail=f"conversazione {cid} non trovata")
    return conv


# -------------------------------------------------------------------- health
@router.get("/health")
async def health() -> dict[str, Any]:
    return {"status": "ok", "time": time.time()}


@router.get("/health/deep")
async def health_deep(db: Database = Depends(db_dep), llm: LLMClient = Depends(llm_dep)) -> dict[str, Any]:
    s = get_settings()
    db_stats = await run_in_threadpool(db.stats)
    integrity = await run_in_threadpool(db.integrity_check)
    llm_health = await llm.health()
    problems = s.validate()
    if integrity != "ok":
        problems.append(f"integrita' SQLite: {integrity}")
    if not llm_health.get("reachable"):
        problems.append(f"backend LLM non raggiungibile su {s.llm_base_url}")
    return {
        "status": "ok" if not problems else "degraded",
        "problems": problems,
        "db": {**db_stats, "integrity": integrity},
        "llm": {**llm_health, "base_url": s.llm_base_url, "model": s.llm_model},
        "context": {
            "window": s.context_window,
            "max_output_tokens": s.max_output_tokens,
            "trigger_ratio": s.compaction_trigger_ratio,
            "target_ratio": s.compaction_target_ratio,
            "keep_recent_messages": s.keep_recent_messages,
        },
    }


# ------------------------------------------------------------- conversazioni
@router.post("/conversations", status_code=201)
async def create_conversation(body: ConversationCreate, db: Database = Depends(db_dep)) -> dict[str, Any]:
    cid = await run_in_threadpool(
        db.create_conversation, body.title, body.system_prompt, body.model or get_settings().llm_model
    )
    return await run_in_threadpool(db.get_conversation, cid)


@router.get("/conversations")
async def list_conversations(limit: int = 50, offset: int = 0, db: Database = Depends(db_dep)) -> dict[str, Any]:
    limit = max(1, min(limit, 200))
    items = await run_in_threadpool(db.list_conversations, limit, max(0, offset))
    return {"items": items, "limit": limit, "offset": offset}


@router.get("/conversations/{cid}")
async def get_conversation(cid: str, include_archived: bool = False, db: Database = Depends(db_dep)) -> dict[str, Any]:
    conv = await run_in_threadpool(_conv_or_404, db, cid)
    messages = await run_in_threadpool(lambda: db.get_messages(cid, active_only=not include_archived))
    return {"conversation": conv, "messages": messages}


@router.patch("/conversations/{cid}")
async def update_conversation(cid: str, body: ConversationUpdate, db: Database = Depends(db_dep)) -> dict[str, Any]:
    await run_in_threadpool(_conv_or_404, db, cid)
    fields = {k: v for k, v in body.model_dump().items() if v is not None}
    if fields:
        await run_in_threadpool(lambda: db.update_conversation(cid, **fields))
    return await run_in_threadpool(db.get_conversation, cid)


@router.delete("/conversations/{cid}")
async def delete_conversation(cid: str, db: Database = Depends(db_dep)) -> dict[str, Any]:
    """Cancellazione LOGICA: i dati restano su disco e sono ripristinabili."""
    await run_in_threadpool(_conv_or_404, db, cid)
    await run_in_threadpool(db.soft_delete_conversation, cid)
    return {"deleted": cid, "recoverable": True,
            "hint": f"POST /conversations/{cid}/restore per ripristinarla"}


@router.post("/conversations/{cid}/restore")
async def restore_conversation(cid: str, db: Database = Depends(db_dep)) -> dict[str, Any]:
    conv = await run_in_threadpool(db.get_conversation, cid, True)
    if conv is None:
        raise HTTPException(status_code=404, detail=f"conversazione {cid} non trovata")
    await run_in_threadpool(db.restore_conversation, cid)
    return await run_in_threadpool(db.get_conversation, cid)


# ------------------------------------------------------------------ messaggi
async def _persist_user_message(db: Database, cid: str, content: str) -> int:
    return await run_in_threadpool(
        lambda: db.add_message(cid, "user", content,
                               tokens=count_message({"role": "user", "content": content}))
    )


@router.post("/conversations/{cid}/messages")
async def post_message(
    cid: str, body: MessageIn, db: Database = Depends(db_dep), llm: LLMClient = Depends(llm_dep)
) -> dict[str, Any]:
    await run_in_threadpool(_conv_or_404, db, cid)
    lock = await conversation_lock(cid)
    async with lock:  # niente due turni in parallelo sulla stessa chat
        await _persist_user_message(db, cid, body.content)
        try:
            turn = await run_agent_turn(
                db, llm, cid, use_tools=body.use_tools, tools=body.tools, temperature=body.temperature
            )
        except LLMError as exc:
            # Il messaggio dell'utente resta salvato: al retry non si perde nulla.
            raise HTTPException(
                status_code=503 if exc.retryable else 502,
                detail={"message": str(exc), "error_kind": exc.kind, "retryable": exc.retryable},
            ) from exc
        tokens = await run_in_threadpool(active_tokens, db, cid)
        return {
            "content": turn.content,
            "tool_rounds": turn.tool_rounds,
            "compactions": turn.compactions,
            "warnings": turn.warnings,
            "usage": turn.usage,
            "context_tokens": tokens,
        }


@router.post("/conversations/{cid}/messages/stream")
async def post_message_stream(
    cid: str, request: Request, body: MessageIn,
    db: Database = Depends(db_dep), llm: LLMClient = Depends(llm_dep),
) -> StreamingResponse:
    """Streaming SSE. Il testo generato viene salvato anche se il client cade."""
    await run_in_threadpool(_conv_or_404, db, cid)

    async def gen() -> AsyncIterator[str]:
        lock = await conversation_lock(cid)
        async with lock:
            await _persist_user_message(db, cid, body.content)
            pieces: list[str] = []
            try:
                comp = []
                if await run_in_threadpool(needs_compaction, db, cid, None):
                    for res in await ensure_fits(db, llm, cid):
                        comp.append({"status": res.status, "archived": res.archived,
                                     "tokens_after": res.tokens_after, "reason": res.reason})
                    yield f"event: compaction\ndata: {json.dumps(comp, ensure_ascii=False)}\n\n"

                messages = await run_in_threadpool(build_context, db, cid, None)
                try:
                    stream = llm.stream_chat(messages, temperature=body.temperature)
                    async for chunk in stream:
                        delta = ((chunk.get("choices") or [{}])[0].get("delta") or {}).get("content")
                        if not delta:
                            continue
                        pieces.append(delta)
                        yield f"data: {json.dumps({'delta': delta}, ensure_ascii=False)}\n\n"
                except ContextLengthError:
                    await compact(db, llm, cid, force=True)
                    messages = await run_in_threadpool(build_context, db, cid, None)
                    async for chunk in llm.stream_chat(messages, temperature=body.temperature):
                        delta = ((chunk.get("choices") or [{}])[0].get("delta") or {}).get("content")
                        if not delta:
                            continue
                        pieces.append(delta)
                        yield f"data: {json.dumps({'delta': delta}, ensure_ascii=False)}\n\n"
            except LLMError as exc:
                yield ("event: error\ndata: "
                       + json.dumps({"message": str(exc), "error_kind": exc.kind,
                                     "retryable": exc.retryable}, ensure_ascii=False) + "\n\n")
            except asyncio.CancelledError:
                log.info("client disconnesso da %s: salvo il parziale", cid)
                raise
            finally:
                # Invariante: quello che e' stato generato viene salvato.
                text = "".join(pieces).strip()
                if text:
                    await run_in_threadpool(
                        lambda: db.add_message(
                            cid, "assistant", text,
                            tokens=count_message({"role": "assistant", "content": text}),
                        )
                    )
            yield "data: [DONE]\n\n"

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive"},
    )


# -------------------------------------------------------------- compattazione
@router.get("/conversations/{cid}/stats")
async def conversation_stats(cid: str, db: Database = Depends(db_dep)) -> dict[str, Any]:
    conv = await run_in_threadpool(_conv_or_404, db, cid)
    s = get_settings()
    tokens = await run_in_threadpool(active_tokens, db, cid)
    active = await run_in_threadpool(lambda: db.get_messages(cid, active_only=True))
    every = await run_in_threadpool(lambda: db.get_messages(cid, active_only=False))
    comps = await run_in_threadpool(db.list_compactions, cid)
    budget = s.context_window - s.max_output_tokens
    return {
        "conversation_id": cid,
        "title": conv["title"],
        "context_tokens": tokens,
        "context_budget": budget,
        "usage_ratio": round(tokens / budget, 3) if budget else None,
        "compaction_at": round(budget * s.compaction_trigger_ratio),
        "needs_compaction": tokens > budget * s.compaction_trigger_ratio,
        "messages_active": len(active),
        "messages_total": len(every),
        "messages_archived": len(every) - len(active),
        "summaries": sum(1 for m in active if m.get("kind") == "summary"),
        "compactions": comps,
    }


@router.post("/conversations/{cid}/compact")
async def force_compact(
    cid: str, db: Database = Depends(db_dep), llm: LLMClient = Depends(llm_dep),
    force: bool = Body(default=True, embed=True),
) -> dict[str, Any]:
    await run_in_threadpool(_conv_or_404, db, cid)
    lock = await conversation_lock(cid)
    async with lock:
        res = await compact(db, llm, cid, force=force)
    return {
        "status": res.status, "reason": res.reason, "archived": res.archived,
        "tokens_before": res.tokens_before, "tokens_after": res.tokens_after,
        "summary_message_id": res.summary_message_id, "level": res.level,
    }


@router.post("/conversations/{cid}/compact/undo")
async def undo_compaction(cid: str, db: Database = Depends(db_dep)) -> dict[str, Any]:
    """Ripristina i messaggi dell'ultima compattazione.

    Esiste solo perche' i messaggi non vengono mai cancellati: e' la rete di
    sicurezza per quando un riassunto viene male e si vuole tornare indietro.
    """
    await run_in_threadpool(_conv_or_404, db, cid)
    lock = await conversation_lock(cid)
    async with lock:
        comp = await run_in_threadpool(db.revert_last_compaction, cid)
    if comp is None:
        raise HTTPException(status_code=404, detail="nessuna compattazione da annullare")
    return {"reverted": comp["id"], "restored_messages": comp["restored_messages"]}


@router.get("/conversations/{cid}/context")
async def preview_context(cid: str, db: Database = Depends(db_dep)) -> dict[str, Any]:
    """Mostra ESATTAMENTE il payload che verrebbe mandato al modello.

    E' l'endpoint da guardare per capire perche' il modello 'ha perso il filo':
    se qui manca qualcosa, il problema e' la compattazione, non il modello.
    """
    await run_in_threadpool(_conv_or_404, db, cid)
    wire = await run_in_threadpool(build_context, db, cid, None)
    return {"messages": wire, "tokens": sum(count_message(m) for m in wire),
            "has_summary": any(SUMMARY_HEADER in (m.get("content") or "") for m in wire)}
