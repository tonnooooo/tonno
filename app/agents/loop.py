"""Ciclo agente con tool calling, a prova di contesto.

Invarianti che qui vengono garantite (e che, violate, rompono la chat in modo
permanente perche' restano scritte a DB):

1. A OGNI `tool_call` dell'assistente corrisponde SEMPRE un messaggio `tool`
   salvato. Se il ciclo si interrompe (limite iterazioni, timeout, errore),
   si scrive comunque un risultato sintetico. Senza questo, la conversazione
   resta con una tool_call orfana e OGNI richiesta successiva viene
   rifiutata dal server con 400: la chat sembra "morta per sempre".
2. Il numero di iterazioni e' limitato: niente loop infiniti di tool.
3. Prima di ogni chiamata al modello si verifica che il contesto entri, e in
   caso contrario si compatta. Gli output dei tool crescono in fretta.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any

from app.agents.tools import run_tool, tool_specs
from app.compaction import build_context, compact, ensure_fits, needs_compaction
from app.config import Settings, get_settings
from app.db import Database
from app.llm import ContextLengthError, LLMClient
from app.tokens import count_message

log = logging.getLogger("app.agents.loop")


@dataclass
class TurnResult:
    content: str
    tool_rounds: int = 0
    compactions: list[dict[str, Any]] = field(default_factory=list)
    usage: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)


def _parse_arguments(raw: Any) -> dict[str, Any]:
    """I modelli locali (Qwen inclusi) sbagliano spesso il JSON degli argomenti.
    Meglio recuperare che far fallire il turno."""
    if isinstance(raw, dict):
        return raw
    if not raw:
        return {}
    text = str(raw).strip()
    try:
        parsed = json.loads(text)
        return parsed if isinstance(parsed, dict) else {"input": parsed}
    except ValueError:
        pass
    # tentativo di riparazione: virgolette singole, code fence, testo attorno
    cleaned = text.strip("`").replace("'", '"')
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start != -1 and end > start:
        try:
            parsed = json.loads(cleaned[start : end + 1])
            if isinstance(parsed, dict):
                return parsed
        except ValueError:
            pass
    log.warning("argomenti tool non parsabili, passati come testo grezzo: %r", text[:200])
    return {"query": text} if text else {}


async def run_agent_turn(
    db: Database,
    llm: LLMClient,
    cid: str,
    *,
    use_tools: bool = False,
    tools: list[str] | None = None,
    settings: Settings | None = None,
    temperature: float = 0.7,
) -> TurnResult:
    """Esegue un turno completo dell'assistente, salvando tutto a DB."""
    s = settings or get_settings()
    result = TurnResult(content="")
    specs = tool_specs(tools) if use_tools else None

    for round_index in range(s.max_tool_iterations + 1):
        # --- 1. il contesto deve entrare PRIMA di chiamare il modello ---
        if needs_compaction(db, cid, s):
            for res in await ensure_fits(db, llm, cid, s):
                result.compactions.append({"status": res.status, "archived": res.archived,
                                           "tokens_before": res.tokens_before,
                                           "tokens_after": res.tokens_after, "reason": res.reason})
                if res.status == "failed":
                    result.warnings.append(f"compattazione fallita: {res.reason}")

        messages = build_context(db, cid, s)

        # --- 2. chiamata al modello, con recupero sul context length ---
        kwargs: dict[str, Any] = {"temperature": temperature}
        if specs:
            kwargs["tools"] = specs
            kwargs["tool_choice"] = "auto"
        try:
            data = await llm.chat(messages, **kwargs)
        except ContextLengthError as exc:
            # Il server dice che non ci sta: si compatta a forza e si riprova
            # una volta sola. E' la situazione in cui prima la chat si piantava.
            log.warning("contesto oltre il limite su %s, compattazione forzata: %s", cid, exc)
            res = await compact(db, llm, cid, s, force=True)
            result.compactions.append({"status": res.status, "archived": res.archived,
                                       "tokens_before": res.tokens_before,
                                       "tokens_after": res.tokens_after, "reason": res.reason})
            messages = build_context(db, cid, s)
            data = await llm.chat(messages, **kwargs)

        choice = data["choices"][0]
        msg = choice.get("message") or {}
        content = (msg.get("content") or "").strip()
        tool_calls = msg.get("tool_calls") or []
        result.usage = data.get("usage") or {}

        # --- 3. nessun tool richiesto: fine turno ---
        if not tool_calls:
            db.add_message(cid, "assistant", content,
                           tokens=count_message({"role": "assistant", "content": content}))
            result.content = content
            return result

        # --- 4. tetto sulle iterazioni: si chiude in modo PULITO ---
        if round_index >= s.max_tool_iterations:
            db.add_message(
                cid, "assistant", content, tool_calls=tool_calls,
                tokens=count_message({"role": "assistant", "content": content, "tool_calls": tool_calls}),
            )
            # invariante 1: ogni tool_call ha comunque il suo risultato
            for call in tool_calls:
                db.add_message(
                    cid, "tool",
                    f"ERRORE: raggiunto il limite di {s.max_tool_iterations} chiamate a strumenti "
                    f"per questo turno; esecuzione non effettuata.",
                    tool_call_id=call.get("id") or "", name=(call.get("function") or {}).get("name"),
                    tokens=64,
                )
            fallback = content or (
                "Ho raggiunto il numero massimo di ricerche per questo messaggio. "
                "Ti riporto quello che ho raccolto finora; chiedimi di continuare se serve altro."
            )
            db.add_message(cid, "assistant", fallback,
                           tokens=count_message({"role": "assistant", "content": fallback}))
            result.content = fallback
            result.tool_rounds = round_index
            result.warnings.append("limite di iterazioni sugli strumenti raggiunto")
            return result

        # --- 5. esecuzione dei tool ---
        db.add_message(
            cid, "assistant", content, tool_calls=tool_calls,
            tokens=count_message({"role": "assistant", "content": content, "tool_calls": tool_calls}),
        )
        for call in tool_calls:
            fn = call.get("function") or {}
            name = fn.get("name") or ""
            args = _parse_arguments(fn.get("arguments"))
            log.info("conversazione %s: eseguo tool %s(%s)", cid, name, list(args))
            output = await run_tool(name, args)
            db.add_message(
                cid, "tool", output, tool_call_id=call.get("id") or "", name=name,
                tokens=count_message({"role": "tool", "content": output}),
            )
        result.tool_rounds = round_index + 1

    # irraggiungibile: il ramo 4 chiude sempre il ciclo
    result.content = result.content or ""
    return result
