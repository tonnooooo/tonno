"""Configurazione centralizzata, letta da variabili d'ambiente.

Regola: nessun valore magico sparso nel codice. Tutto passa da qui, cosi'
un tuning sulla VM si fa con un .env e un restart, senza toccare i sorgenti.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field


def _str(name: str, default: str) -> str:
    v = os.getenv(name)
    return default if v is None or v.strip() == "" else v.strip()


def _int(name: str, default: int) -> int:
    try:
        return int(_str(name, str(default)))
    except ValueError:
        return default


def _float(name: str, default: float) -> float:
    try:
        return float(_str(name, str(default)))
    except ValueError:
        return default


@dataclass(frozen=True)
class Settings:
    # --- backend LLM ---
    llm_base_url: str = field(default_factory=lambda: _str("LLM_BASE_URL", "http://127.0.0.1:8000/v1").rstrip("/"))
    llm_api_key: str = field(default_factory=lambda: _str("LLM_API_KEY", "EMPTY"))
    llm_model: str = field(default_factory=lambda: _str("LLM_MODEL", "local-model"))

    # --- budget di contesto ---
    context_window: int = field(default_factory=lambda: _int("CONTEXT_WINDOW", 32768))
    max_output_tokens: int = field(default_factory=lambda: _int("MAX_OUTPUT_TOKENS", 1024))

    # --- compattazione ---
    compaction_trigger_ratio: float = field(default_factory=lambda: _float("COMPACTION_TRIGGER_RATIO", 0.75))
    compaction_target_ratio: float = field(default_factory=lambda: _float("COMPACTION_TARGET_RATIO", 0.45))
    keep_recent_messages: int = field(default_factory=lambda: _int("KEEP_RECENT_MESSAGES", 6))
    min_messages_to_compact: int = field(default_factory=lambda: _int("MIN_MESSAGES_TO_COMPACT", 4))
    max_summary_input_tokens: int = field(default_factory=lambda: _int("MAX_SUMMARY_INPUT_TOKENS", 6000))
    summary_max_tokens: int = field(default_factory=lambda: _int("SUMMARY_MAX_TOKENS", 700))

    # --- rete ---
    request_timeout_s: float = field(default_factory=lambda: _float("REQUEST_TIMEOUT_S", 180.0))
    connect_timeout_s: float = field(default_factory=lambda: _float("CONNECT_TIMEOUT_S", 10.0))
    max_retries: int = field(default_factory=lambda: _int("MAX_RETRIES", 3))

    # --- persistenza ---
    db_path: str = field(default_factory=lambda: _str("DB_PATH", "./data/chat.db"))

    # --- agenti / tool ---
    tool_output_max_chars: int = field(default_factory=lambda: _int("TOOL_OUTPUT_MAX_CHARS", 6000))
    max_tool_iterations: int = field(default_factory=lambda: _int("MAX_TOOL_ITERATIONS", 6))
    tool_timeout_s: float = field(default_factory=lambda: _float("TOOL_TIMEOUT_S", 30.0))
    searxng_url: str = field(default_factory=lambda: _str("SEARXNG_URL", ""))

    # --- varie ---
    log_level: str = field(default_factory=lambda: _str("LOG_LEVEL", "INFO"))

    def validate(self) -> list[str]:
        """Ritorna la lista dei problemi di configurazione (vuota = tutto ok).

        Serve a beccare all'avvio le combinazioni che in produzione si
        manifestano molto piu' tardi come "la chat ogni tanto si rompe".
        """
        problems: list[str] = []
        if self.context_window < 2048:
            problems.append(f"CONTEXT_WINDOW={self.context_window} troppo basso (minimo 2048)")
        if self.max_output_tokens >= self.context_window:
            problems.append("MAX_OUTPUT_TOKENS deve essere < CONTEXT_WINDOW")
        if not 0.3 <= self.compaction_trigger_ratio <= 0.95:
            problems.append("COMPACTION_TRIGGER_RATIO fuori dall'intervallo sensato 0.30-0.95")
        if self.compaction_target_ratio >= self.compaction_trigger_ratio:
            problems.append("COMPACTION_TARGET_RATIO deve essere < COMPACTION_TRIGGER_RATIO, altrimenti si compatta a ciclo continuo")
        if self.keep_recent_messages < 2:
            problems.append("KEEP_RECENT_MESSAGES < 2: l'ultimo turno verrebbe compattato, la chat perde il filo")
        if self.max_summary_input_tokens + self.summary_max_tokens >= self.context_window:
            problems.append("MAX_SUMMARY_INPUT_TOKENS + SUMMARY_MAX_TOKENS supera la finestra: la compattazione fallirebbe sempre")
        return problems


_settings: Settings | None = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings


def reset_settings_cache() -> None:
    """Usato dai test per rileggere l'ambiente."""
    global _settings
    _settings = None
