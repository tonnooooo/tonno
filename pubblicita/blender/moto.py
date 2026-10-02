"""Matematica dei movimenti per i blockout, in puro Python (niente bpy).

Tutto cio' che si anima (camera, oggetti con keyframe o percorso, ruote delle
auto, camminata del manichino) viene calcolato qui fotogramma per fotogramma e
poi "cotto" in keyframe da ``kit.py``. Tenere la matematica fuori da Blender
permette di testarla con pytest e di controllare l'easing senza dipendere
dalle API delle F-curve, cambiate piu' volte tra Blender 4.x e 5.x.

Convenzioni: unita' in metri, Z in alto, angoli in gradi nei JSON e in radianti
qui dentro solo dove indicato. Il "fronte" di ogni prefab guarda verso -Y.
"""
from __future__ import annotations

import math
from typing import Callable, Iterable, Sequence

Vec = tuple[float, float, float]

# ---------------------------------------------------------------------------
# Easing
# ---------------------------------------------------------------------------


def _back_out(t: float) -> float:
    c1 = 1.70158
    c3 = c1 + 1.0
    return 1.0 + c3 * (t - 1.0) ** 3 + c1 * (t - 1.0) ** 2


EASING: dict[str, Callable[[float], float]] = {
    "linear": lambda t: t,
    "in": lambda t: t * t * t,
    "out": lambda t: 1.0 - (1.0 - t) ** 3,
    "in_out": lambda t: 4 * t * t * t if t < 0.5 else 1.0 - (-2 * t + 2) ** 3 / 2,
    "smooth": lambda t: t * t * (3 - 2 * t),
    "sine": lambda t: -(math.cos(math.pi * t) - 1) / 2,
    "expo_in": lambda t: 0.0 if t <= 0 else 2 ** (10 * t - 10),
    "expo_out": lambda t: 1.0 if t >= 1 else 1 - 2 ** (-10 * t),
    "back_out": _back_out,
    "constant": lambda t: 0.0 if t < 1.0 else 1.0,
}


def ease(nome: str | None, t: float) -> float:
    """Applica l'easing ``nome`` a ``t`` (limitato a 0..1)."""
    t = 0.0 if t < 0 else 1.0 if t > 1 else t
    return EASING[nome or "linear"](t)


def progresso(f: float, inizio: float, fine: float, easing: str | None = "linear") -> float:
    """Avanzamento 0..1 di un movimento tra i frame ``inizio`` e ``fine``."""
    if fine <= inizio:
        return 1.0 if f >= inizio else 0.0
    return ease(easing, (f - inizio) / (fine - inizio))


# ---------------------------------------------------------------------------
# Vettori minimi
# ---------------------------------------------------------------------------


def add(a: Sequence[float], b: Sequence[float]) -> Vec:
    return (a[0] + b[0], a[1] + b[1], a[2] + b[2])


def sub(a: Sequence[float], b: Sequence[float]) -> Vec:
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def mul(a: Sequence[float], k: float) -> Vec:
    return (a[0] * k, a[1] * k, a[2] * k)


def lerp(a, b, t: float):
    if isinstance(a, (int, float)):
        return a + (b - a) * t
    return tuple(x + (y - x) * t for x, y in zip(a, b))


def lunghezza(a: Sequence[float]) -> float:
    return math.sqrt(sum(x * x for x in a))


def normalizza(a: Sequence[float]) -> Vec:
    n = lunghezza(a)
    if n < 1e-12:
        return (0.0, 0.0, 0.0)
    return (a[0] / n, a[1] / n, a[2] / n)


def croce(a: Sequence[float], b: Sequence[float]) -> Vec:
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def ruota_z(v: Sequence[float], ang: float, centro: Sequence[float] = (0, 0, 0)) -> Vec:
    """Ruota ``v`` attorno all'asse Z passante per ``centro`` (radianti)."""
    x, y = v[0] - centro[0], v[1] - centro[1]
    c, s = math.cos(ang), math.sin(ang)
    return (centro[0] + x * c - y * s, centro[1] + x * s + y * c, v[2])


