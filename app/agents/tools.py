"""Strumenti per gli agenti di ricerca / OSINT.

Il problema degli agenti in una chat con contesto limitato non e' la qualita'
dello strumento: e' che l'output finisce nel contesto. Una singola pagina web
puo' valere 50k token e da sola manda in crisi la finestra: da li' partono i
"dopo un po' la chat si rompe". Quindi ogni tool qui:

- ha un timeout proprio,
- ha un tetto sui byte scaricati (non si legge una risposta infinita),
- restituisce un output TRONCATO a TOOL_OUTPUT_MAX_CHARS,
- non solleva mai: gli errori tornano come testo, cosi' il modello puo'
  reagire invece di far fallire l'intera richiesta.
"""
from __future__ import annotations

import asyncio
import html
import json
import logging
import re
from typing import Any, Awaitable, Callable

import httpx

from app.config import get_settings

log = logging.getLogger("app.agents.tools")

ToolFn = Callable[..., Awaitable[str]]
TOOL_REGISTRY: dict[str, dict[str, Any]] = {}

_MAX_DOWNLOAD_BYTES = 2_000_000  # 2 MB: oltre non serve, e' solo rischio


def tool(name: str, description: str, parameters: dict[str, Any]) -> Callable[[ToolFn], ToolFn]:
    def deco(fn: ToolFn) -> ToolFn:
        TOOL_REGISTRY[name] = {
            "fn": fn,
            "spec": {
                "type": "function",
                "function": {"name": name, "description": description, "parameters": parameters},
            },
        }
        return fn

    return deco


def tool_specs(names: list[str] | None = None) -> list[dict[str, Any]]:
    keys = names if names is not None else list(TOOL_REGISTRY)
    return [TOOL_REGISTRY[k]["spec"] for k in keys if k in TOOL_REGISTRY]


def _truncate(text: str, limit: int | None = None) -> str:
    limit = limit or get_settings().tool_output_max_chars
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n\n[...output troncato: {len(text) - limit} caratteri omessi...]"


def _strip_html(raw: str) -> str:
    raw = re.sub(r"(?is)<(script|style|noscript|svg)[^>]*>.*?</\1>", " ", raw)
    raw = re.sub(r"(?s)<!--.*?-->", " ", raw)
    raw = re.sub(r"(?s)<[^>]+>", " ", raw)
    raw = html.unescape(raw)
    return re.sub(r"[ \t\r\f\v]+", " ", re.sub(r"\n\s*\n+", "\n\n", raw)).strip()


async def _get(url: str, **kw: Any) -> httpx.Response:
    s = get_settings()
    timeout = httpx.Timeout(s.tool_timeout_s, connect=min(10.0, s.tool_timeout_s))
    async with httpx.AsyncClient(
        timeout=timeout, follow_redirects=True, max_redirects=5,
        headers={"User-Agent": "tonno-research/1.0"},
    ) as client:
        async with client.stream("GET", url, **kw) as resp:
            resp.raise_for_status()
            chunks: list[bytes] = []
            total = 0
            async for chunk in resp.aiter_bytes():
                chunks.append(chunk)
                total += len(chunk)
                if total >= _MAX_DOWNLOAD_BYTES:  # tetto rigido sullo scarico
                    break
            resp._content = b"".join(chunks)  # noqa: SLF001
            return resp


@tool(
    "web_search",
    "Cerca sul web tramite l'istanza SearXNG configurata. Restituisce titolo, URL e sintesi dei primi risultati.",
    {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "La query di ricerca"},
            "max_results": {"type": "integer", "description": "Numero massimo di risultati (default 6)"},
        },
        "required": ["query"],
    },
)
async def web_search(query: str, max_results: int = 6) -> str:
    s = get_settings()
    if not s.searxng_url:
        return ("ERRORE: ricerca web non configurata. Imposta SEARXNG_URL nel file .env "
                "con l'indirizzo della tua istanza SearXNG (es. http://127.0.0.1:8080).")
    max_results = max(1, min(int(max_results or 6), 10))
    try:
        resp = await _get(
            s.searxng_url.rstrip("/") + "/search",
            params={"q": query, "format": "json", "safesearch": 0},
        )
        data = resp.json()
    except Exception as exc:  # noqa: BLE001 - il tool non deve mai far cadere il turno
        log.warning("web_search fallita: %r", exc)
        return f"ERRORE nella ricerca web: {exc!r}"

    results = (data.get("results") or [])[:max_results]
    if not results:
        return f"Nessun risultato per: {query}"
    out = [f"Risultati per «{query}»:"]
    for i, r in enumerate(results, 1):
        out.append(
            f"{i}. {r.get('title', 'senza titolo')}\n   URL: {r.get('url', '')}\n"
            f"   {(r.get('content') or '').strip()[:400]}"
        )
    return _truncate("\n".join(out))


@tool(
    "fetch_url",
    "Scarica una pagina web e ne restituisce il testo ripulito dall'HTML. Usalo per approfondire un risultato di ricerca.",
    {
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "URL completo da scaricare (http/https)"},
        },
        "required": ["url"],
    },
)
async def fetch_url(url: str) -> str:
    if not re.match(r"^https?://", url or "", re.I):
        return "ERRORE: sono ammessi solo URL http:// o https://"
    try:
        resp = await _get(url)
    except Exception as exc:  # noqa: BLE001
        log.warning("fetch_url fallita su %s: %r", url, exc)
        return f"ERRORE nello scaricamento di {url}: {exc!r}"
    ctype = resp.headers.get("content-type", "")
    body = resp.content.decode(resp.encoding or "utf-8", "replace")
    if "json" in ctype:
        try:
            body = json.dumps(json.loads(body), ensure_ascii=False, indent=2)
        except ValueError:
            pass
    elif "html" in ctype or body.lstrip().startswith("<"):
        body = _strip_html(body)
    return _truncate(f"Contenuto di {url} ({ctype or 'sconosciuto'}):\n\n{body}")


async def run_tool(name: str, arguments: dict[str, Any]) -> str:
    """Esegue un tool con timeout. Non solleva: qualunque problema torna come testo."""
    entry = TOOL_REGISTRY.get(name)
    if entry is None:
        return f"ERRORE: strumento sconosciuto «{name}». Disponibili: {', '.join(TOOL_REGISTRY)}"
    s = get_settings()
    try:
        return await asyncio.wait_for(entry["fn"](**(arguments or {})), timeout=s.tool_timeout_s + 5)
    except asyncio.TimeoutError:
        return f"ERRORE: lo strumento «{name}» ha superato il timeout di {s.tool_timeout_s}s."
    except TypeError as exc:
        return f"ERRORE: argomenti non validi per «{name}»: {exc}"
    except Exception as exc:  # noqa: BLE001
        log.exception("tool %s esploso", name)
        return f"ERRORE nell'esecuzione di «{name}»: {exc!r}"
