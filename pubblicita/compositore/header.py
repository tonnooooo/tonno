"""Intestazione: marchio procedurale + titolo, con animazione d'apertura da config.

Animazione (``header.animation``)::

    "mark":  {"start_s": 0.0, "duration_s": 0.3, "easing": "easeOutCubic",
              "from": {"opacity": 0, "scale": 0.7, "rotate_deg": -12, "dx": 0, "dy": 0, "blur": 4},
              "timing": {"opacity": {"start_s": 0.0, "duration_s": 0.25, "easing": "linear"}}}
    "title": {"start_s": 0.35, "stagger_s": 0.25, "duration_s": 0.4, "easing": "...",
              "from": {"opacity": 0, "dy": 14, "blur": 3}}

    "shimmer": {"start_s": 1.81, "duration_s": 0.16, "color": [138, 186, 173], "half_width": 190}

Ogni proprietà va da ``from`` al valore di riposo (opacità 1, scala 1, il resto 0).
Lo «shimmer» è un riflesso colorato (profilo triangolare largo 2 × half_width px) che
attraversa il titolo da sinistra a destra una volta sola.
Il titolo è animato parola per parola, ognuna ``stagger_s`` dopo la precedente.
``easing`` è un nome o una curva ``[x1, y1, x2, y2]`` come in CSS ``cubic-bezier``.
"""
from __future__ import annotations

import math

import numpy as np

from . import grafica

REST = {"opacity": 1.0, "scale": 1.0, "rotate_deg": 0.0, "dx": 0.0, "dy": 0.0, "blur": 0.0}

EASINGS = {
    "linear": None,
    "ease": (0.25, 0.1, 0.25, 1.0),
    "ease-in": (0.42, 0.0, 1.0, 1.0),
    "ease-out": (0.0, 0.0, 0.58, 1.0),
    "ease-in-out": (0.42, 0.0, 0.58, 1.0),
    "easeOutCubic": (0.33, 1.0, 0.68, 1.0),
    "easeOutQuart": (0.25, 1.0, 0.5, 1.0),
    "easeOutExpo": (0.16, 1.0, 0.3, 1.0),
    "easeInOutCubic": (0.65, 0.0, 0.35, 1.0),
    "easeOutBack": (0.34, 1.56, 0.64, 1.0),
}


def cubic_bezier(x1: float, y1: float, x2: float, y2: float, x: float) -> float:
    """Valore y della curva di Bézier CSS per il tempo normalizzato x ∈ [0, 1]."""
    if x <= 0:
        return 0.0
    if x >= 1:
        return 1.0

    def bx(s):
        return 3 * (1 - s) ** 2 * s * x1 + 3 * (1 - s) * s * s * x2 + s ** 3

    def by(s):
        return 3 * (1 - s) ** 2 * s * y1 + 3 * (1 - s) * s * s * y2 + s ** 3

    lo, hi = 0.0, 1.0
    for _ in range(40):  # bisezione: x(s) è monotona per x1, x2 in [0, 1]
        mid = (lo + hi) / 2
        if bx(mid) < x:
            lo = mid
        else:
            hi = mid
    return by((lo + hi) / 2)


def ease(name, p: float) -> float:
    p = min(max(p, 0.0), 1.0)
    if isinstance(name, (list, tuple)):
        return cubic_bezier(*name, p)
    if name not in EASINGS:
        raise ValueError(f"easing sconosciuto: {name!r} (disponibili: {', '.join(EASINGS)})")
    curve = EASINGS[name]
    return p if curve is None else cubic_bezier(*curve, p)


def tween_state(anim: dict | None, t: float, delay: float = 0.0) -> dict:
    """Stato delle proprietà al tempo t (secondi) per un'animazione «from → riposo»."""
    state = dict(REST)
    if not anim:
        return state
    base_start = anim.get("start_s", 0.0) + delay
    base_dur = anim.get("duration_s", 0.5)
    base_ease = anim.get("easing", "easeOutCubic")
    timing = anim.get("timing", {})
    for prop, v0 in anim.get("from", {}).items():
        tm = timing.get(prop, {})
        start = tm.get("start_s", base_start - delay) + delay
        dur = max(tm.get("duration_s", base_dur), 1e-6)
        e = ease(tm.get("easing", base_ease), (t - start) / dur)
        v1 = anim.get("to", {}).get(prop, REST[prop])
        state[prop] = v0 + (v1 - v0) * e
    return state