def ruota_asse(v: Sequence[float], asse: Sequence[float], ang: float) -> Vec:
    """Rotazione di Rodrigues di ``v`` attorno ad ``asse`` (radianti)."""
    k = normalizza(asse)
    c, s = math.cos(ang), math.sin(ang)
    kxv = croce(k, v)
    kdv = k[0] * v[0] + k[1] * v[1] + k[2] * v[2]
    return tuple(v[i] * c + kxv[i] * s + k[i] * kdv * (1 - c) for i in range(3))  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# Orientamento
# ---------------------------------------------------------------------------


def look_at_euler(pos: Sequence[float], bersaglio: Sequence[float], roll_deg: float = 0.0) -> Vec:
    """Euler XYZ (radianti) di una camera Blender in ``pos`` che guarda ``bersaglio``.

    La camera Blender guarda lungo -Z locale con +Y in alto: rot_x = 90 gradi la
    rende orizzontale (verso +Y), rot_z la fa girare attorno all'asse verticale.
    Il roll e' approssimato sull'asse Y (esatto per inquadrature orizzontali),
    sufficiente per inclinazioni lievi e per il micro-mosso.
    """
    d = sub(bersaglio, pos)
    h = math.hypot(d[0], d[1])
    rx = math.atan2(h, -d[2]) if (h > 1e-9 or abs(d[2]) > 1e-9) else math.pi / 2
    rz = math.atan2(-d[0], d[1]) if h > 1e-9 else 0.0
    return (rx, math.radians(roll_deg), rz)


def yaw_da_direzione(dx: float, dy: float) -> float:
    """Rotazione Z (radianti) che porta il fronte (-Y) di un prefab lungo (dx, dy)."""
    return math.atan2(dx, -dy)


def srotola(angoli: Sequence[float]) -> list[float]:
    """Rende continua una sequenza di angoli (radianti) eliminando i salti di 2*pi."""
    out: list[float] = []
    for a in angoli:
        if out:
            prev = out[-1]
            while a - prev > math.pi:
                a -= 2 * math.pi
            while a - prev < -math.pi:
                a += 2 * math.pi
        out.append(a)
    return out


# ---------------------------------------------------------------------------
# Keyframe
# ---------------------------------------------------------------------------


def frame_di(chiave: dict, fps: int = 24) -> float:
    """Frame di una chiave: accetta ``f`` (frame, base 0) oppure ``t`` (secondi)."""
    if "f" in chiave:
        return float(chiave["f"])
    return float(chiave["t"]) * fps


def campiona_chiavi(chiavi: Sequence[dict], campo: str, f: float, base=None, fps: int = 24):
    """Valore di ``campo`` al frame ``f`` interpolando le chiavi che lo definiscono.

    Ogni chiave puo' indicare ``ease``: e' la curva usata per ARRIVARE a quella
    chiave dalla precedente. Prima della prima chiave e dopo l'ultima il valore
    resta fermo. Se nessuna chiave definisce il campo restituisce ``base``.
    """
    pts = [(frame_di(k, fps), k[campo], k.get("ease", "in_out")) for k in chiavi if campo in k]
    if not pts:
        return base
    pts.sort(key=lambda p: p[0])
    if f <= pts[0][0]:
        return pts[0][1]
    for (f0, v0, _), (f1, v1, e1) in zip(pts, pts[1:]):
        if f <= f1:
            return lerp(v0, v1, progresso(f, f0, f1, e1))
    return pts[-1][1]


# ---------------------------------------------------------------------------
# Percorsi
# ---------------------------------------------------------------------------


def _catmull(p0, p1, p2, p3, t):
    t2, t3 = t * t, t * t * t
    return tuple(
        0.5 * ((2 * b) + (-a + c) * t + (2 * a - 5 * b + 4 * c - d) * t2 + (-a + 3 * b - 3 * c + d) * t3)
        for a, b, c, d in zip(p0, p1, p2, p3)
    )


