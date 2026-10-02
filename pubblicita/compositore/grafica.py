"""Primitive grafiche del compositore: maschere, ombre, marchio, testo, icone, pillole.

Convenzioni: coordinate in pixel «a bordo» (il pixel i copre [i, i+1)); i livelli sono
array float32 premoltiplicati ``(H, W, 4)`` con RGB in 0–255 e alfa in 0–1, così che la
composizione sia ``out = out * (1 - a) + rgb``.
"""
from __future__ import annotations

import math
from functools import lru_cache
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

FONT_DIR = Path(__file__).resolve().parent / "fonts"


# ---------------------------------------------------------------- forme di base (SDF)

def _grid(x0: float, y0: float, w: int, h: int, ss: int):
    """Griglia dei centri dei sotto-campioni (ss×ss per pixel) per un riquadro w×h."""
    o = (np.arange(ss) + 0.5) / ss
    xs = (x0 + np.arange(w)[:, None] + o[None, :]).reshape(-1)
    ys = (y0 + np.arange(h)[:, None] + o[None, :]).reshape(-1)
    return np.meshgrid(xs, ys)


def _downsample(cov: np.ndarray, h: int, w: int, ss: int) -> np.ndarray:
    return cov.reshape(h, ss, w, ss).mean(axis=(1, 3)).astype(np.float32)


def _cov(d: np.ndarray, ss: int) -> np.ndarray:
    """Copertura del sotto-campione dalla distanza con segno (rampa larga un sotto-campione)."""
    return np.clip(0.5 - d * ss, 0.0, 1.0).astype(np.float32)


def sdf_round_rect(px, py, x, y, w, h, r):
    cx, cy = x + w / 2, y + h / 2
    qx = np.abs(px - cx) - (w / 2 - r)
    qy = np.abs(py - cy) - (h / 2 - r)
    return np.hypot(np.maximum(qx, 0), np.maximum(qy, 0)) + np.minimum(np.maximum(qx, qy), 0) - r


def round_rect_mask(w: int, h: int, r: float, ss: int = 4, inset: float = 0.0) -> np.ndarray:
    """Copertura antialias (H, W) di un rettangolo arrotondato che riempie il riquadro."""
    px, py = _grid(0, 0, w, h, ss)
    d = sdf_round_rect(px, py, inset, inset, w - 2 * inset, h - 2 * inset, max(r - inset, 0))
    return _downsample(_cov(d, ss), h, w, ss)


def sdf_uneven_capsule(px, py, ax, ay, bx, by, r1, r2):
    """Distanza da un segmento a raggio variabile (I. Quilez), da A (r1) a B (r2)."""
    h = math.hypot(bx - ax, by - ay) + 1e-9
    ux, uy = (bx - ax) / h, (by - ay) / h
    qx, qy = px - ax, py - ay
    ly = qx * ux + qy * uy
    lx = np.abs(-qx * uy + qy * ux)
    b = (r1 - r2) / h
    a = math.sqrt(max(1 - b * b, 1e-9))
    k = -b * lx + a * ly
    d0 = np.hypot(lx, ly) - r1
    d1 = np.hypot(lx, ly - h) - r2
    dm = a * lx + b * ly - r1
    return np.where(k < 0, d0, np.where(k > a * h, d1, dm))


# ---------------------------------------------------------------- ombra

def shadow_alpha(width: int, height: int, boxes: list, radius: float, offset, blur: float,
                 opacity: float, spread: float = 0.0) -> np.ndarray:
    """Alfa dell'ombra portata (stile CSS box-shadow) di più riquadri, su tutta la tela."""
    img = Image.new("L", (width, height), 0)
    d = ImageDraw.Draw(img)
    ox, oy = offset
    for (x, y, w, h) in boxes:
        d.rounded_rectangle((x - spread + ox, y - spread + oy, x + w - 1 + spread + ox,
                             y + h - 1 + spread + oy), radius=radius + spread, fill=255)
    if blur > 0:
        img = img.filter(ImageFilter.GaussianBlur(blur))
    return np.asarray(img, dtype=np.float32) / 255.0 * opacity


