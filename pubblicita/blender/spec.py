"""Schema, valori di default e validazione della spec JSON di uno shot blockout.

Nessuna dipendenza da Blender: la stessa validazione gira in pytest, negli
agenti che scrivono le spec e dentro ``build_shot.py`` prima di costruire la
scena. ``normalizza`` restituisce una copia completa di tutti i default, cosi'
``kit.py`` non deve ripetere valori sparsi. La documentazione per esteso e' in
``SPEC.md``.
"""
from __future__ import annotations

import copy
import json
import re
from pathlib import Path
from typing import Any

try:  # pacchetto importato normalmente (pytest, python -m)
    from . import moto
except ImportError:  # pragma: no cover - esecuzione come modulo isolato
    import moto  # type: ignore[no-redef]

FPS = 24

# ---------------------------------------------------------------------------
# Tabelle condivise con kit.py
# ---------------------------------------------------------------------------

PASTELLI = {
    "menta": "#CFF2E3",
    "lilla": "#E9C8F0",
    "crema": "#F2E6D8",
    "rosa": "#F7BCD8",
    "celeste": "#C4E4F8",
}

# Preset materiale: colore (hex), rugosita', metallico, coat, emissione.
MATERIALI: dict[str, dict[str, Any]] = {
    "clay": {"color": "#ECE5D8", "roughness": 0.38, "specular": 0.5},
    "clay_dark": {"color": "#3A3734", "roughness": 0.45},
    "mannequin": {"color": "#EEE7DB", "roughness": 0.32, "specular": 0.55, "coat": 0.15},
    "white_glossy": {"color": "#E7E5E1", "roughness": 0.22, "coat": 0.4},
    "car_paint": {"color": "#E7E5E1", "roughness": 0.25, "coat": 0.5},
    "black_matte": {"color": "#0B0B0C", "roughness": 0.9, "specular": 0.2},
    "glossy_black": {"color": "#060607", "roughness": 0.12, "coat": 0.3},
    "accent_dark": {"color": "#252527", "roughness": 0.25, "coat": 0.4},
    "building": {"color": "#101217", "roughness": 0.5},
    "wet_ground": {"color": "#0B0C0F", "roughness": 0.03, "wet": True, "ior": 2.4, "coat": 0.4},
    "asphalt": {"color": "#141519", "roughness": 0.6},
    "concrete": {"color": "#8D8A86", "roughness": 0.7},
    "wood": {"color": "#8A5530", "roughness": 0.65, "specular": 0.3},
    "wood_dark": {"color": "#3D2717", "roughness": 0.6, "specular": 0.3},
    "wood_light": {"color": "#B08457", "roughness": 0.6, "specular": 0.35},
    "metal": {"color": "#A3A7AB", "roughness": 0.28, "metallic": 1.0},
    "chrome": {"color": "#D8D8D8", "roughness": 0.05, "metallic": 1.0},
    "glass": {"color": "#07080A", "roughness": 0.04, "specular": 0.6},
    "glass_clear": {"color": "#FFFFFF", "roughness": 0.0, "transmission": 1.0},
    "paper": {"color": "#E6D7BC", "roughness": 0.85},
    "shoji": {"color": "#E2D2B5", "roughness": 0.7},
    "tatami": {"color": "#DCCCA6", "roughness": 0.75},
    "beige": {"color": "#D9C6A8", "roughness": 0.65},
    "navy": {"color": "#1A2232", "roughness": 0.5},
    "tile": {"color": "#3A2A20", "roughness": 0.12, "ior": 1.8},
    "rubber": {"color": "#0D0D0E", "roughness": 0.6},
    "plastic": {"color": "#C8C8C8", "roughness": 0.35},
}

# Preset di mondo/illuminazione. Le luci usano lo stesso schema di "lights".
MONDI: dict[str, dict[str, Any]] = {
    "night_city": {
        "color": "#0B1018", "strength": 0.35, "background": "#07090D", "background_strength": 1.0,
        "lights": [
            {"light_type": "area", "location": [3, -6, 9], "look_at": [0, 2, 0], "color": "#C9D6FF",
             "energy": 900, "size": 8, "size_y": 4},
            {"light_type": "area", "location": [-7, -3, 3], "look_at": [0, 0, 1], "color": "#D8DCEA",
             "energy": 220, "size": 4},
        ],
        "glare": {"type": "Bloom", "threshold": 0.8, "strength": 0.22, "size": 0.55},
    },
    "night_sky": {
        "color": "#1A2438", "strength": 0.6, "background": "#161E2E", "background_strength": 1.0,
        "lights": [
            {"light_type": "area", "location": [2, -5, 6], "look_at": [0, 0, 1.4], "color": "#DCE4FF",
             "energy": 500, "size": 5},
            {"light_type": "area", "location": [-4, 3, 3], "look_at": [0, 0, 1.4], "color": "#FFE2C4",
             "energy": 180, "size": 3},
        ],
        "glare": {"type": "Bloom", "threshold": 0.9, "strength": 0.4, "size": 0.6},
    },
    "warm_interior": {
        "color": "#3A322B", "strength": 0.35, "background": "#120C08", "background_strength": 1.0,
        "lights": [
            {"light_type": "area", "location": [0, -2.5, 2.4], "look_at": [0, 0.5, 1.1], "color": "#FFF1E0",
             "energy": 70, "size": 3.5, "size_y": 2.0},
        ],
        "glare": {"type": "Bloom", "threshold": 0.95, "strength": 0.35, "size": 0.6},
    },
    "studio": {
        "color": "#C9C9C9", "strength": 0.6, "background": "#BDBDBD", "background_strength": 1.0,
        "lights": [
            {"light_type": "area", "location": [3, -4, 4], "look_at": [0, 0, 1], "color": "#FFFFFF",
             "energy": 800, "size": 3},
            {"light_type": "area", "location": [-4, -2, 2.5], "look_at": [0, 0, 1], "color": "#FFFFFF",
             "energy": 250, "size": 3},
        ],
        "glare": False,
    },
    "dusk": {
        "color": "#5C6C8C", "strength": 0.6, "background": "#8C8FA8", "background_strength": 1.0,
        "lights": [
            {"light_type": "sun", "rotation": [80, 0, 125], "color": "#FFB27A", "energy": 2.5, "angle": 3},
        ],
        "glare": {"type": "Bloom", "threshold": 1.0, "strength": 0.3, "size": 0.6},
    },
    "day": {
        "color": "#BFD3EC", "strength": 0.9, "background": "#CFE0F2", "background_strength": 1.0,
        "lights": [
            {"light_type": "sun", "rotation": [50, 0, 35], "color": "#FFF4E6", "energy": 4.0, "angle": 2},
        ],
        "glare": False,
    },
    "none": {"color": "#000000", "strength": 0.0, "background": None, "background_strength": 1.0,
             "lights": [], "glare": False},
}