class Percorso:
    """Polilinea (o spline Catmull-Rom) parametrizzata per lunghezza d'arco."""

    def __init__(self, punti: Sequence[Sequence[float]], liscio: bool = True, campioni: int = 24):
        pts = [tuple(float(c) for c in p) + (0.0,) * (3 - len(p)) for p in punti]
        if len(pts) < 2:
            raise ValueError("un percorso richiede almeno 2 punti")
        if liscio and len(pts) > 2:
            dense = []
            ext = [pts[0]] + pts + [pts[-1]]
            for i in range(len(pts) - 1):
                for j in range(campioni):
                    dense.append(_catmull(ext[i], ext[i + 1], ext[i + 2], ext[i + 3], j / campioni))
            dense.append(pts[-1])
            pts = dense
        self.punti = pts
        self.cum = [0.0]
        for a, b in zip(pts, pts[1:]):
            self.cum.append(self.cum[-1] + lunghezza(sub(b, a)))

    @property
    def lunghezza(self) -> float:
        return self.cum[-1]

    def _segmento(self, s: float) -> tuple[int, float]:
        s = max(0.0, min(self.lunghezza, s))
        lo, hi = 0, len(self.cum) - 1
        while hi - lo > 1:
            mid = (lo + hi) // 2
            if self.cum[mid] <= s:
                lo = mid
            else:
                hi = mid
        seg = self.cum[hi] - self.cum[lo]
        return lo, (s - self.cum[lo]) / seg if seg > 1e-12 else 0.0

    def punto(self, u: float) -> Vec:
        """Punto alla frazione ``u`` (0..1) della lunghezza totale."""
        i, t = self._segmento(u * self.lunghezza)
        return lerp(self.punti[i], self.punti[i + 1], t)  # type: ignore[return-value]

    def tangente(self, u: float) -> Vec:
        i, _ = self._segmento(u * self.lunghezza)
        d = sub(self.punti[i + 1], self.punti[i])
        if lunghezza(d) < 1e-12 and i > 0:
            d = sub(self.punti[i], self.punti[i - 1])
        return normalizza(d)


def campiona_percorso(percorso_spec: dict, f: float, fps: int = 24) -> tuple[Vec, float, float]:
    """Posizione, yaw (radianti) e distanza percorsa al frame ``f``.

    ``percorso_spec``: {"points": [...], "start": f0, "end": f1, "ease", "smooth", "orient"}
    (start/end possono essere dati anche in secondi con "start_t"/"end_t").
    """
    p = Percorso(percorso_spec["points"], percorso_spec.get("smooth", True))
    f0 = percorso_spec.get("start", 0)
    f1 = percorso_spec.get("end", f0 + 1)
    u = progresso(f, f0, f1, percorso_spec.get("ease", "linear"))
    pos = p.punto(u)
    tan = p.tangente(min(u, 0.999999))
    yaw = yaw_da_direzione(tan[0], tan[1]) if math.hypot(tan[0], tan[1]) > 1e-9 else 0.0
    return pos, yaw, u * p.lunghezza


def distanze_cumulate(posizioni: Sequence[Sequence[float]], avanti: Sequence[Sequence[float]] | None = None) -> list[float]:
    """Distanza percorsa (con segno se si passa ``avanti``) fotogramma per fotogramma.

    Serve per far girare le ruote e cadenzare la camminata anche quando
    l'oggetto e' animato con keyframe invece che con un percorso.
    """
    out = [0.0]
    for i in range(1, len(posizioni)):
        d = sub(posizioni[i], posizioni[i - 1])
        passo = math.hypot(d[0], d[1])
        if avanti is not None and passo > 1e-9:
            a = avanti[i]
            if d[0] * a[0] + d[1] * a[1] < 0:
                passo = -passo
        out.append(out[-1] + passo)
    return out


def avanti_da_yaw(yaw: float) -> Vec:
    """Vettore fronte (-Y ruotato di ``yaw`` attorno a Z)."""
    return (math.sin(yaw), -math.cos(yaw), 0.0)


# ---------------------------------------------------------------------------
# Rumore morbido (micro-mosso a mano)
# ---------------------------------------------------------------------------


