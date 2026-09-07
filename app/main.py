"""Entrypoint FastAPI.

Avvio consigliato sulla VM:
    uvicorn app.main:app --host 0.0.0.0 --port 8080 --workers 1

ATTENZIONE ai worker: con SQLite e i lock per conversazione questo servizio va
tenuto a UN processo (i thread bastano abbondantemente, il collo di bottiglia
e' la GPU). Piu' worker significa piu' processi che scrivono lo stesso file e
lock applicativi che non si vedono tra loro: e' un'altra strada verso la chat
corrotta. Se serve scalare, si mette un reverse proxy davanti e si passa a
Postgres.
"""
from __future__ import annotations

import logging
import os
import time
import uuid

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api import router
from app.config import get_settings
from app.db import get_db
from app.llm import LLMError, get_llm

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
)
log = logging.getLogger("app")

app = FastAPI(
    title="Chat backend",
    version="2.0.0",
    description="Backend chat con compattazione del contesto sicura e agenti di ricerca.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=(os.getenv("CORS_ORIGINS", "*").split(",")),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def request_context(request: Request, call_next):
    """Request id + tempi in log. Senza questo, diagnosticare 'ogni tanto si
    rompe' su una VM remota e' impossibile."""
    rid = request.headers.get("x-request-id") or uuid.uuid4().hex[:12]
    started = time.perf_counter()
    try:
        response = await call_next(request)
    except Exception:
        log.exception("[%s] %s %s ESPLOSA dopo %.0fms", rid, request.method, request.url.path,
                      (time.perf_counter() - started) * 1000)
        raise
    elapsed = (time.perf_counter() - started) * 1000
    response.headers["x-request-id"] = rid
    response.headers["x-elapsed-ms"] = f"{elapsed:.0f}"
    if elapsed > 5000 or response.status_code >= 500:
        log.warning("[%s] %s %s -> %d in %.0fms", rid, request.method, request.url.path,
                    response.status_code, elapsed)
    return response


@app.exception_handler(LLMError)
async def llm_error_handler(_: Request, exc: LLMError) -> JSONResponse:
    return JSONResponse(
        status_code=503 if exc.retryable else 502,
        content={"detail": {"message": str(exc), "error_kind": exc.kind, "retryable": exc.retryable}},
    )


@app.exception_handler(Exception)
async def unhandled_handler(request: Request, exc: Exception) -> JSONResponse:
    """Nessun 500 muto: il frontend riceve sempre un motivo leggibile."""
    log.exception("errore non gestito su %s", request.url.path)
    return JSONResponse(
        status_code=500,
        content={"detail": {"message": f"errore interno: {type(exc).__name__}: {exc}",
                            "error_kind": "internal", "retryable": False}},
    )


@app.on_event("startup")
async def on_startup() -> None:
    s = get_settings()
    problems = s.validate()
    for p in problems:
        log.error("CONFIGURAZIONE: %s", p)
    db = get_db()
    integrity = db.integrity_check()
    if integrity != "ok":
        log.error("SQLite riporta problemi di integrita': %s", integrity)
    log.info("avviato | modello=%s | contesto=%d | db=%s | messaggi=%d",
             s.llm_model, s.context_window, s.db_path, db.stats()["messages_total"])


@app.on_event("shutdown")
async def on_shutdown() -> None:
    try:
        await get_llm().aclose()
    finally:
        get_db().close()
    log.info("spento pulito")


app.include_router(router)
