"""Client per server LLM OpenAI-compatible (vLLM, llama.cpp, TGI, Ollama).

Contro i bug segnalati:
- timeout espliciti su connect/read: senza, una richiesta appesa blocca il
  worker e la chat "si pianta" finche' non riavvii FastAPI;
- retry con backoff SOLO sugli errori transitori (rete, 5xx, 429). Un 400
  "context length exceeded" NON si ritenta: si propaga come errore
  strutturato, cosi' il livello sopra sa che deve compattare;
- circuit breaker: se il backend e' giu', si smette di martellarlo e si
  risponde subito con un errore chiaro invece di accumulare richieste;
- parsing SSE tollerante ai frame spezzati.
"""
from __future__ import annotations

import asyncio
import json
import logging
import random
import time
from typing import Any, AsyncIterator

import httpx

from app.config import Settings, get_settings

log = logging.getLogger("app.llm")


class LLMError(RuntimeError):
    """Errore del backend LLM con classificazione utile al chiamante."""

    def __init__(self, message: str, *, status: int | None = None, kind: str = "unknown", retryable: bool = False):
        super().__init__(message)
        self.status = status
        self.kind = kind          # context_length | rate_limit | server | network | bad_request | unknown
        self.retryable = retryable


class ContextLengthError(LLMError):
    def __init__(self, message: str, status: int | None = None):
        super().__init__(message, status=status, kind="context_length", retryable=False)


class CircuitBreaker:
    """Apre dopo N fallimenti consecutivi, richiude dopo un cooldown."""

    def __init__(self, threshold: int = 5, cooldown_s: float = 20.0):
        self.threshold = threshold
        self.cooldown_s = cooldown_s
        self.failures = 0
        self.opened_at: float | None = None

    @property
    def is_open(self) -> bool:
        if self.opened_at is None:
            return False
        if time.monotonic() - self.opened_at >= self.cooldown_s:
            # half-open: si concede un tentativo
            self.opened_at = None
            self.failures = self.threshold - 1
            return False
        return True

    def record_success(self) -> None:
        self.failures = 0
        self.opened_at = None

    def record_failure(self) -> None:
        self.failures += 1
        if self.failures >= self.threshold and self.opened_at is None:
            self.opened_at = time.monotonic()
            log.warning("circuit breaker APERTO dopo %d fallimenti consecutivi", self.failures)


_CONTEXT_MARKERS = (
    "context length", "context_length", "maximum context", "too many tokens",
    "reduce the length", "prompt is too long", "exceeds the maximum",
    "input is too long", "max_model_len", "longer than the maximum",
)


def _classify(status: int, body: str) -> LLMError:
    low = (body or "").lower()
    if status == 400 and any(m in low for m in _CONTEXT_MARKERS):
        return ContextLengthError(f"contesto troppo lungo per il modello: {body[:400]}", status)
    if status == 429:
        return LLMError("rate limit dal backend LLM", status=status, kind="rate_limit", retryable=True)
    if status >= 500:
        return LLMError(f"errore server LLM {status}: {body[:400]}", status=status, kind="server", retryable=True)
    return LLMError(f"richiesta rifiutata dal backend LLM {status}: {body[:400]}",
                    status=status, kind="bad_request", retryable=False)


