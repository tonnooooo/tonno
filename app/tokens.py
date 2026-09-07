"""Conteggio token.

Perche' e' un modulo a se': quasi tutti i bug del tipo "dopo un po' la chat
si rompe" nascono da un conteggio token sbagliato o assente. Se stimi meno
del reale, il server LLM risponde 400 (context length exceeded) e la chat
sembra "morta". Qui si stima sempre per eccesso, con margine.
"""
from __future__ import annotations

import json
from typing import Any, Iterable

_ENCODER = None
_ENCODER_TRIED = False

# Overhead per messaggio nel template di chat (role, delimitatori, a capo).
# I template ChatML (Qwen, Gemma, Llama) costano ~4-8 token per messaggio.
PER_MESSAGE_OVERHEAD = 8
# Token di coda aggiunti dal template per aprire il turno dell'assistente.
PER_REQUEST_OVERHEAD = 8
# Margine di sicurezza: meglio compattare un filo prima che ricevere un 400.
SAFETY_MARGIN = 1.08


def _encoder():
    global _ENCODER, _ENCODER_TRIED
    if not _ENCODER_TRIED:
        _ENCODER_TRIED = True
        try:  # tiktoken e' opzionale: se manca si usa l'euristica
            import tiktoken

            _ENCODER = tiktoken.get_encoding("cl100k_base")
        except Exception:
            _ENCODER = None
    return _ENCODER


def count_text(text: str | None) -> int:
    """Token di una stringa. Stima per eccesso quando tiktoken non c'e'."""
    if not text:
        return 0
    enc = _encoder()
    if enc is not None:
        try:
            return len(enc.encode(text, disallowed_special=()))
        except Exception:
            pass
    # Euristica: l'italiano tokenizza peggio dell'inglese (~3.2 char/token).
    # Si usa 3.0 per stare larghi, con un minimo di 1 token per parola.
    approx_chars = len(text) / 3.0
    approx_words = text.count(" ") + 1
    return int(max(approx_chars, approx_words) + 1)


def count_message(message: dict[str, Any]) -> int:
    """Token di un singolo messaggio in formato OpenAI-compatible."""
    total = PER_MESSAGE_OVERHEAD
    total += count_text(message.get("role"))
    content = message.get("content")
    if isinstance(content, str):
        total += count_text(content)
    elif isinstance(content, list):  # content multimodale/parti
        for part in content:
            if isinstance(part, dict):
                total += count_text(part.get("text", ""))
            else:
                total += count_text(str(part))
    elif content is not None:
        total += count_text(str(content))

    if message.get("name"):
        total += count_text(message["name"])
    if message.get("tool_call_id"):
        total += count_text(message["tool_call_id"])
    tool_calls = message.get("tool_calls")
    if tool_calls:
        # Le tool call vengono serializzate nel prompt: si contano come JSON.
        try:
            total += count_text(json.dumps(tool_calls, ensure_ascii=False))
        except (TypeError, ValueError):
            total += count_text(str(tool_calls))
    return total


def count_messages(messages: Iterable[dict[str, Any]]) -> int:
    """Token dell'intera conversazione, margine di sicurezza incluso."""
    raw = sum(count_message(m) for m in messages) + PER_REQUEST_OVERHEAD
    return int(raw * SAFETY_MARGIN) + 1


def fits(messages: Iterable[dict[str, Any]], context_window: int, max_output_tokens: int) -> bool:
    return count_messages(messages) + max_output_tokens <= context_window