def rumore(t: float, seme: int = 0, ottave: int = 3) -> float:
    """Rumore deterministico e continuo in [-1, 1] come somma di sinusoidi."""
    tot, amp, norm = 0.0, 1.0, 0.0
    for o in range(ottave):
        k = seme * 7.31 + o * 3.17
        fr = (1.0 + o * 1.93) * (1.0 + 0.11 * math.sin(k))
        tot += amp * math.sin(t * fr * 2 * math.pi + k * 1.7) * math.cos(t * fr * 1.3 + k)
        norm += amp
        amp *= 0.5
    return tot / norm


def mosso_a_mano(f: float, cfg: dict, fps: int = 24) -> tuple[Vec, Vec]:
    """Offset di posizione (m) e rotazione (gradi) del micro-mosso al frame ``f``."""
    t = f / fps * cfg.get("frequency", 1.0)
    a = cfg.get("amplitude", 0.015)
    r = cfg.get("rotation", 0.35)
    s = int(cfg.get("seed", 1))
    loc = (a * rumore(t, s), a * 0.6 * rumore(t, s + 11), a * rumore(t, s + 23))
    rot = (r * rumore(t, s + 37), r * 0.5 * rumore(t, s + 41), r * rumore(t, s + 53))
    return loc, rot


# ---------------------------------------------------------------------------
# Camera
# ---------------------------------------------------------------------------

Risolutore = Callable[[str, float], Vec]


def risolvi_punto(valore, f: float, risolvi: Risolutore | None) -> Vec | None:
    """Converte un bersaglio (lista, nome oggetto o {object, offset}) in coordinate."""
    if valore is None:
        return None
    if isinstance(valore, str):
        if risolvi is None:
            raise ValueError(f"serve un risolutore per l'oggetto {valore!r}")
        return risolvi(valore, f)
    if isinstance(valore, dict):
        base = risolvi_punto(valore["object"], f, risolvi)
        return add(base, valore.get("offset", (0, 0, 0)))  # type: ignore[arg-type]
    return tuple(float(c) for c in valore)  # type: ignore[return-value]


def _applica_movimento(m: dict, f: float, loc: Vec, tgt: Vec, lens: float, roll: float,
                       risolvi: Risolutore | None, totale: int):
    tipo = m["type"]
    u = progresso(f, m.get("start", 0), m.get("end", totale - 1), m.get("ease", "in_out"))
    vista = normalizza(sub(tgt, loc))
    destra = normalizza(croce(vista, (0, 0, 1))) if abs(vista[2]) < 0.999 else (1.0, 0.0, 0.0)
    if tipo == "static":
        pass
    elif tipo in ("dolly_in", "dolly_out"):
        d = m.get("distance", 1.0) * (1 if tipo == "dolly_in" else -1)
        # anche il bersaglio avanza: il dolly cambia la distanza, non la direzione di sguardo
        delta = mul(vista, d * u)
        loc, tgt = add(loc, delta), add(tgt, delta)
    elif tipo == "truck":
        delta = mul(destra, m.get("distance", 1.0) * u)
        loc = add(loc, delta)
        if not m.get("keep_target", False):
            tgt = add(tgt, delta)
    elif tipo == "pedestal":
        delta = (0.0, 0.0, m.get("distance", 0.5) * u)
        loc = add(loc, delta)
        if not m.get("keep_target", False):
            tgt = add(tgt, delta)
    elif tipo == "pan":
        tgt = ruota_z(tgt, math.radians(m.get("angle", 20.0)) * u, loc)
    elif tipo == "tilt":
        v = sub(tgt, loc)
        tgt = add(loc, ruota_asse(v, destra, math.radians(m.get("angle", 10.0)) * u))
    elif tipo == "orbit":
        centro = risolvi_punto(m.get("center"), f, risolvi) or tgt
        loc = ruota_z(loc, math.radians(m.get("angle", 30.0)) * u, centro)
        loc = add(loc, (0.0, 0.0, m.get("height", 0.0) * u))
    elif tipo in ("crane_up", "crane_down"):
        h = m.get("height", 1.0) * (1 if tipo == "crane_up" else -1)
        loc = add(loc, (0.0, 0.0, h * u))
        if not m.get("keep_target", True):
            tgt = add(tgt, (0.0, 0.0, h * u))
    elif tipo == "tracking":
        bersaglio = risolvi_punto(m["target"], f, risolvi)
        assert bersaglio is not None
        off = m.get("offset", (0.0, -4.0, 1.2))
        loc = add(bersaglio, off)
        tgt = add(bersaglio, m.get("look_offset", (0.0, 0.0, 1.0)))
    elif tipo == "zoom":
        lens = lens + (m.get("lens_end", lens * 1.5) - lens) * u
    elif tipo == "dolly_zoom":
        # vertigo: la camera si avvicina e la focale si accorcia mantenendo il soggetto
        d0 = lunghezza(sub(tgt, loc))
        dist = m.get("distance", 1.0) * u
        d1 = max(0.05, d0 - dist)
        loc = add(loc, mul(vista, d0 - d1))
        lens = lens * d1 / d0
    elif tipo == "roll":
        roll = roll + m.get("angle", 5.0) * u
    else:  # pragma: no cover - la validazione lo impedisce
        raise ValueError(f"movimento camera sconosciuto: {tipo}")
    return loc, tgt, lens, roll