# ---------------------------------------------------------------- composizione

def over(dst: np.ndarray, layer: np.ndarray, x: int, y: int) -> None:
    """Compone un livello premoltiplicato (h, w, 4) su ``dst`` (float32 o uint8) in (x, y)."""
    h, w = layer.shape[:2]
    H, W = dst.shape[:2]
    x0, y0, x1, y1 = max(x, 0), max(y, 0), min(x + w, W), min(y + h, H)
    if x1 <= x0 or y1 <= y0:
        return
    sub = layer[y0 - y:y1 - y, x0 - x:x1 - x]
    a = sub[..., 3:4]
    region = dst[y0:y1, x0:x1].astype(np.float32)
    res = region * (1.0 - a) + sub[..., :3]
    if dst.dtype == np.uint8:
        dst[y0:y1, x0:x1] = np.clip(res + 0.5, 0, 255).astype(np.uint8)
    else:
        dst[y0:y1, x0:x1] = res


def premul(rgb, alpha: np.ndarray) -> np.ndarray:
    """Livello premoltiplicato da colore uniforme (o array RGB) e copertura."""
    a = alpha.astype(np.float32)
    if np.ndim(rgb) == 1:
        rgb = np.asarray(rgb, np.float32)[None, None, :]
    out = np.empty(a.shape + (4,), np.float32)
    out[..., :3] = rgb * a[..., None]
    out[..., 3] = a
    return out


def gaussian_blur(arr: np.ndarray, sigma: float) -> np.ndarray:
    """Sfocatura gaussiana separabile (assi 0 e 1) in float32, bordi a zero."""
    if sigma <= 0.05:
        return arr
    r = int(math.ceil(3 * sigma))
    k = np.exp(-0.5 * (np.arange(-r, r + 1) / sigma) ** 2).astype(np.float32)
    k /= k.sum()
    out = arr.astype(np.float32)
    for axis in (0, 1):
        pad = [(0, 0)] * out.ndim
        pad[axis] = (r, r)
        src = np.pad(out, pad)
        acc = np.zeros_like(out)
        n = out.shape[axis]
        for i, w in enumerate(k):
            sl = [slice(None)] * out.ndim
            sl[axis] = slice(i, i + n)
            acc += w * src[tuple(sl)]
        out = acc
    return out


def blur_layer(layer: np.ndarray, sigma: float) -> np.ndarray:
    """Sfocatura gaussiana di un livello premoltiplicato (il margine va previsto dal chiamante)."""
    return gaussian_blur(layer, sigma)


# ---------------------------------------------------------------- marchio

def mark_layer(cfg: dict, cx: float, cy: float, box: int, scale: float = 1.0,
               rotate_deg: float = 0.0, ss: int = 4) -> tuple[np.ndarray, int, int]:
    """Disegna il marchio (quadrato + asterisco) centrato in (cx, cy) con scala/rotazione.

    Restituisce (livello premoltiplicato, x0, y0) su un riquadro ``box``×``box``.
    """
    size = cfg["size"] * scale
    x0 = int(math.floor(cx - box / 2))
    y0 = int(math.floor(cy - box / 2))
    px, py = _grid(x0, y0, box, box, ss)
    # rotazione inversa della griglia attorno al centro del marchio
    t = math.radians(rotate_deg)
    ct, st = math.cos(t), math.sin(t)
    dx, dy = px - cx, py - cy
    lx = ct * dx + st * dy
    ly = -st * dx + ct * dy
    sq = sdf_round_rect(lx, ly, -size / 2, -size / 2, size, size, cfg.get("radius", 0) * scale)
    cov_sq = _cov(sq, ss)
    star = cfg["star"]
    k = size  # le misure dell'asterisco sono frazioni del lato
    scx, scy = star["center"][0] * k, star["center"][1] * k
    d = np.hypot(lx - scx, ly - scy) - star["core_radius"] * k
    rb = star["base_radius"] * k
    for ang, length, tip in star["rays"]:
        a = math.radians(ang)
        L, rt = length * k, tip * k
        bx, by = scx + (L - rt) * math.cos(a), scy + (L - rt) * math.sin(a)
        d = np.minimum(d, sdf_uneven_capsule(lx, ly, scx, scy, bx, by, rb, rt))
    cov_star = _cov(d, ss) * cov_sq
    cs = _downsample(cov_sq, box, box, ss)
    cst = _downsample(cov_star, box, box, ss)
    col_sq = np.asarray(cfg["color"], np.float32)
    col_st = np.asarray(star["color"], np.float32)
    rgb = col_sq[None, None, :] * (cs - cst)[..., None] + col_st[None, None, :] * cst[..., None]
    layer = np.concatenate([rgb, cs[..., None]], axis=-1).astype(np.float32)
    return layer, x0, y0