STILI_AUTO = ("coupe_80s", "hatchback", "sedan", "sports", "suv", "van")
ACCESSORI = ("hair_bun", "kanzashi", "flower", "sunglasses", "umbrella", "obi", "hat", "bag")
ABITI = ("long", "none", "pants", "skirt")
FACCE = ("front", "back", "left", "right")
TIPI_LUCE = ("area", "sun", "point", "spot")
GLARE = ("Bloom", "Fog Glow", "Streaks", "Ghosts", "Simple Star", "Sun Beams")
MOVIMENTI = ("static", "dolly_in", "dolly_out", "truck", "pedestal", "pan", "tilt", "orbit",
             "crane_up", "crane_down", "tracking", "zoom", "dolly_zoom", "roll")
VIEW_TRANSFORM = ("AgX", "Filmic", "Standard", "Khronos PBR Neutral")
LOOKS = ("None", "Punchy", "Greyscale", "Very High Contrast", "High Contrast", "Medium High Contrast",
         "Base Contrast", "Medium Low Contrast", "Low Contrast", "Very Low Contrast")

# ---------------------------------------------------------------------------
# Default delle sezioni
# ---------------------------------------------------------------------------

META_DEFAULT = {"fps": FPS, "resolution": [1280, 720], "samples": 12, "seed": 0, "note": ""}

RENDER_DEFAULT = {
    "engine": "cycles",
    "denoise": True,
    "adaptive_threshold": 0.04,
    "light_tree": False,
    "bounces": {"max": 4, "diffuse": 2, "glossy": 2, "transmission": 2, "transparent": 4, "volume": 0},
    "clamp_indirect": 6.0,
    "motion_blur": False,
    "shutter": 0.5,
    "view_transform": "Standard",   # pannelli emissivi a forza 1 = esattamente il colore hex, come nel riferimento
    "look": "None",
    "exposure": 0.0,
    "gamma": 1.0,
    "glare": "preset",          # "preset" = quello del mondo; False per spegnerlo; dict per personalizzarlo
    "vignette": 0.22,
    "film_transparent": False,
    "persistent_data": True,
    "crf": 14,
}

CAMERA_DEFAULT = {
    "lens": 35.0, "sensor": 36.0, "clip_start": 0.05, "clip_end": 1000.0,
    "location": [0.0, -8.0, 1.6], "look_at": [0.0, 0.0, 1.2], "rotation": None, "roll": 0.0,
    "keys": [], "moves": [], "dof": None, "handheld": None, "shift": [0.0, 0.0],
}

WORLD_DEFAULT = {"preset": "studio", "replace_lights": False, "lights": [], "fog": None, "volumetric": None}

COMUNI = {
    "location": [0.0, 0.0, 0.0], "rotation": [0.0, 0.0, 0.0], "scale": 1.0, "parent": None,
    "keys": [], "path": None, "visible": None, "repeat": None, "shadow": True, "note": "",
}

# Default per tipo di oggetto (oltre ai comuni).
TIPI: dict[str, dict[str, Any]] = {
    # primitive
    "box": {"size": [1.0, 1.0, 1.0], "bevel": 0.0, "origin": "center", "material": "clay"},
    "cylinder": {"radius": 0.5, "depth": 1.0, "vertices": 32, "origin": "center", "material": "clay", "smooth": True},
    "sphere": {"radius": 0.5, "segments": 32, "rings": 16, "material": "clay", "smooth": True},
    "cone": {"radius1": 0.5, "radius2": 0.0, "depth": 1.0, "vertices": 32, "origin": "center", "material": "clay", "smooth": True},
    "plane": {"size": [2.0, 2.0], "material": "clay"},
    "torus": {"major": 0.5, "minor": 0.1, "segments": 48, "material": "clay"},
    "capsule": {"radius": 0.1, "length": 1.0, "origin": "center", "material": "clay"},
    "lathe": {"profile": None, "segments": 32, "material": "clay", "smooth": True},
    "extrude": {"profile": None, "width": 1.0, "material": "clay", "smooth": False, "bevel": 0.0},
    "empty": {},
    "light": {"light_type": "area", "color": "#FFFFFF", "energy": 300.0, "size": 1.0, "size_y": None,
              "spot_size": 45.0, "spot_blend": 0.3, "angle": 1.0, "look_at": None, "camera_visible": False,
              "cast_shadow": True},
    # prefab
    "mannequin": {"height": 1.65, "pose": "standing", "joints": {}, "pose_keys": [], "walk": False,
                  "dress": "long", "color": "#EEE7DB", "accent": "#1E1E20", "accessories": [],
                  "umbrella_color": "#141416", "material": "mannequin"},
    "car": {"style": "coupe_80s", "color": "#E6E4E0", "lower_color": "#121315", "popup_headlights": False,
            "lights_on": True, "headlight_strength": 30.0, "headlight_beams": True,
            "taillight_color": "#FF5C70", "taillights_on": True, "doors_open": "none", "stripe": True},
    "building_block": {"size": [10.0, 10.0, 20.0], "color": "#101217", "material": "building",
                       "panels": [], "windows": None, "bevel": 0.0},
    "skyline": {"count": 6, "axis": "x", "spacing": 0.0, "width": [6.0, 12.0], "depth": [6.0, 10.0],
                "height": [10.0, 30.0], "seed": 1, "panels": {"count": 3}, "color": "#101217"},
    "billboard": {"size": [4.0, 2.25], "color": PASTELLI["lilla"], "strength": 1.1, "frame": None},
    "street": {"size": [40.0, 80.0], "wet": 0.85, "color": "#0B0C0F", "crosswalk": None,
               "lane_lines": False, "sidewalks": None},
    "room": {"size": [6.0, 5.0, 2.6], "walls": ["back", "left", "right"], "wall_style": "shoji",
             "floor": "tatami", "ceiling": True, "beam": True, "lintel": 1.85, "wall_color": "#DDD2BF",
             "frame_color": "#1D2535", "beam_color": "#6E4A2C", "panel_width": 1.5, "light": True},
    "corridor": {"length": 20.0, "width": 3.2, "height": 3.0, "wall_style": "wood_slats", "floor": "tiles",
                 "ceiling": True, "signs": True, "end": "dark", "wall_color": "#9A6236",
                 "lamps": {"count": 6, "side": "both", "radius": 0.22, "height": 2.35, "color": "#FFF1DC",
                           "strength": 6.0, "light_energy": 35.0}},
    "lantern": {"radius": 0.25, "color": "#FFF2DE", "strength": 6.0, "light_energy": 30.0,
                "cord": 0.0, "stretch": 1.1},
    "tower_lattice": {"height": 30.0, "base": 8.0, "top": 1.2, "levels": 10, "strut": 0.08,
                      "antenna": 6.0, "color": "#F2F2F2", "emission": 1.2},
    "tree": {"height": 4.0, "radius": 1.4, "style": "round", "color": "#CFC8BB", "trunk_color": "#5A4636"},
    "table": {"size": [1.2, 0.8, 0.75], "material": "wood"},
    "chair": {"seat_height": 0.45, "material": "wood"},
    "car_interior": {"drive": "right", "dash_color": "#141516", "seat_color": "#1B1B1D",
                     "wheel_color": "#0A0A0B", "gauges_color": "#FFB46B", "frame": True},
    "text": {"text": "TESTO", "size": 1.0, "extrude": 0.05, "align": "center", "material": "emissive:#FFFFFF:3"},
}
TIPI["sign"] = TIPI["text"]
PRIMITIVE = ("box", "cylinder", "sphere", "cone", "plane", "torus", "capsule", "lathe", "extrude", "empty", "light")