def _is_rest(st: dict) -> bool:
    return all(abs(st[k] - REST[k]) < 1e-4 for k in REST)


class Header:
    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.anim = cfg.get("animation", {})
        m = cfg.get("mark")
        self.mark = m
        if m:
            self.mcx = m["center_x"]
            self.mcy = m["top"] + m.get("height", m["size"]) / 2
            self.mbox = int(math.ceil(m["size"] * 1.6)) + 8
            self.mark_static = grafica.mark_layer(m, self.mcx, self.mcy, self.mbox)
        ti = cfg.get("title")
        self.title = ti
        self.words = []
        if ti and ti.get("text"):
            font = grafica.load_font(ti["font"], ti["size"] * 4)
            pos, total = grafica.text_advances(font, ti["text"], ti.get("tracking", 0.0) * 4)
            ws = ti.get("word_spacing", 0.0)
            text = ti["text"]
            width = total / 4 + ws * text.count(" ")
            x0 = ti["center_x"] - width / 2
            self.title_span = (x0, x0 + width)
            i, k = 0, 0
            for word in text.split(" "):
                if word:
                    xw = x0 + pos[i] / 4 + ws * k
                    self.words.append({"text": word, "x": xw,
                                       "static": self._word_layer(word, xw, 0.0)})
                    k += 1
                i += len(word) + 1

    def _word_layer(self, word: str, x: float, dy: float, pad: int = 8):
        ti = self.title
        return grafica.text_layer(word, ti["font"], ti["size"], ti["color"], ti.get("tracking", 0.0),
                                  x, ti["baseline"] + dy, pad=pad)

    def draw(self, frame: np.ndarray, t: float) -> None:
        if self.mark:
            st = tween_state(self.anim.get("mark"), t)
            if _is_rest(st):
                layer, x0, y0 = self.mark_static
                grafica.over(frame, layer, x0, y0)
            elif st["opacity"] > 1e-3 and st["scale"] > 1e-3:
                layer, x0, y0 = grafica.mark_layer(self.mark, self.mcx + st["dx"], self.mcy + st["dy"],
                                                   self.mbox, st["scale"], st["rotate_deg"], ss=3)
                layer = grafica.blur_layer(layer, st["blur"]) * st["opacity"]
                grafica.over(frame, layer, x0, y0)
        ta = self.anim.get("title")
        stagger = (ta or {}).get("stagger_s", 0.0)
        shim = self._shimmer(t)
        for i, w in enumerate(self.words):
            st = tween_state(ta, t, delay=i * stagger)
            if _is_rest(st):
                layer, x0, y0, _ = w["static"]
            elif st["opacity"] > 1e-3:
                layer, x0, y0, _ = self._word_layer(w["text"], w["x"] + st["dx"], st["dy"],
                                                    pad=8 + int(math.ceil(3 * st["blur"])))
            else:
                continue
            if shim is not None:
                layer = self._recolor(layer, x0, shim)
            if not _is_rest(st):
                layer = grafica.blur_layer(layer, st["blur"]) * st["opacity"]
            grafica.over(frame, layer, x0, y0)

    def _shimmer(self, t: float):
        """(centro_x, mezza_larghezza, colore) del riflesso al tempo t, oppure None."""
        sh = self.anim.get("shimmer")
        if not sh or not self.words:
            return None
        p = (t - sh["start_s"]) / max(sh["duration_s"], 1e-6)
        if p < 0 or p > 1:
            return None
        hw = float(sh["half_width"])
        xa, xb = self.title_span
        return (xa - hw + p * (xb - xa + 2 * hw), hw, np.asarray(sh["color"], np.float32))

    def _recolor(self, layer: np.ndarray, x0: int, shim) -> np.ndarray:
        cx, hw, col = shim
        xs = x0 + np.arange(layer.shape[1], dtype=np.float32) + 0.5
        k = np.clip(1.0 - np.abs(xs - cx) / hw, 0.0, 1.0)[None, :, None]
        base = np.asarray(self.title["color"], np.float32)
        out = layer.copy()
        out[..., :3] = layer[..., 3:4] * (base * (1 - k) + col * k)
        return out