# ---------------------------------------------------------------- testo

@lru_cache(maxsize=32)
def load_font(path: str, size_px: float) -> ImageFont.FreeTypeFont:
    p = Path(path)
    if not p.is_absolute() and not p.exists():
        p = FONT_DIR / p.name if (FONT_DIR / p.name).exists() else Path(__file__).resolve().parent / p
    return ImageFont.truetype(str(p), size_px)


def text_advances(font: ImageFont.FreeTypeFont, text: str, tracking: float) -> tuple[list[float], float]:
    """Posizioni orizzontali dei glifi (kerning incluso) con ``tracking`` px tra lettere."""
    pos, x = [], 0.0
    for i, ch in enumerate(text):
        pos.append(x)
        if i + 1 < len(text):
            adv = font.getlength(text[i:i + 2]) - font.getlength(text[i + 1])
        else:
            adv = font.getlength(ch)
        x += adv + tracking
    return pos, x - tracking  # nessun tracking dopo l'ultima lettera


def text_layer(text: str, font_path: str, size: float, color, tracking: float = 0.0,
               x: float = 0.0, baseline: float = 0.0, ss: int = 4, pad: int = 4,
               opacity: float = 1.0):
    """Rasterizza ``text`` con origine (x, baseline) in coordinate tela.

    Restituisce (livello premoltiplicato, x0, y0, larghezza_avanzamento).
    Il testo è disegnato a ``ss``× e ridotto: niente hinting, posizionamento sub-pixel.
    """
    font = load_font(font_path, size * ss)
    pos, total = text_advances(font, text, tracking * ss)
    asc, desc = font.getmetrics()
    x0 = int(math.floor(x)) - pad
    y0 = int(math.floor(baseline - asc / ss)) - pad
    w = int(math.ceil(total / ss)) + 2 * pad + 2
    h = int(math.ceil((asc + desc) / ss)) + 2 * pad + 2
    img = Image.new("L", (w * ss, h * ss), 0)
    d = ImageDraw.Draw(img)
    ox = (x - x0) * ss
    oy = (baseline - y0) * ss
    for p, ch in zip(pos, text):
        if ch != " ":
            d.text((ox + p, oy), ch, font=font, fill=255, anchor="ls")
    cov = np.asarray(img, np.float32).reshape(h, ss, w, ss).mean(axis=(1, 3)) / 255.0
    return premul(color, cov * opacity), x0, y0, total / ss


def text_width(text: str, font_path: str, size: float, tracking: float = 0.0) -> float:
    font = load_font(font_path, size * 4)
    return text_advances(font, text, tracking * 4)[1] / 4


def text_ink_box(text: str, font_path: str, size: float, tracking: float = 0.0):
    """Riquadro dell'inchiostro rispetto all'origine (x=0, baseline=0): (l, t, r, b)."""
    layer, x0, y0, _ = text_layer(text, font_path, size, (255, 255, 255), tracking, 0.0, 0.0)
    a = layer[..., 3]
    ys, xs = np.where(a > 0.5)
    return xs.min() + x0, ys.min() + y0, xs.max() + x0 + 1, ys.max() + y0 + 1


# ---------------------------------------------------------------- icone