def campiona_camera(cam: dict, frames: int, risolvi: Risolutore | None = None, fps: int = 24) -> list[dict]:
    """Calcola posa e ottica della camera per ogni frame 0..frames-1.

    Ritorna una lista di dict {location, rotation (radianti, Euler XYZ), lens,
    focus_distance (o None)}. Ordine di applicazione: chiavi (o posa base),
    movimenti preset in sequenza, micro-mosso.
    """
    out = []
    chiavi = cam.get("keys") or []
    movimenti = cam.get("moves") or []
    hh = cam.get("handheld")
    for f in range(frames):
        loc = campiona_chiavi(chiavi, "location", f, cam.get("location"), fps)
        loc = tuple(float(c) for c in loc)
        rot_fissa = campiona_chiavi(chiavi, "rotation", f, cam.get("rotation"), fps)
        tgt = _look_at_chiavi(chiavi, f, cam, risolvi, fps)
        lens = float(campiona_chiavi(chiavi, "lens", f, cam.get("lens", 35.0), fps))
        roll = float(campiona_chiavi(chiavi, "roll", f, cam.get("roll", 0.0), fps))
        fuoco = campiona_chiavi(chiavi, "focus_distance", f, None, fps)
        if tgt is None:
            # niente look_at: ricaviamo un bersaglio dalla rotazione (default: orizzontale verso +Y)
            r = [math.radians(a) for a in (rot_fissa or (90.0, 0.0, 0.0))]
            dirz = (0.0, 0.0, -1.0)
            dirz = ruota_asse(dirz, (1, 0, 0), r[0])
            dirz = ruota_asse(dirz, (0, 1, 0), r[1])
            dirz = ruota_asse(dirz, (0, 0, 1), r[2])
            tgt = add(loc, mul(dirz, 5.0))
            if not movimenti and not hh:
                out.append({"location": loc, "rotation": tuple(r), "lens": lens,
                            "focus_distance": fuoco, "target": tgt})
                continue
        for m in movimenti:
            loc, tgt, lens, roll = _applica_movimento(m, f, loc, tgt, lens, roll, risolvi, frames)
        rot = list(look_at_euler(loc, tgt, roll))
        if hh:
            dl, dr = mosso_a_mano(f, hh, fps)
            loc = add(loc, dl)
            rot = [rot[i] + math.radians(dr[i]) for i in range(3)]
        out.append({"location": loc, "rotation": tuple(rot), "lens": lens,
                    "focus_distance": fuoco, "target": tgt})
    # continuita' degli angoli (niente salti di 360 gradi tra fotogrammi)
    for asse in range(3):
        serie = srotola([o["rotation"][asse] for o in out])
        for o, v in zip(out, serie):
            r = list(o["rotation"])
            r[asse] = v
            o["rotation"] = tuple(r)
    return out