class LLMClient:
    def __init__(self, settings: Settings | None = None, transport: httpx.AsyncBaseTransport | None = None):
        self.s = settings or get_settings()
        self.breaker = CircuitBreaker()
        timeout = httpx.Timeout(
            self.s.request_timeout_s, connect=self.s.connect_timeout_s,
            read=self.s.request_timeout_s, write=30.0, pool=10.0,
        )
        headers = {"Content-Type": "application/json"}
        if self.s.llm_api_key and self.s.llm_api_key != "EMPTY":
            headers["Authorization"] = f"Bearer {self.s.llm_api_key}"
        self._client = httpx.AsyncClient(
            base_url=self.s.llm_base_url, timeout=timeout, headers=headers, transport=transport,
            limits=httpx.Limits(max_connections=32, max_keepalive_connections=16),
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    # ------------------------------------------------------------------ utils
    def _payload(self, messages: list[dict[str, Any]], **over: Any) -> dict[str, Any]:
        body: dict[str, Any] = {
            "model": over.pop("model", None) or self.s.llm_model,
            "messages": messages,
            "max_tokens": over.pop("max_tokens", None) or self.s.max_output_tokens,
            "temperature": over.pop("temperature", 0.7),
        }
        body.update({k: v for k, v in over.items() if v is not None})
        return body

    async def _post_with_retry(self, url: str, payload: dict[str, Any]) -> httpx.Response:
        if self.breaker.is_open:
            raise LLMError("backend LLM non raggiungibile (circuit breaker aperto), riprova tra qualche secondo",
                           kind="network", retryable=True)
        last: LLMError | None = None
        for attempt in range(1, self.s.max_retries + 1):
            try:
                resp = await self._client.post(url, json=payload)
                if resp.status_code < 400:
                    self.breaker.record_success()
                    return resp
                err = _classify(resp.status_code, resp.text)
                if not err.retryable:
                    # Un 400 non e' colpa della rete: non deve aprire il breaker.
                    raise err
                last = err
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                last = LLMError(f"errore di rete verso il backend LLM: {exc!r}", kind="network", retryable=True)
            except LLMError:
                raise
            self.breaker.record_failure()
            if attempt < self.s.max_retries:
                delay = min(2 ** (attempt - 1), 8) + random.uniform(0, 0.4)
                log.warning("tentativo %d/%d fallito (%s), ritento tra %.1fs",
                            attempt, self.s.max_retries, last, delay)
                await asyncio.sleep(delay)
        assert last is not None
        raise last

    # ------------------------------------------------------------- completions
    async def chat(self, messages: list[dict[str, Any]], **over: Any) -> dict[str, Any]:
        payload = self._payload(messages, **over)
        payload["stream"] = False
        resp = await self._post_with_retry("/chat/completions", payload)
        try:
            data = resp.json()
        except ValueError as exc:
            raise LLMError(f"risposta non JSON dal backend LLM: {exc}", kind="server") from exc
        if "choices" not in data or not data["choices"]:
            raise LLMError(f"risposta senza 'choices': {json.dumps(data)[:300]}", kind="server")
        return data

    async def chat_text(self, messages: list[dict[str, Any]], **over: Any) -> str:
        data = await self.chat(messages, **over)
        return (data["choices"][0].get("message", {}).get("content") or "").strip()

    async def stream_chat(self, messages: list[dict[str, Any]], **over: Any) -> AsyncIterator[dict[str, Any]]:
        """Genera i delta SSE. Rilancia LLMError classificato in caso di errore."""
        if self.breaker.is_open:
            raise LLMError("backend LLM non raggiungibile (circuit breaker aperto)", kind="network", retryable=True)
        payload = self._payload(messages, **over)
        payload["stream"] = True
        try:
            async with self._client.stream("POST", "/chat/completions", json=payload) as resp:
                if resp.status_code >= 400:
                    body = (await resp.aread()).decode("utf-8", "replace")
                    err = _classify(resp.status_code, body)
                    if err.retryable:
                        self.breaker.record_failure()
                    raise err
                self.breaker.record_success()
                async for line in resp.aiter_lines():
                    if not line or not line.startswith("data:"):
                        continue
                    chunk = line[5:].strip()
                    if chunk == "[DONE]":
                        return
                    try:
                        yield json.loads(chunk)
                    except ValueError:
                        log.debug("frame SSE non parsabile, ignorato: %r", chunk[:120])
                        continue
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            self.breaker.record_failure()
            raise LLMError(f"streaming interrotto: {exc!r}", kind="network", retryable=True) from exc

    async def health(self) -> dict[str, Any]:
        try:
            resp = await self._client.get("/models", timeout=httpx.Timeout(10.0, connect=5.0))
            ok = resp.status_code < 400
            models: list[str] = []
            if ok:
                try:
                    models = [m.get("id") for m in resp.json().get("data", [])]
                except ValueError:
                    pass
            return {"reachable": ok, "status": resp.status_code, "models": models,
                    "circuit_open": self.breaker.is_open}
        except Exception as exc:  # noqa: BLE001 - la health non deve mai sollevare
            return {"reachable": False, "error": repr(exc), "circuit_open": self.breaker.is_open}


_client: LLMClient | None = None


def get_llm() -> LLMClient:
    global _client
    if _client is None:
        _client = LLMClient()
    return _client


def set_llm(client: LLMClient | None) -> None:
    global _client
    _client = client