def icon_layer(spec, size: int, ss: int = 4) -> np.ndarray:
    """Icona ``size``×``size``: nome di un'icona procedurale oppure percorso di un PNG."""
    if spec is None:
        return np.zeros((size, size, 4), np.float32)
    if isinstance(spec, dict):
        name, opts = spec.get("name") or spec.get("src"), spec
    else:
        name, opts = spec, {}
    if isinstance(name, str) and name.lower().endswith((".png", ".webp", ".jpg", ".jpeg")):
        return _icon_png(Path(name), size, opts.get("radius", 0))
    fn = _ICONS.get(name)
    if fn is None:
        raise ValueError(f"icona sconosciuta: {name!r} (procedurali: {', '.join(sorted(_ICONS))}; oppure un file .png)")
    px, py = _grid(0, 0, size, size, ss)
    u, v = px / size, py / size  # coordinate normalizzate 0..1
    rgb, cov = fn(u, v, size, opts)
    rgb = rgb.reshape(size, ss, size, ss, 3).mean(axis=(1, 3))
    cov = _downsample(cov, size, size, ss)
    # rgb già premoltiplicato sui sottocampioni
    return np.concatenate([rgb, cov[..., None]], -1).astype(np.float32)


def _icon_png(path: Path, size: int, radius: float) -> np.ndarray:
    im = Image.open(path).convert("RGBA")
    scale = min(size / im.width, size / im.height)
    nw, nh = max(1, round(im.width * scale)), max(1, round(im.height * scale))
    im = im.resize((nw, nh), Image.LANCZOS)
    canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    canvas.paste(im, ((size - nw) // 2, (size - nh) // 2))
    arr = np.asarray(canvas, np.float32)
    a = arr[..., 3] / 255.0
    if radius > 0:
        a = a * round_rect_mask(size, size, radius)
    return np.concatenate([arr[..., :3] * a[..., None], a[..., None]], -1)


def _col(c):
    return np.asarray(c, np.float32)


def _paint(layers):
    """Somma di strati (colore, copertura) in ordine: restituisce rgb premoltiplicato e alfa."""
    rgb = None
    acc = None
    for col, cov in layers:
        cov = cov.astype(np.float32)
        if rgb is None:
            rgb = np.zeros(cov.shape + (3,), np.float32)
            acc = np.zeros(cov.shape, np.float32)
        rgb = rgb * (1 - cov[..., None]) + _col(col)[None, :] * cov[..., None]
        acc = acc * (1 - cov) + cov
    return rgb, acc


def _icon_orbita(u, v, size, o):
    """Anello arancio con perno blu: icona generica «3D / blockout»."""
    r = np.hypot(u - 0.56, v - 0.55)
    ring = (np.abs(r - 0.27) <= 0.09).astype(np.float32)
    arm = ((np.abs((v - 0.42) + 0.55 * (u - 0.30)) <= 0.07) & (u > 0.06) & (u < 0.45)).astype(np.float32)
    core = (r <= 0.13).astype(np.float32)
    hole = (r <= 0.18).astype(np.float32)
    return _paint([(o.get("color", (234, 118, 0)), np.maximum(ring, arm)),
                   ((255, 255, 255), hole * (1 - core)), (o.get("accent", (38, 87, 146)), core)])


def _icon_spark(u, v, size, o):
    """Stella a quattro punte su quadrato arrotondato: icona generica «AI / generazione»."""
    sq = (sdf_round_rect(u, v, 0.04, 0.04, 0.92, 0.92, 0.24) <= 0).astype(np.float32)
    x, y = np.abs(u - 0.5), np.abs(v - 0.5)
    star = ((np.sqrt(x) + np.sqrt(y)) <= np.sqrt(0.30)).astype(np.float32)
    return _paint([(o.get("color", (25, 166, 137)), sq), (o.get("accent", (255, 255, 255)), star * sq)])


def _icon_play(u, v, size, o):
    sq = (sdf_round_rect(u, v, 0.04, 0.04, 0.92, 0.92, 0.24) <= 0).astype(np.float32)
    tri = ((u > 0.38) & (np.abs(v - 0.5) < (0.72 - u) * 0.85)).astype(np.float32)
    return _paint([(o.get("color", (60, 60, 70)), sq), (o.get("accent", (255, 255, 255)), tri * sq)])


def _icon_dot(u, v, size, o):
    c = (np.hypot(u - 0.5, v - 0.5) <= 0.32).astype(np.float32)
    return _paint([(o.get("color", (233, 133, 26)), c)])


_ICONS = {"orbita": _icon_orbita, "spark": _icon_spark, "play": _icon_play, "dot": _icon_dot}


# ---------------------------------------------------------------- etichetta a pillola

def label_layer(items: list[dict], style: dict, ss: int = 4) -> np.ndarray:
    """Etichetta completa (pillola + bordo + icone + testi), larghezza calcolata dal contenuto.

    Il livello restituito ha origine nell'angolo in alto a sinistra della pillola, più un
    margine ``style['margin']`` per il bordo esterno.
    """
    h = int(style["height"])
    font = style["font"]
    fsize = style["font_size"]
    tracking = style.get("tracking", 0.0)
    pad_l, pad_r = style["padding_left"], style["padding_right"]
    icon_size = int(style["icon_size"])
    base = style["baseline"]  # dalla cima della pillola
    gap_default = style.get("gap", 12)
    # 1) layout orizzontale
    x = pad_l
    placed = []
    for i, it in enumerate(items):
        if i > 0:
            x += it.get("gap_before", gap_default)
        if "icon" in it:
            placed.append(("icon", it, x))
            x += icon_size
        else:
            size = it.get("size", fsize)
            w = text_width(it["text"], it.get("font", font), size, it.get("tracking", tracking))
            placed.append(("text", it, x))
            x += w
    width = int(round(x + pad_r))
    m = int(style.get("margin", 2))
    W, H = width + 2 * m, h + 2 * m
    layer = np.zeros((H, W, 4), np.float32)
    # 2) pillola
    px, py = _grid(-m, -m, W, H, ss)
    d = sdf_round_rect(px, py, 0, 0, width, h, style["radius"])
    fill = _downsample(_cov(d, ss), H, W, ss) * style["fill_opacity"]
    over_layer(layer, premul(style["fill"], fill))
    bw = style.get("border_width", 0)
    if bw > 0:
        ring = _downsample(_cov(np.abs(d) - bw / 2, ss), H, W, ss) * style["border_opacity"]
        over_layer(layer, premul(style["border_color"], ring))
    # 3) contenuto
    for kind, it, ix in placed:
        if kind == "icon":
            ic = icon_layer(it["icon"], icon_size)
            iy = (h - icon_size) / 2 + it.get("dy", 0)
            _blit(layer, ic, int(round(ix)) + m, int(round(iy)) + m)
        else:
            size = it.get("size", fsize)
            col = it.get("color", style["text_color"])
            tl, tx0, ty0, _ = text_layer(it["text"], it.get("font", font), size, col,
                                         it.get("tracking", tracking), ix + m,
                                         base + m + it.get("dy", 0), ss,
                                         opacity=it.get("opacity", 1.0))
            _blit(layer, tl, tx0, ty0)
    return layer


def over_layer(dst: np.ndarray, src: np.ndarray) -> None:
    """dst ← src sopra dst (stesse dimensioni, entrambi premoltiplicati)."""
    a = src[..., 3:4]
    dst[..., :3] = src[..., :3] + dst[..., :3] * (1 - a)
    dst[..., 3:4] = a + dst[..., 3:4] * (1 - a)


def _blit(dst: np.ndarray, src: np.ndarray, x: int, y: int) -> None:
    h, w = src.shape[:2]
    H, W = dst.shape[:2]
    x0, y0, x1, y1 = max(x, 0), max(y, 0), min(x + w, W), min(y + h, H)
    if x1 > x0 and y1 > y0:
        over_layer(dst[y0:y1, x0:x1], src[y0 - y:y1 - y, x0 - x:x1 - x])