def _look_at_chiavi(chiavi, f, cam, risolvi, fps) -> Vec | None:
    """Bersaglio al frame ``f``: risolve oggetti/coordinate delle chiavi e interpola."""
    risolte = []
    for k in chiavi:
        if "look_at" in k:
            kk = dict(k)
            kk["look_at"] = risolvi_punto(k["look_at"], f, risolvi)
            risolte.append(kk)
    if risolte:
        return tuple(campiona_chiavi(risolte, "look_at", f, None, fps))  # type: ignore[return-value]
    return risolvi_punto(cam.get("look_at"), f, risolvi)


# ---------------------------------------------------------------------------
# Oggetti
# ---------------------------------------------------------------------------


def campiona_oggetto(obj: dict, frames: int, fps: int = 24) -> list[dict] | None:
    """Trasformazioni per frame di un oggetto animato (None se statico).

    Ritorna per ogni frame {location, rotation (gradi), scale, distance} dove
    ``distance`` e' la strada percorsa lungo il fronte (per ruote e passi).
    """
    chiavi = obj.get("keys") or []
    perc = obj.get("path")
    if not chiavi and not perc:
        return None
    base_loc = tuple(obj.get("location", (0, 0, 0)))
    base_rot = tuple(obj.get("rotation", (0, 0, 0)))
    sc = obj.get("scale", 1.0)
    base_sc = (sc, sc, sc) if isinstance(sc, (int, float)) else tuple(sc)
    out = []
    dist_perc = []
    for f in range(frames):
        loc = tuple(campiona_chiavi(chiavi, "location", f, base_loc, fps))
        rot = tuple(campiona_chiavi(chiavi, "rotation", f, base_rot, fps))
        s = campiona_chiavi(chiavi, "scale", f, base_sc, fps)
        s = (s, s, s) if isinstance(s, (int, float)) else tuple(s)
        if perc:
            pos, yaw, dist = campiona_percorso(perc, f, fps)
            loc = add(pos, perc.get("offset", (0, 0, 0)))
            if perc.get("orient", True):
                rot = (rot[0], rot[1], math.degrees(yaw) + perc.get("yaw_offset", 0.0))
            dist_perc.append(dist)
        out.append({"location": loc, "rotation": rot, "scale": s})
    # continuita' dello yaw
    serie = srotola([math.radians(o["rotation"][2]) for o in out])
    for o, v in zip(out, serie):
        o["rotation"] = (o["rotation"][0], o["rotation"][1], math.degrees(v))
    if perc:
        dist = dist_perc
    else:
        avanti = [avanti_da_yaw(math.radians(o["rotation"][2])) for o in out]
        dist = distanze_cumulate([o["location"] for o in out], avanti)
    for o, d in zip(out, dist):
        o["distance"] = d
    return out


# ---------------------------------------------------------------------------
# Manichino: pose e camminata
# ---------------------------------------------------------------------------

GIUNTI = (
    "root", "pelvis", "spine", "neck", "head",
    "shoulder_l", "elbow_l", "wrist_l", "shoulder_r", "elbow_r", "wrist_r",
    "hip_l", "knee_l", "ankle_l", "hip_r", "knee_r", "ankle_r",
)