class SpecErrore(ValueError):
    """Spec non valida: ``errori`` contiene un messaggio per problema."""

    def __init__(self, errori: list[str]):
        super().__init__("spec non valida:\n- " + "\n- ".join(errori))
        self.errori = errori


# ---------------------------------------------------------------------------
# Controlli elementari
# ---------------------------------------------------------------------------

_HEX = re.compile(r"^#([0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")
_ID = re.compile(r"^[A-Za-z0-9_.-]{1,64}$")


def _num(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _vec(v, n: int) -> bool:
    return isinstance(v, (list, tuple)) and len(v) == n and all(_num(x) for x in v)


def colore_valido(v) -> bool:
    if isinstance(v, str):
        return bool(_HEX.match(v))
    return isinstance(v, (list, tuple)) and len(v) in (3, 4) and all(_num(x) and 0 <= x <= 1 for x in v)


def hex_a_rgb(v) -> tuple[float, float, float]:
    """"#rrggbb" (sRGB) o [r, g, b] in 0..1 -> terna sRGB 0..1."""
    if isinstance(v, (list, tuple)):
        return (float(v[0]), float(v[1]), float(v[2]))
    h = v.lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    return (int(h[0:2], 16) / 255.0, int(h[2:4], 16) / 255.0, int(h[4:6], 16) / 255.0)


def materiale_valido(v) -> str | None:
    """None se ``v`` e' un materiale accettabile, altrimenti il motivo."""
    if isinstance(v, str):
        if v in MATERIALI or colore_valido(v):
            return None
        if v.startswith("emissive:"):
            parti = v.split(":")
            if len(parti) not in (2, 3) or not colore_valido(parti[1]):
                return "formato atteso emissive:#rrggbb[:forza]"
            if len(parti) == 3:
                try:
                    float(parti[2])
                except ValueError:
                    return "forza dell'emissione non numerica"
            return None
        if ":" in v:
            nome, col = v.split(":", 1)
            if nome in MATERIALI and colore_valido(col):
                return None
        return f"materiale sconosciuto {v!r} (preset: {', '.join(sorted(MATERIALI))})"
    if isinstance(v, dict):
        if "preset" in v and v["preset"] not in MATERIALI:
            return f"preset materiale sconosciuto {v['preset']!r}"
        for k in ("color", "emission"):
            if k in v and not colore_valido(v[k]):
                return f"{k} non e' un colore valido"
        for k in ("roughness", "metallic", "coat", "transmission", "specular", "emission_strength", "alpha", "ior"):
            if k in v and not _num(v[k]):
                return f"{k} deve essere un numero"
        return None
    return "materiale: atteso nome preset, '#hex', 'emissive:#hex[:forza]' o dizionario"


def risolvi_materiale(v) -> dict[str, Any]:
    """Converte qualunque forma di materiale in un dict completo di parametri PBR."""
    base = {"color": "#CCCCCC", "roughness": 0.5, "metallic": 0.0, "coat": 0.0, "transmission": 0.0,
            "specular": 0.5, "ior": 1.5, "emission": None, "emission_strength": 0.0, "wet": False, "alpha": 1.0}
    if isinstance(v, str):
        if v.startswith("emissive:"):
            parti = v.split(":")
            base.update(color=parti[1], emission=parti[1],
                        emission_strength=float(parti[2]) if len(parti) == 3 else 3.0, emissive_only=True)
            return base
        if v in MATERIALI:
            base.update(MATERIALI[v])
            base["preset"] = v
            return base
        if ":" in v:
            nome, col = v.split(":", 1)
            base.update(MATERIALI[nome])
            base.update(color=col, preset=nome)
            return base
        base.update(MATERIALI["clay"])
        base["color"] = v
        return base
    d = dict(v)
    if "preset" in d:
        base.update(MATERIALI[d["preset"]])
    base.update(d)
    return base


# ---------------------------------------------------------------------------
# Validazione
# ---------------------------------------------------------------------------


class _Ctx:
    def __init__(self, frames: int):
        self.errori: list[str] = []
        self.avvisi: list[str] = []
        self.frames = frames

    def err(self, dove: str, msg: str) -> None:
        self.errori.append(f"{dove}: {msg}")


def _check_vec(ctx: _Ctx, dove: str, v, n: int) -> None:
    if not _vec(v, n):
        ctx.err(dove, f"atteso elenco di {n} numeri, trovato {v!r}")


def _check_color(ctx: _Ctx, dove: str, v, nullable: bool = False) -> None:
    if v is None and nullable:
        return
    if not colore_valido(v):
        ctx.err(dove, f"colore non valido {v!r} (usa '#rrggbb' o [r,g,b] 0..1)")


def _check_tempo(ctx: _Ctx, dove: str, k: dict) -> None:
    if "f" in k and "t" in k:
        ctx.err(dove, "usa 'f' (frame) oppure 't' (secondi), non entrambi")
    elif "f" in k:
        if not _num(k["f"]) or k["f"] < 0:
            ctx.err(dove, f"'f' deve essere un frame >= 0, trovato {k['f']!r}")
    elif "t" in k:
        if not _num(k["t"]) or k["t"] < 0:
            ctx.err(dove, f"'t' deve essere un tempo >= 0 in secondi, trovato {k['t']!r}")
    else:
        ctx.err(dove, "manca il tempo della chiave ('f' o 't')")


def _check_ease(ctx: _Ctx, dove: str, d: dict) -> None:
    if "ease" in d and d["ease"] not in moto.EASING:
        ctx.err(dove, f"easing sconosciuto {d['ease']!r} (validi: {', '.join(moto.EASING)})")


def _check_bersaglio(ctx: _Ctx, dove: str, v, nomi: set[str]) -> None:
    if v is None:
        return
    if isinstance(v, str):
        if v not in nomi:
            ctx.err(dove, f"oggetto {v!r} inesistente")
    elif isinstance(v, dict):
        if v.get("object") not in nomi:
            ctx.err(dove, f"oggetto {v.get('object')!r} inesistente")
        if "offset" in v:
            _check_vec(ctx, dove + ".offset", v["offset"], 3)
    else:
        _check_vec(ctx, dove, v, 3)


def _check_chiavi_oggetto(ctx: _Ctx, dove: str, chiavi) -> None:
    if not isinstance(chiavi, list):
        ctx.err(dove, "atteso elenco di chiavi")
        return
    for i, k in enumerate(chiavi):
        d = f"{dove}[{i}]"
        if not isinstance(k, dict):
            ctx.err(d, "atteso oggetto JSON")
            continue
        _check_tempo(ctx, d, k)
        _check_ease(ctx, d, k)
        for campo in ("location", "rotation"):
            if campo in k:
                _check_vec(ctx, f"{d}.{campo}", k[campo], 3)
        if "scale" in k and not (_num(k["scale"]) or _vec(k["scale"], 3)):
            ctx.err(f"{d}.scale", "atteso numero o elenco di 3 numeri")
        extra = set(k) - {"f", "t", "ease", "location", "rotation", "scale"}
        if extra:
            ctx.err(d, f"campi sconosciuti {sorted(extra)}")


def _check_percorso(ctx: _Ctx, dove: str, p) -> None:
    if not isinstance(p, dict):
        ctx.err(dove, "atteso oggetto JSON")
        return
    pts = p.get("points")
    if not isinstance(pts, list) or len(pts) < 2 or not all(_vec(x, 3) for x in pts):
        ctx.err(dove + ".points", "attesi almeno 2 punti [x, y, z]")
    for k in ("start", "end", "start_t", "end_t", "yaw_offset"):
        if k in p and not _num(p[k]):
            ctx.err(f"{dove}.{k}", "atteso numero")
    _check_ease(ctx, dove, p)
    if "offset" in p:
        _check_vec(ctx, dove + ".offset", p["offset"], 3)


def _check_luce(ctx: _Ctx, dove: str, l: dict, nomi: set[str]) -> None:
    if l.get("light_type", "area") not in TIPI_LUCE:
        ctx.err(dove + ".light_type", f"tipo luce sconosciuto (validi: {', '.join(TIPI_LUCE)})")
    _check_color(ctx, dove + ".color", l.get("color", "#FFFFFF"))
    for k in ("energy", "size", "spot_size", "spot_blend", "angle"):
        if k in l and not _num(l[k]):
            ctx.err(f"{dove}.{k}", "atteso numero")
    if l.get("size_y") is not None and not _num(l["size_y"]):
        ctx.err(dove + ".size_y", "atteso numero")
    for k in ("location", "rotation"):
        if k in l:
            _check_vec(ctx, f"{dove}.{k}", l[k], 3)
    _check_bersaglio(ctx, dove + ".look_at", l.get("look_at"), nomi)


def _check_pannelli(ctx: _Ctx, dove: str, p) -> None:
    if isinstance(p, dict):  # generazione casuale
        if "count" in p and (not isinstance(p["count"], int) or p["count"] < 0):
            ctx.err(dove + ".count", "atteso intero >= 0")
        for k in ("w", "h", "z"):
            if k in p:
                _check_vec(ctx, f"{dove}.{k}", p[k], 2)
        for i, c in enumerate(p.get("palette", [])):
            _check_color(ctx, f"{dove}.palette[{i}]", c)
        for f in p.get("faces", []):
            if f not in FACCE:
                ctx.err(dove + ".faces", f"faccia sconosciuta {f!r}")
        return
    if not isinstance(p, list):
        ctx.err(dove, "atteso elenco di pannelli o dizionario di generazione casuale")
        return
    for i, q in enumerate(p):
        d = f"{dove}[{i}]"
        if not isinstance(q, dict):
            ctx.err(d, "atteso oggetto JSON")
            continue
        if q.get("face", "front") not in FACCE:
            ctx.err(d + ".face", f"faccia sconosciuta (valide: {', '.join(FACCE)})")
        for k in ("x", "z", "w", "h", "strength", "depth"):
            if k in q and not _num(q[k]):
                ctx.err(f"{d}.{k}", "atteso numero")
        if "color" in q:
            _check_color(ctx, d + ".color", q["color"])


_SENZA_CONTROLLO_TIPO = {"walk", "material", "pose", "panels", "lamps", "joints", "pose_keys", "accessories",
                         "walls", "profile", "look_at", "frame"}


def _check_tipi_default(ctx: _Ctx, dove: str, o: dict, tipo: str) -> None:
    """Controllo generico: ogni parametro deve avere lo stesso tipo del suo default."""
    for k, dflt in TIPI[tipo].items():
        if k not in o or k in _SENZA_CONTROLLO_TIPO or dflt is None or "color" in k:
            continue
        v = o[k]
        if isinstance(dflt, bool):
            ok = isinstance(v, bool)
            atteso = "true/false"
        elif isinstance(dflt, (int, float)):
            ok = _num(v)
            atteso = "un numero"
        elif isinstance(dflt, list) and dflt and all(_num(x) for x in dflt):
            ok = _vec(v, len(dflt))
            atteso = f"un elenco di {len(dflt)} numeri"
        elif isinstance(dflt, str):
            ok = isinstance(v, str)
            atteso = "un testo"
        else:
            continue
        if not ok:
            ctx.err(f"{dove}.{k}", f"atteso {atteso}, trovato {v!r}")


def _check_oggetto(ctx: _Ctx, i: int, o, nomi: set[str]) -> None:
    dove = f"objects[{i}]"
    if not isinstance(o, dict):
        ctx.err(dove, "atteso oggetto JSON")
        return
    tipo = o.get("type")
    if tipo not in TIPI:
        ctx.err(dove + ".type", f"tipo sconosciuto {tipo!r} (validi: {', '.join(sorted(TIPI))})")
        return
    dove = f"objects[{i}] ({o.get('name', tipo)})"
    ammessi = set(COMUNI) | set(TIPI[tipo]) | {"name", "type"}
    if tipo not in ("empty", "light"):
        ammessi |= {"material", "color"}
    sconosciuti = set(o) - ammessi
    if sconosciuti:
        ctx.err(dove, f"campi sconosciuti per {tipo}: {sorted(sconosciuti)}")
    _check_tipi_default(ctx, dove, o, tipo)
    for k in ("location", "rotation"):
        if k in o:
            _check_vec(ctx, f"{dove}.{k}", o[k], 3)
    if "scale" in o and not (_num(o["scale"]) or _vec(o["scale"], 3)):
        ctx.err(dove + ".scale", "atteso numero o elenco di 3 numeri")
    if o.get("parent") is not None and o["parent"] not in nomi:
        ctx.err(dove + ".parent", f"genitore {o['parent']!r} inesistente")
    if o.get("parent") is not None and o.get("parent") == o.get("name"):
        ctx.err(dove + ".parent", "un oggetto non puo' essere genitore di se stesso")
    if "keys" in o:
        _check_chiavi_oggetto(ctx, dove + ".keys", o["keys"])
    if o.get("path") is not None:
        _check_percorso(ctx, dove + ".path", o["path"])
    if o.get("visible") is not None:
        v = o["visible"]
        if not isinstance(v, dict) or not all(_num(v.get(k, 0)) for k in ("from", "to")):
            ctx.err(dove + ".visible", "atteso {\"from\": frame, \"to\": frame}")
    if o.get("repeat") is not None:
        r = o["repeat"]
        if not isinstance(r, dict) or not isinstance(r.get("count"), int) or r["count"] < 1:
            ctx.err(dove + ".repeat", "atteso {\"count\": n>=1, \"offset\": [dx,dy,dz]}")
        else:
            _check_vec(ctx, dove + ".repeat.offset", r.get("offset", [0, 0, 0]), 3)
            if "rotation" in r:
                _check_vec(ctx, dove + ".repeat.rotation", r["rotation"], 3)
    if "material" in o:
        motivo = materiale_valido(o["material"])
        if motivo:
            ctx.err(dove + ".material", motivo)
    for k in ("color", "accent", "lower_color", "taillight_color", "wall_color", "frame_color",
              "beam_color", "trunk_color", "dash_color", "seat_color", "wheel_color", "gauges_color",
              "umbrella_color"):
        if k in o:
            _check_color(ctx, f"{dove}.{k}", o[k])

    # controlli specifici
    if tipo == "box" and "size" in o:
        _check_vec(ctx, dove + ".size", o["size"], 3)
    if tipo == "plane" and "size" in o:
        _check_vec(ctx, dove + ".size", o["size"], 2)
    if tipo in ("box", "cylinder", "cone", "capsule") and o.get("origin", "center") not in ("center", "bottom"):
        ctx.err(dove + ".origin", "valori ammessi: center, bottom")
    if tipo == "lathe":
        prof = o.get("profile")
        if not isinstance(prof, list) or len(prof) < 2 or not all(_vec(p, 2) and p[0] >= 0 for p in prof):
            ctx.err(dove + ".profile", "attesi almeno 2 punti [raggio>=0, z]")
    if tipo == "extrude":
        prof = o.get("profile")
        if not isinstance(prof, list) or len(prof) < 3 or not all(_vec(p, 2) for p in prof):
            ctx.err(dove + ".profile", "attesi almeno 3 punti [y, z] del poligono laterale")
    if tipo == "light":
        _check_luce(ctx, dove, o, nomi)
    if tipo == "mannequin":
        p = o.get("pose", "standing")
        if not (p in moto.POSE or isinstance(p, dict)):
            ctx.err(dove + ".pose", f"posa sconosciuta {p!r} (preset: {', '.join(moto.POSE)})")
        _check_giunti(ctx, dove + ".joints", o.get("joints", {}))
        for j, k in enumerate(o.get("pose_keys", [])):
            dk = f"{dove}.pose_keys[{j}]"
            if not isinstance(k, dict):
                ctx.err(dk, "atteso oggetto JSON")
                continue
            _check_tempo(ctx, dk, k)
            _check_ease(ctx, dk, k)
            if "pose" in k and k["pose"] not in moto.POSE:
                ctx.err(dk + ".pose", f"posa sconosciuta {k['pose']!r}")
            _check_giunti(ctx, dk + ".joints", k.get("joints", {}))
        if o.get("dress", "long") not in ABITI:
            ctx.err(dove + ".dress", f"valori ammessi: {', '.join(ABITI)}")
        acc = o.get("accessories", [])
        if not isinstance(acc, list) or any(a not in ACCESSORI for a in acc):
            ctx.err(dove + ".accessories", f"accessori ammessi: {', '.join(ACCESSORI)}")
        w = o.get("walk", False)
        if not isinstance(w, (bool, dict)):
            ctx.err(dove + ".walk", "atteso true/false o {cadence, stride, amplitude, phase}")
    if tipo == "car":
        if o.get("style", "coupe_80s") not in STILI_AUTO:
            ctx.err(dove + ".style", f"stili ammessi: {', '.join(STILI_AUTO)}")
        if o.get("doors_open", "none") not in ("none", "left", "right", "both"):
            ctx.err(dove + ".doors_open", "valori ammessi: none, left, right, both")
    if tipo == "building_block":
        if "size" in o:
            _check_vec(ctx, dove + ".size", o["size"], 3)
        if "panels" in o:
            _check_pannelli(ctx, dove + ".panels", o["panels"])
    if tipo == "skyline" and "panels" in o:
        _check_pannelli(ctx, dove + ".panels", o["panels"])
    if tipo == "billboard" and "size" in o:
        _check_vec(ctx, dove + ".size", o["size"], 2)
    if tipo == "street":
        if "size" in o:
            _check_vec(ctx, dove + ".size", o["size"], 2)
    if tipo == "room":
        if "size" in o:
            _check_vec(ctx, dove + ".size", o["size"], 3)
        if o.get("wall_style", "shoji") not in ("shoji", "plain", "wood"):
            ctx.err(dove + ".wall_style", "valori ammessi: shoji, plain, wood")
        if o.get("floor", "tatami") not in ("tatami", "wood", "concrete", "tiles"):
            ctx.err(dove + ".floor", "valori ammessi: tatami, wood, concrete, tiles")
        for w in o.get("walls", []):
            if w not in FACCE:
                ctx.err(dove + ".walls", f"parete sconosciuta {w!r}")
    if tipo == "corridor":
        if o.get("wall_style", "wood_slats") not in ("wood_slats", "plain", "shoji"):
            ctx.err(dove + ".wall_style", "valori ammessi: wood_slats, plain, shoji")
        if o.get("floor", "tiles") not in ("tiles", "wood", "stone"):
            ctx.err(dove + ".floor", "valori ammessi: tiles, wood, stone")
        if o.get("end", "dark") not in ("dark", "wall", "open"):
            ctx.err(dove + ".end", "valori ammessi: dark, wall, open")
    if tipo == "tree" and o.get("style", "round") not in ("round", "cone"):
        ctx.err(dove + ".style", "valori ammessi: round, cone")
    if tipo == "car_interior" and o.get("drive", "right") not in ("right", "left"):
        ctx.err(dove + ".drive", "valori ammessi: right, left")
    if tipo in ("text", "sign") and not isinstance(o.get("text", "TESTO"), str):
        ctx.err(dove + ".text", "atteso testo")


def _check_giunti(ctx: _Ctx, dove: str, giunti) -> None:
    if not isinstance(giunti, dict):
        ctx.err(dove, "atteso dizionario giunto -> [x, y, z] in gradi")
        return
    for n, v in giunti.items():
        if n not in moto.GIUNTI:
            ctx.err(dove, f"giunto sconosciuto {n!r} (validi: {', '.join(moto.GIUNTI)})")
        else:
            _check_vec(ctx, f"{dove}.{n}", v, 3)


def _check_camera(ctx: _Ctx, cam, nomi: set[str]) -> None:
    if not isinstance(cam, dict):
        ctx.err("camera", "atteso oggetto JSON")
        return
    sconosciuti = set(cam) - set(CAMERA_DEFAULT) - {"preset"}
    if sconosciuti:
        ctx.err("camera", f"campi sconosciuti {sorted(sconosciuti)}")
    for k in ("lens", "sensor", "clip_start", "clip_end", "roll"):
        if k in cam and not _num(cam[k]):
            ctx.err(f"camera.{k}", "atteso numero")
    if "location" in cam:
        _check_vec(ctx, "camera.location", cam["location"], 3)
    if cam.get("rotation") is not None:
        _check_vec(ctx, "camera.rotation", cam["rotation"], 3)
    if "shift" in cam:
        _check_vec(ctx, "camera.shift", cam["shift"], 2)
    _check_bersaglio(ctx, "camera.look_at", cam.get("look_at"), nomi)
    for i, k in enumerate(cam.get("keys", [])):
        d = f"camera.keys[{i}]"
        if not isinstance(k, dict):
            ctx.err(d, "atteso oggetto JSON")
            continue
        _check_tempo(ctx, d, k)
        _check_ease(ctx, d, k)
        if "location" in k:
            _check_vec(ctx, d + ".location", k["location"], 3)
        if "rotation" in k:
            _check_vec(ctx, d + ".rotation", k["rotation"], 3)
        _check_bersaglio(ctx, d + ".look_at", k.get("look_at"), nomi)
        for c in ("lens", "roll", "focus_distance"):
            if c in k and not _num(k[c]):
                ctx.err(f"{d}.{c}", "atteso numero")
        extra = set(k) - {"f", "t", "ease", "location", "rotation", "look_at", "lens", "roll", "focus_distance"}
        if extra:
            ctx.err(d, f"campi sconosciuti {sorted(extra)}")
    mosse = cam.get("moves", [])
    if "preset" in cam:
        mosse = cam["preset"] if isinstance(cam["preset"], list) else [cam["preset"]]
    for i, m in enumerate(mosse):
        d = f"camera.moves[{i}]"
        if not isinstance(m, dict) or m.get("type") not in MOVIMENTI:
            ctx.err(d, f"movimento sconosciuto (validi: {', '.join(MOVIMENTI)})")
            continue
        _check_ease(ctx, d, m)
        for c in ("distance", "angle", "height", "lens_end", "start", "end"):
            if c in m and not _num(m[c]):
                ctx.err(f"{d}.{c}", "atteso numero")
        if m["type"] == "tracking":
            if "target" not in m:
                ctx.err(d, "tracking richiede 'target'")
            else:
                _check_bersaglio(ctx, d + ".target", m["target"], nomi)
        if "center" in m:
            _check_bersaglio(ctx, d + ".center", m["center"], nomi)
        for c in ("offset", "look_offset"):
            if c in m:
                _check_vec(ctx, f"{d}.{c}", m[c], 3)
    dof = cam.get("dof")
    if dof is not None:
        if not isinstance(dof, dict):
            ctx.err("camera.dof", "atteso oggetto JSON o null")
        else:
            fuoco = dof.get("focus")
            if fuoco is not None and not _num(fuoco):
                _check_bersaglio(ctx, "camera.dof.focus", fuoco, nomi)
            if "fstop" in dof and (not _num(dof["fstop"]) or dof["fstop"] <= 0):
                ctx.err("camera.dof.fstop", "atteso numero > 0")
    hh = cam.get("handheld")
    if hh is not None and not isinstance(hh, (dict, bool)):
        ctx.err("camera.handheld", "atteso oggetto JSON, true o null")


def valida(spec: Any) -> list[str]:
    """Restituisce l'elenco degli errori (vuoto se la spec e' valida)."""
    if not isinstance(spec, dict):
        return ["la spec deve essere un oggetto JSON"]
    meta = spec.get("meta")
    ctx = _Ctx(1)
    if not isinstance(meta, dict):
        ctx.err("meta", "sezione obbligatoria mancante")
        meta = {}
    sconosciute = set(spec) - {"meta", "world", "render", "camera", "objects", "$schema", "note"}
    if sconosciute:
        ctx.err("spec", f"sezioni sconosciute {sorted(sconosciute)}")
    mid = meta.get("id")
    if not isinstance(mid, str) or not _ID.match(mid):
        ctx.err("meta.id", "obbligatorio: lettere, cifre, _ . - (max 64)")
    frames = meta.get("frames")
    if frames is None and _num(meta.get("seconds")):
        frames = round(meta["seconds"] * FPS)
    if not isinstance(frames, int) or isinstance(frames, bool) or frames < 1:
        ctx.err("meta.frames", "obbligatorio: intero >= 1 (oppure 'seconds')")
    else:
        ctx.frames = frames
    if meta.get("fps", FPS) != FPS:
        ctx.err("meta.fps", f"la pipeline lavora solo a {FPS} fps")
    if "resolution" in meta:
        r = meta["resolution"]
        if not (_vec(r, 2) and all(isinstance(x, int) and x >= 16 for x in r)):
            ctx.err("meta.resolution", "attesi due interi >= 16 [larghezza, altezza]")
    if "samples" in meta and (not isinstance(meta["samples"], int) or meta["samples"] < 1):
        ctx.err("meta.samples", "atteso intero >= 1")
    if "seed" in meta and not isinstance(meta["seed"], int):
        ctx.err("meta.seed", "atteso intero")

    objs = spec.get("objects", [])
    if not isinstance(objs, list):
        ctx.err("objects", "atteso elenco")
        objs = []
    nomi: set[str] = set()
    for i, o in enumerate(objs):
        if isinstance(o, dict):
            n = o.get("name")
            if n is None:
                continue
            if not isinstance(n, str) or not n:
                ctx.err(f"objects[{i}].name", "atteso testo non vuoto")
            elif n in nomi:
                ctx.err(f"objects[{i}].name", f"nome duplicato {n!r}")
            else:
                nomi.add(n)
    for i, o in enumerate(objs):
        _check_oggetto(ctx, i, o, nomi)

    world = spec.get("world", {})
    if not isinstance(world, dict):
        ctx.err("world", "atteso oggetto JSON")
    else:
        sconosciuti = set(world) - set(WORLD_DEFAULT) - {"color", "strength", "background", "background_strength"}
        if sconosciuti:
            ctx.err("world", f"campi sconosciuti {sorted(sconosciuti)}")
        if world.get("preset", "studio") not in MONDI:
            ctx.err("world.preset", f"preset sconosciuto (validi: {', '.join(MONDI)})")
        for k in ("color", "background"):
            if k in world:
                _check_color(ctx, f"world.{k}", world[k], nullable=(k == "background"))
        for k in ("strength", "background_strength"):
            if k in world and not _num(world[k]):
                ctx.err(f"world.{k}", "atteso numero")
        for i, l in enumerate(world.get("lights", [])):
            if not isinstance(l, dict):
                ctx.err(f"world.lights[{i}]", "atteso oggetto JSON")
            else:
                _check_luce(ctx, f"world.lights[{i}]", l, nomi)
        fog = world.get("fog")
        if fog is not None:
            if not isinstance(fog, dict):
                ctx.err("world.fog", "atteso oggetto JSON o null")
            else:
                for k in ("start", "depth", "amount"):
                    if k in fog and not _num(fog[k]):
                        ctx.err(f"world.fog.{k}", "atteso numero")
                if "color" in fog:
                    _check_color(ctx, "world.fog.color", fog["color"])
        vol = world.get("volumetric")
        if vol is not None and not isinstance(vol, dict):
            ctx.err("world.volumetric", "atteso oggetto JSON o null")

    render = spec.get("render", {})
    if not isinstance(render, dict):
        ctx.err("render", "atteso oggetto JSON")
    else:
        sconosciuti = set(render) - set(RENDER_DEFAULT) - {"samples"}
        if sconosciuti:
            ctx.err("render", f"campi sconosciuti {sorted(sconosciuti)}")
        if render.get("engine", "cycles") != "cycles":
            ctx.err("render.engine", "e' supportato solo 'cycles' (EEVEE senza GPU e' piu' lento)")
        if render.get("view_transform", "AgX") not in VIEW_TRANSFORM:
            ctx.err("render.view_transform", f"validi: {', '.join(VIEW_TRANSFORM)}")
        if render.get("look", "None") not in LOOKS:
            ctx.err("render.look", f"validi: {', '.join(LOOKS)}")
        g = render.get("glare", "preset")
        if not (g in ("preset", False, None) or isinstance(g, dict)):
            ctx.err("render.glare", "atteso \"preset\", false o {type, threshold, strength, size}")
        if isinstance(g, dict) and g.get("type", "Bloom") not in GLARE:
            ctx.err("render.glare.type", f"validi: {', '.join(GLARE)}")
        for k in ("vignette", "exposure", "gamma", "shutter", "clamp_indirect", "adaptive_threshold"):
            if k in render and not _num(render[k]):
                ctx.err(f"render.{k}", "atteso numero")
        if "crf" in render and (not isinstance(render["crf"], int) or not 0 <= render["crf"] <= 51):
            ctx.err("render.crf", "atteso intero 0..51")
        if "bounces" in render and not isinstance(render["bounces"], dict):
            ctx.err("render.bounces", "atteso oggetto JSON")

    if "camera" in spec:
        _check_camera(ctx, spec["camera"], nomi)
    return ctx.errori


# ---------------------------------------------------------------------------
# Normalizzazione
# ---------------------------------------------------------------------------


def _unisci(base: dict, sopra: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in sopra.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _unisci(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out


def _tempi_in_frame(d: dict) -> dict:
    """Converte 't' (secondi) in 'f' nelle chiavi, per avere un'unica unita'."""
    if "t" in d and "f" not in d:
        d = dict(d)
        d["f"] = d.pop("t") * FPS
    return d


def normalizza(spec: dict) -> dict:
    """Copia della spec con tutti i default espliciti (presuppone ``valida`` ok)."""
    s = copy.deepcopy(spec)
    meta = _unisci(META_DEFAULT, s.get("meta", {}))
    if "frames" not in meta:
        meta["frames"] = round(meta.pop("seconds") * FPS)
    meta.pop("seconds", None)
    out: dict[str, Any] = {"meta": meta}

    world_in = s.get("world", {})
    preset = MONDI[world_in.get("preset", "studio")]
    world = _unisci(WORLD_DEFAULT, {k: v for k, v in preset.items() if k not in ("lights", "glare")})
    world = _unisci(world, {k: v for k, v in world_in.items() if k != "lights"})
    luci_preset = [] if world_in.get("replace_lights") else copy.deepcopy(preset["lights"])
    world["lights"] = [_unisci(TIPI["light"], l) for l in luci_preset + list(world_in.get("lights", []))]
    out["world"] = world

    render = _unisci(RENDER_DEFAULT, s.get("render", {}))
    render["samples"] = render.get("samples", meta["samples"])
    if render["glare"] == "preset":
        render["glare"] = copy.deepcopy(preset.get("glare", False))
    elif render["glare"] is None:
        render["glare"] = False
    if isinstance(render["glare"], dict):
        render["glare"] = _unisci({"type": "Bloom", "threshold": 0.9, "strength": 0.4, "size": 0.6}, render["glare"])
    render["bounces"] = _unisci(RENDER_DEFAULT["bounces"], render.get("bounces", {}))
    out["render"] = render

    cam = _unisci(CAMERA_DEFAULT, {k: v for k, v in s.get("camera", {}).items() if k != "preset"})
    if "preset" in s.get("camera", {}):
        p = s["camera"]["preset"]
        cam["moves"] = list(cam.get("moves", [])) + (p if isinstance(p, list) else [p])
    cam["keys"] = [_tempi_in_frame(k) for k in cam["keys"]]
    for m in cam["moves"]:
        for a, b in (("start_t", "start"), ("end_t", "end")):
            if a in m:
                m[b] = m.pop(a) * FPS
    if cam["handheld"] is True:
        cam["handheld"] = {}
    if isinstance(cam["handheld"], dict):
        cam["handheld"] = _unisci({"amplitude": 0.012, "rotation": 0.3, "frequency": 1.0, "seed": 1}, cam["handheld"])
    if isinstance(cam["dof"], dict):
        cam["dof"] = _unisci({"focus": None, "fstop": 4.0}, cam["dof"])
    out["camera"] = cam

    objs = []
    for i, o in enumerate(s.get("objects", [])):
        tipo = o["type"]
        n = _unisci(COMUNI, TIPI[tipo])
        n = _unisci(n, o)
        n.setdefault("name", f"{tipo}_{i:02d}")
        n["keys"] = [_tempi_in_frame(k) for k in n.get("keys", [])]
        if tipo == "mannequin":
            n["pose_keys"] = [_tempi_in_frame(k) for k in n.get("pose_keys", [])]
        if n.get("path"):
            p = n["path"]
            for a, b in (("start_t", "start"), ("end_t", "end")):
                if a in p:
                    p[b] = p.pop(a) * FPS
            p.setdefault("start", 0)
            p.setdefault("end", meta["frames"] - 1)
        objs.append(n)
    out["objects"] = objs
    if "note" in s:
        out["note"] = s["note"]
    return out


def carica(percorso: str | Path) -> dict:
    """Legge, valida e normalizza una spec JSON. Solleva ``SpecErrore``."""
    try:
        dati = json.loads(Path(percorso).read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SpecErrore([f"JSON non valido: {exc}"]) from exc
    errori = valida(dati)
    if errori:
        raise SpecErrore(errori)
    return normalizza(dati)


def main(argv: list[str] | None = None) -> int:
    """``python3 -m pubblicita.blender.spec file.json ...``: valida una o piu' spec."""
    import sys

    args = sys.argv[1:] if argv is None else argv
    if not args:
        print("uso: python3 -m pubblicita.blender.spec spec.json [altre.json ...]")
        return 2
    esito = 0
    for a in args:
        try:
            s = carica(a)
            print(f"OK  {a}  ({s['meta']['id']}, {s['meta']['frames']} frame, {len(s['objects'])} oggetti)")
        except (SpecErrore, OSError) as exc:
            esito = 1
            print(f"ERR {a}\n{exc}")
    return esito


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
