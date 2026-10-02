"""Sfondo: colore di base con leggera tinta a gradiente e linee ondulate animate.

Le linee sono descritte nel config (``background.waves``): ogni linea è una spline
Catmull-Rom uniforme con punti di controllo a ``origin_x + i * spacing``; l'ordinata di
ogni punto oscilla nel tempo con una frequenza propria della linea e la sua seconda
armonica::

    y_i(t) = rest_i + s1_i sin(wt) + c1_i cos(wt) + s2_i sin(2wt) + c2_i cos(2wt),  w = 2π/period

Il motivo si ripete in verticale ogni ``tile_height`` px (``copy`` = indice della
ripetizione). Tutto è deterministico: il frame n dipende solo da t = n / fps.
"""
from __future__ import annotations

import math

import numpy as np


# ---------------------------------------------------------------- tinta

def _bspline_basis(t: np.ndarray, n: int) -> np.ndarray:
    """Basi B-spline cubiche uniformi «clamped» con n punti di controllo su t ∈ [0, 1]."""
    k = 3
    knots = np.concatenate([np.zeros(k), np.linspace(0, 1, n - k + 1), np.ones(k)])
    t = np.clip(t, 0, 1)

    def B(i, kk):
        if kk == 0:
            last = knots[i + 1] == 1.0
            return ((knots[i] <= t) & ((t < knots[i + 1]) | (last & (t == 1.0)))).astype(float)
        out = 0.0
        if knots[i + kk] > knots[i]:
            out = out + (t - knots[i]) / (knots[i + kk] - knots[i]) * B(i, kk - 1)
        if knots[i + kk + 1] > knots[i + 1]:
            out = out + (knots[i + kk + 1] - t) / (knots[i + kk + 1] - knots[i + 1]) * B(i + 1, kk - 1)
        return out

    return np.stack([B(i, k) for i in range(n)], 1)


def base_image(cfg: dict, width: int, height: int) -> np.ndarray:
    """Colore di base (H, W, 3) float32: tinta uniforme o griglia B-spline di colori."""
    tint = cfg.get("tint")
    if not tint:
        return np.broadcast_to(np.asarray(cfg["color"], np.float32), (height, width, 3)).copy()
    nx, ny = int(tint["nx"]), int(tint["ny"])
    grid = np.asarray(tint["rgb"], np.float32).reshape(ny, nx, 3)
    bx = _bspline_basis(np.arange(width) / (width - 1), nx).astype(np.float32)
    by = _bspline_basis(np.arange(height) / (height - 1), ny).astype(np.float32)
    out = np.empty((height, width, 3), np.float32)
    for c in range(3):
        out[..., c] = (by @ grid[:, :, c]) @ bx.T
    return out


# ---------------------------------------------------------------- linee

def catmull_rom_basis(x: np.ndarray, spacing: float, origin: float, npts: int) -> np.ndarray:
    """Matrice (len(x), npts): y(x) = M @ punti, punti a origin + i * spacing."""
    u = (np.asarray(x, float) - origin) / spacing
    i = np.floor(u).astype(int)
    s = u - i
    s2, s3 = s * s, s * s * s
    w = np.stack([(-s3 + 2 * s2 - s) / 2, (3 * s3 - 5 * s2 + 2) / 2,
                  (-3 * s3 + 4 * s2 + s) / 2, (s3 - s2) / 2], 1)
    M = np.zeros((len(u), npts))
    rows = np.arange(len(u))
    for k in range(4):
        np.add.at(M, (rows, np.clip(i - 1 + k, 0, npts - 1)), w[:, k])
    return M


class Waves:
    """Linee ondulate: precalcola le basi e disegna un frame alla volta."""

    COMPONENTS = ("rest", "sin1", "cos1", "sin2", "cos2")

    def __init__(self, cfg: dict, width: int, height: int):
        self.cfg = cfg
        self.width, self.height = width, height
        self.tile = float(cfg.get("tile_height", 640))
        self.speed = float(cfg.get("speed", 1.0))
        self.t0 = float(cfg.get("time_offset_s", 0.0))
        self.styles = cfg["styles"]
        lines = cfg["lines"]
        npts = len(lines[0]["rest"]) if lines else 0
        # colonne e righe in coordinate «indice di pixel» (centro del pixel = intero)
        self.M = catmull_rom_basis(np.arange(width, dtype=np.float64), cfg["spacing"], cfg["origin_x"], npts)
        self.lines = []
        for ln in lines:
            P = np.stack([np.asarray(ln[c], float) for c in self.COMPONENTS])  # (5, npts)
            st = self.styles[ln["style"]]
            self.lines.append({
                "P": P, "w": 2 * math.pi / float(ln["period_s"]),
                "dy": float(ln.get("copy", 0)) * self.tile + float(ln.get("dy", 0.0)),
                "color": np.asarray(st["color"], np.float32),
                "alpha": float(st.get("opacity", 1.0)), "width": float(st["width"]),
                "order": int(st.get("order", 0)),
            })
        self.lines.sort(key=lambda d: d["order"])

    def curves(self, t: float) -> list[np.ndarray]:
        """Ordinata (indice di riga, centro del pixel = intero) di ogni linea per ogni colonna."""
        tt = (t + self.t0) * self.speed
        out = []
        for ln in self.lines:
            w = ln["w"]
            ph = np.array([1.0, math.sin(w * tt), math.cos(w * tt), math.sin(2 * w * tt), math.cos(2 * w * tt)])
            out.append(self.M @ (ph @ ln["P"]) + ln["dy"])
        return out

    def draw(self, frame: np.ndarray, t: float, shade: np.ndarray | None = None) -> None:
        """Disegna le linee su ``frame`` (uint8, H×W×3) già contenente lo sfondo ombreggiato.

        ``shade`` (H×W float32) è il fattore d'ombra 1 - alfa_ombra: la linea va sotto
        l'ombra dei pannelli come il resto dello sfondo.
        """
        H, W = self.height, self.width
        cols = np.arange(W)
        for ln, y in zip(self.lines, self.curves(t)):
            half = ln["width"] / 2
            slope = np.gradient(y)
            cosv = 1.0 / np.sqrt(1.0 + slope * slope)
            K = int(math.ceil(half / cosv.min() + 2)) * 2 + 1
            r0 = np.floor(y).astype(int) - K // 2
            rows = r0[None, :] + np.arange(K)[:, None]            # (K, W)
            dist = np.abs(rows - y[None, :]) * cosv[None, :]       # distanza perpendicolare
            cov = np.clip(half + 0.5 - dist, 0.0, 1.0) * ln["alpha"]
            ok = (rows >= 0) & (rows < H) & (cov > 0)
            if not ok.any():
                continue
            rr, cc = rows[ok], np.broadcast_to(cols, rows.shape)[ok]
            a = cov[ok][:, None].astype(np.float32)
            px = frame[rr, cc].astype(np.float32)
            col = ln["color"][None, :]
            if shade is not None:
                col = col * shade[rr, cc][:, None]
            frame[rr, cc] = np.clip(px * (1 - a) + col * a + 0.5, 0, 255).astype(np.uint8)