# Angoli in gradi (Euler XYZ locali). Arti a riposo pendono lungo -Z.
# X negativo porta un arto in avanti (verso -Y); per le braccia Y negativo apre
# il braccio sinistro (+X) verso l'esterno, Y positivo apre il destro.
POSE: dict[str, dict] = {
    "standing": {
        "joints": {"shoulder_l": (2, -7, 0), "shoulder_r": (2, 7, 0),
                   "elbow_l": (-6, 0, 0), "elbow_r": (-6, 0, 0)},
    },
    "walking": {
        "joints": {"shoulder_l": (0, -6, 0), "shoulder_r": (0, 6, 0),
                   "elbow_l": (-12, 0, 0), "elbow_r": (-12, 0, 0)},
    },
    "sitting_chair": {
        "pelvis_drop": 0.42,
        "joints": {"hip_l": (-90, -4, 0), "hip_r": (-90, 4, 0), "knee_l": (90, 0, 0), "knee_r": (90, 0, 0),
                   "shoulder_l": (-25, -6, 0), "shoulder_r": (-25, 6, 0),
                   "elbow_l": (-45, 0, 0), "elbow_r": (-45, 0, 0)},
    },
    "sitting_seiza": {
        "pelvis_drop": 0.62,
        "joints": {"hip_l": (-55, -3, 0), "hip_r": (-55, 3, 0), "knee_l": (145, 0, 0), "knee_r": (145, 0, 0),
                   "ankle_l": (40, 0, 0), "ankle_r": (40, 0, 0),
                   "shoulder_l": (-28, 2, 0), "shoulder_r": (-28, -2, 0),
                   "elbow_l": (-50, 0, -10), "elbow_r": (-50, 0, 10)},
    },
    "driving": {
        "pelvis_drop": 0.47,
        "joints": {"spine": (-12, 0, 0), "hip_l": (-75, -6, 0), "hip_r": (-75, 6, 0),
                   "knee_l": (65, 0, 0), "knee_r": (65, 0, 0),
                   "shoulder_l": (-68, -14, 0), "shoulder_r": (-68, 14, 0),
                   "elbow_l": (-28, 0, 0), "elbow_r": (-28, 0, 0)},
    },
    "hand_raise": {
        "joints": {"shoulder_l": (2, -7, 0), "elbow_l": (-6, 0, 0),
                   "shoulder_r": (-130, 25, 0), "elbow_r": (-115, 0, 0)},
    },
    "turning_head": {
        "joints": {"spine": (0, 0, 12), "head": (0, 0, 48), "shoulder_l": (2, -7, 0), "shoulder_r": (2, 7, 0),
                   "elbow_l": (-6, 0, 0), "elbow_r": (-6, 0, 0)},
    },
    "holding_umbrella": {
        "joints": {"shoulder_l": (2, -7, 0), "elbow_l": (-6, 0, 0),
                   "shoulder_r": (-35, 12, 0), "elbow_r": (-80, 0, 0)},
    },
    "arms_front": {
        "joints": {"shoulder_l": (-20, 4, 0), "shoulder_r": (-20, -4, 0),
                   "elbow_l": (-70, 0, -15), "elbow_r": (-70, 0, 15)},
    },
    "looking_up": {
        "joints": {"head": (28, 0, 0), "shoulder_l": (2, -7, 0), "shoulder_r": (2, 7, 0)},
    },
    "t_pose": {"joints": {"shoulder_l": (0, -90, 0), "shoulder_r": (0, 90, 0)}},
}


def posa(nome_o_giunti, extra: dict | None = None) -> dict:
    """Restituisce {"joints": {...}, "pelvis_drop": m} risolvendo un preset."""
    if isinstance(nome_o_giunti, str):
        base = POSE[nome_o_giunti]
        res = {"joints": dict(base["joints"]), "pelvis_drop": base.get("pelvis_drop", 0.0)}
    else:
        res = {"joints": dict(nome_o_giunti or {}), "pelvis_drop": 0.0}
    for k, v in (extra or {}).items():
        res["joints"][k] = tuple(v)
    return res


def angolo_giunto(p: dict, nome: str) -> Vec:
    return tuple(p["joints"].get(nome, (0.0, 0.0, 0.0)))  # type: ignore[return-value]


def ciclo_camminata(fase: float, ampiezza: float = 1.0) -> dict:
    """Offset dei giunti (gradi) e saltello del bacino per una fase in radianti.

    Una fase di 2*pi corrisponde a due passi (sinistro + destro).
    """
    s = math.sin(fase)
    a = ampiezza
    g = {
        "hip_l": (-24 * a * s, 0, 0),
        "hip_r": (24 * a * s, 0, 0),
        "knee_l": (max(0.0, 38 * a * math.sin(fase + 1.9)), 0, 0),
        "knee_r": (max(0.0, 38 * a * math.sin(fase + 1.9 + math.pi)), 0, 0),
        "ankle_l": (8 * a * math.sin(fase + 0.6), 0, 0),
        "ankle_r": (8 * a * math.sin(fase + 0.6 + math.pi), 0, 0),
        "shoulder_l": (18 * a * s, 0, 0),
        "shoulder_r": (-18 * a * s, 0, 0),
        "elbow_l": (-10 * a * max(0.0, s), 0, 0),
        "elbow_r": (-10 * a * max(0.0, -s), 0, 0),
        "spine": (0, 0, 4 * a * s),
        "pelvis": (0, 0, -3 * a * s),
    }
    saltello = 0.02 * a * abs(math.cos(fase))
    return {"joints": g, "bob": saltello}


