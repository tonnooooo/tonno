"""Caricamento del layout: ``pubblicita/config/layout.json`` + eventuale config utente.

Il config utente viene fuso *sopra* quello di default (merge ricorsivo dei dizionari;
liste e valori semplici sostituiscono): basta quindi un JSON con le sole chiavi da
cambiare, per esempio le etichette::

    {"panels": {"bottom": {"label": {"items": [{"icon": "spark"}, {"text": "Seedance 2.5"}]}}}}

I percorsi relativi (font, icone PNG) sono risolti rispetto al file che li contiene.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path

DEFAULT_LAYOUT = Path(__file__).resolve().parents[1] / "config" / "layout.json"


def deep_merge(base: dict, over: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in over.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out


def _resolve_paths(node, base: Path):
    """Rende assoluti i percorsi di font e icone PNG relativi al file di config."""
    if isinstance(node, dict):
        for k, v in node.items():
            if isinstance(v, str) and (k in ("font", "src", "image") or k == "icon") and _looks_like_path(v):
                p = Path(v).expanduser()
                if not p.is_absolute() and (base / p).exists():
                    node[k] = str((base / p).resolve())
            else:
                _resolve_paths(v, base)
    elif isinstance(node, list):
        for v in node:
            _resolve_paths(v, base)


def _looks_like_path(s: str) -> bool:
    return "/" in s or s.lower().endswith((".ttf", ".otf", ".png", ".jpg", ".jpeg", ".webp"))


def load_layout(user_config: str | Path | dict | None = None,
                default: str | Path = DEFAULT_LAYOUT) -> dict:
    dpath = Path(default)
    cfg = json.loads(dpath.read_text(encoding="utf-8"))
    _resolve_paths(cfg, dpath.parent)
    if user_config is None:
        return cfg
    if isinstance(user_config, dict):
        over = copy.deepcopy(user_config)
        _resolve_paths(over, Path.cwd())
    else:
        up = Path(user_config)
        if up.resolve() == dpath.resolve():
            return cfg
        over = json.loads(up.read_text(encoding="utf-8"))
        _resolve_paths(over, up.resolve().parent)
    return deep_merge(cfg, over)
