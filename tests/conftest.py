"""Fixture condivise: un backend LLM finto, controllabile e deterministico.

Serve a testare la logica di chat/compattazione senza GPU: i test girano in
CI o sul portatile e riproducono esattamente gli scenari che sulla VM si
vedevano solo dopo ore di conversazione.
"""
from __future__ import annotations

import os
import sys
from typing import Any, AsyncIterator

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import config, db as db_module  # noqa: E402
from app.llm import LLMError  # noqa: E402


class FakeLLM:
    """Sostituto di LLMClient. Registra le chiamate e sa fallire a comando."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.summary_calls = 0
        self.fail_summaries = False
        self.empty_summaries = False
        self.reply = "va bene"
        self.next_tool_calls: list[list[dict[str, Any]]] = []
        self.raise_context_length_once = False

    # -- helper -----------------------------------------------------------
    def _is_summary_request(self, messages: list[dict[str, Any]]) -> bool:
        head = (messages[0].get("content") or "") if messages else ""
        return "compressore di contesto" in head

    async def chat(self, messages: list[dict[str, Any]], **kw: Any) -> dict[str, Any]:
        self.calls.append({"messages": messages, "kw": kw})
        if self._is_summary_request(messages):
            self.summary_calls += 1
            if self.fail_summaries:
                raise LLMError("backend giu'", kind="server", retryable=True)
            text = "" if self.empty_summaries else (
                "- L'utente sta discutendo di test automatici.\n"
                "- Punti chiave conservati: identificativi, decisioni, questioni aperte.\n"
                f"- Sintesi numero {self.summary_calls}."
            )
            return {"choices": [{"message": {"role": "assistant", "content": text}}],
                    "usage": {"total_tokens": 100}}

        if self.raise_context_length_once:
            from app.llm import ContextLengthError

            self.raise_context_length_once = False
            raise ContextLengthError("This model's maximum context length is 32768 tokens", 400)

        message: dict[str, Any] = {"role": "assistant", "content": self.reply}
        if self.next_tool_calls:
            message["tool_calls"] = self.next_tool_calls.pop(0)
            message["content"] = ""
        return {"choices": [{"message": message}], "usage": {"total_tokens": 42}}

    async def chat_text(self, messages: list[dict[str, Any]], **kw: Any) -> str:
        data = await self.chat(messages, **kw)
        return (data["choices"][0]["message"].get("content") or "").strip()

    async def stream_chat(self, messages: list[dict[str, Any]], **kw: Any) -> AsyncIterator[dict[str, Any]]:
        self.calls.append({"messages": messages, "kw": kw, "stream": True})
        for word in self.reply.split(" "):
            yield {"choices": [{"delta": {"content": word + " "}}]}

    async def health(self) -> dict[str, Any]:
        return {"reachable": True, "status": 200, "models": ["fake"], "circuit_open": False}

    async def aclose(self) -> None:
        return None


@pytest.fixture(autouse=True)
def _env(monkeypatch, tmp_path):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "test.db"))
    monkeypatch.setenv("CONTEXT_WINDOW", "4000")
    monkeypatch.setenv("MAX_OUTPUT_TOKENS", "500")
    monkeypatch.setenv("KEEP_RECENT_MESSAGES", "4")
    monkeypatch.setenv("MIN_MESSAGES_TO_COMPACT", "2")
    monkeypatch.setenv("MAX_SUMMARY_INPUT_TOKENS", "1200")
    monkeypatch.setenv("SUMMARY_MAX_TOKENS", "200")
    config.reset_settings_cache()
    db_module.set_db(None)
    yield
    db_module.set_db(None)
    config.reset_settings_cache()


@pytest.fixture
def db(tmp_path):
    database = db_module.Database(str(tmp_path / "chat.db"))
    db_module.set_db(database)
    yield database
    database.close()


@pytest.fixture
def llm():
    return FakeLLM()


def long_text(marker: str, words: int = 120) -> str:
    """Testo abbastanza lungo da far crescere il contesto in fretta."""
    return f"[{marker}] " + " ".join(f"parola{i}" for i in range(words))