def somma_giunti(a: dict, b: dict) -> dict:
    out = dict(a)
    for k, v in b.items():
        base = out.get(k, (0.0, 0.0, 0.0))
        out[k] = (base[0] + v[0], base[1] + v[1], base[2] + v[2])
    return out


def campiona_pose(obj: dict, frames: int, distanze: Sequence[float] | None, fps: int = 24) -> list[dict]:
    """Pose per frame di un manichino: preset/chiavi di posa + camminata."""
    base = posa(obj.get("pose", "standing"), obj.get("joints"))
    chiavi_posa = []
    for k in obj.get("pose_keys") or []:
        p = posa(k.get("pose", obj.get("pose", "standing")), k.get("joints"))
        chiavi_posa.append((frame_di(k, fps), p, k.get("ease", "in_out")))
    chiavi_posa.sort(key=lambda c: c[0])
    walk = obj.get("walk")
    out = []
    for f in range(frames):
        p = base
        if chiavi_posa:
            if f <= chiavi_posa[0][0]:
                p = chiavi_posa[0][1]
            elif f >= chiavi_posa[-1][0]:
                p = chiavi_posa[-1][1]
            else:
                for (f0, p0, _), (f1, p1, e1) in zip(chiavi_posa, chiavi_posa[1:]):
                    if f0 <= f <= f1:
                        u = progresso(f, f0, f1, e1)
                        nomi = set(p0["joints"]) | set(p1["joints"])
                        p = {"joints": {n: lerp(angolo_giunto(p0, n), angolo_giunto(p1, n), u) for n in nomi},
                             "pelvis_drop": lerp(p0["pelvis_drop"], p1["pelvis_drop"], u)}
                        break
        giunti = dict(p["joints"])
        bob = 0.0
        if walk:
            cfg = walk if isinstance(walk, dict) else {}
            passo = cfg.get("stride", 0.7)
            if distanze is not None and cfg.get("cadence") is None and abs(distanze[-1] - distanze[0]) > 1e-6:
                fase = math.pi * distanze[f] / passo
            else:
                fase = math.pi * cfg.get("cadence", 1.8) * f / fps
            fase += cfg.get("phase", 0.0)
            c = ciclo_camminata(fase, cfg.get("amplitude", 1.0))
            giunti = somma_giunti(giunti, c["joints"])
            bob = c["bob"]
        out.append({"joints": giunti, "pelvis_drop": p["pelvis_drop"], "bob": bob})
    return out


def range_frames(testo: str | None, totale: int) -> tuple[int, int]:
    """Interpreta "a-b" (estremi inclusi, base 0) limitandolo alla durata dello shot."""
    if not testo:
        return 0, totale - 1
    parti = str(testo).split("-")
    if len(parti) == 1:
        a = b = int(parti[0])
    elif len(parti) == 2:
        a, b = int(parti[0]), int(parti[1])
    else:
        raise ValueError(f"intervallo frame non valido: {testo!r} (atteso a-b)")
    if a < 0 or b < a or b >= totale:
        raise ValueError(f"intervallo frame {testo!r} fuori dallo shot (0-{totale - 1})")
    return a, b


def risoluzione(testo: str) -> tuple[int, int]:
    """Interpreta "WxH" in una coppia di interi pari (requisito di H.264 yuv420p)."""
    try:
        w, h = (int(x) for x in str(testo).lower().split("x"))
    except ValueError as exc:
        raise ValueError(f"risoluzione non valida: {testo!r} (atteso WxH)") from exc
    if w < 16 or h < 16:
        raise ValueError(f"risoluzione troppo piccola: {testo!r}")
    return w - w % 2, h - h % 2


def iter_frame(a: int, b: int) -> Iterable[int]:
    return range(a, b + 1)
