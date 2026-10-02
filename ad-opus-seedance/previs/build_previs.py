#!/usr/bin/env python3
"""build_previs.py - procedural grey-box Blender previs of the whole ad timeline.

Reads ../shotlist.json (single source of truth), builds in bpy a flat-shaded
grey-box version of every shot (coupe, mannequin, garage / highway / tunnel /
booth), animates each camera with keyframes from the shot's "previs" block
(cam_from -> cam_to over the shot, aimed at look_at through a Track-To empty)
and renders the 15 s / 24 fps timeline with BLENDER_WORKBENCH (viewport solid
mode look: STUDIO light, single grey, darker floor, no outlines, no UI).

Run with the bpy-capable interpreter, e.g.
  <venv>/bin/python previs/build_previs.py                       # full render -> out/previs.mp4
  <venv>/bin/python previs/build_previs.py --shots S04,S05 --scale 25 --out /tmp/t.mp4

Optional keys inside a shot's "previs" block (all have defaults, see RECIPES):
  look_at_to [x,y,z]   look target moves look_at -> look_at_to
  lens_mm / lens_to_mm focal length (sensor 36 mm) / zoom target
  speed                convoy speed in m/s: car + camera + target travel along +Y
                       (cam_from/cam_to/look_at are then RELATIVE to the car)
  handheld             camera shake amplitude in metres (0 = off); also adds a small roll wobble
                       (HANDHELD_ROLL_DEG_PER_M degrees of roll per metre of amplitude)
  flash [s,...]        camera-flash cue: one bright frame (+FLASH_EV exposure) at each time (seconds
                       from the start of the shot) followed by a half-strength decay frame
  car_pos [x,y,z], car_yaw (deg), car_path [[x,y,z],...], car_ease (exponent)
  figure_path [[x,y,z],[x,y,z]], figure_action (walk|flick|poses|lean|stand),
  figure_yaw (deg)
All coordinates are relative to the shot's own world origin (shots live in
separate worlds 1000 m apart, so they never see each other).

Camera aiming: a Track-To constraint on a look-at empty, except where that would be wrong -
  * zenith crossing (e.g. the S09 top-down shot whose aim passes straight down): Track-To flips its
    roll by 180 degrees exactly at the zenith, so the camera gets roll-free per-frame rotation keys
    (heading fixed at the first frame's aim, pitch swept through straight-down);
  * handheld shots: per-frame rotation keys too, so a roll wobble can be added.
Run with --encode-only to re-encode the whole timeline from an existing frames dir after
re-rendering a single shot with --shots SXX --frames-only.
"""
import argparse
import json
import math
import os
import random
import shutil
import struct
import subprocess
import sys
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROJECT = HERE.parent
DEFAULT_SHOTLIST = PROJECT / "shotlist.json"
DEFAULT_OUT = PROJECT / "out" / "previs.mp4"
DEFAULT_FRAMES = Path(os.environ.get("PREVIS_FRAMES_DIR") or (Path(tempfile.gettempdir()) / "previs_frames"))


def parse_args(argv=None):
    ap = argparse.ArgumentParser(
        description="Procedural Blender grey-box previs of the ad timeline (BLENDER_WORKBENCH, 24 fps).",
        epilog="Needs the interpreter that has bpy (Blender as a module) + ffmpeg on PATH.")
    ap.add_argument("--shotlist", default=str(DEFAULT_SHOTLIST), help="shot list json (default: ../shotlist.json)")
    ap.add_argument("--shots", default="", help="comma separated subset, e.g. S01,S02 (default: all)")
    ap.add_argument("--scale", type=float, default=100.0,
                    help="render resolution in percent of 1280x720 (default 100; use 25 for quick tests)")
    ap.add_argument("--frames-only", action="store_true", help="render the PNG sequence only, skip the mp4 encode")
    ap.add_argument("--encode-only", action="store_true",
                    help="build/render nothing: encode ALL shots' frames already in --frames-dir to the output mp4 "
                         "(out/previs.mp4 unless --out); use after re-rendering single shots with --shots X --frames-only")
    ap.add_argument("--out", default="", help="output mp4 (default: out/previs.mp4 for a full 100%% run, "
                                              "otherwise <frames-dir>/../previs_partial.mp4)")
    ap.add_argument("--frames-dir", default=str(DEFAULT_FRAMES),
                    help="where the PNG sequence f_0000.png.. is kept (default: $PREVIS_FRAMES_DIR or <tmp>/previs_frames)")
    ap.add_argument("--grey", type=float, default=0.66,
                    help="object colour (sRGB grey) of the main geometry; with Workbench STUDIO shading 0.66 renders "
                         "as the ~0.42 mid-grey of a Blender viewport (default 0.66)")
    ap.add_argument("--aa", default="8", choices=["OFF", "FXAA", "5", "8", "11", "16", "32"], help="workbench AA samples")
    ap.add_argument("--crf", type=int, default=16, help="x264 crf (default 16)")
    ap.add_argument("--save-blend", default="", help="also save the built scene as .blend for inspection")
    ap.add_argument("--no-render", action="store_true", help="build the scene only (use with --save-blend)")
    ap.add_argument("--list", action="store_true", help="print the frame ranges of the shots and exit")
    return ap.parse_args(argv)


if __name__ == "__main__":
    ARGS = parse_args()

import bpy  # noqa: E402
from mathutils import Euler, Matrix, Vector  # noqa: E402

# --------------------------------------------------------------------------------------
# constants
# --------------------------------------------------------------------------------------
ENV_X = {"garage": 0.0, "highway": 1000.0, "tunnel": 2000.0, "booth": 3000.0}   # env offset in X (m)
SHOT_Y_STEP = 1000.0                                                              # repeated env -> offset in Y
WHEEL_R = 0.33
HIP_Z = 0.92
SEAT_Z = 0.55
TAIL_X, TAIL_Z, TAIL_Y = 0.56, 0.74, -2.275     # TAIL_Y = outer surface of the round taillight (rear panel at -2.2)
ZENITH_TOL = 0.08                  # (horizontal aim distance / drop) below which the aim counts as "straight down"
HANDHELD_ROLL_DEG_PER_M = 12.0     # handheld roll wobble: degrees per metre of handheld amplitude (0.05 m -> 0.6 deg)
FLASH_EV = (2.0, 0.7)              # exposure (EV) of a camera-flash frame and of the decay frame after it
WALL_LAMP_Z = 2.0                  # tunnel wall lamp height (m): just above the hood line of sight of the S08 wheel shot

# display greys (what you see on screen); converted to linear for object.color
PAL = dict(
    body=1.00, glass=0.80, floor=0.86, ground=0.72, ceiling=0.78, line=1.30, dark=0.48, light=1.45,
    spoke=1.25, tire=0.52, bg=0.065,
)

# Per-shot defaults (all overridable from shotlist previs{} with the same key names).
RECIPES = {
    "S01": dict(lens=32, car="at_lookat", flicker=True),
    "S02": dict(lens=50, car="at_lookat"),
    "S03": dict(lens=30, car="at_lookat", taillight="ignite_quick",
                figure=dict(action="walk", path=[[-1.2, 13.0, 0.0], [-1.2, 11.4, 0.0]], appear=0.35)),
    "S04": dict(lens=32, car="pos:1.7,1.2", handheld=0.05, figure=dict(action="walk")),
    "S05": dict(lens=70, car="pos:1.5,3.0", figure=dict(action="flick")),
    "S06": dict(lens=40, car="macro_taillight", taillight="ignite"),
    "S07": dict(lens=32, car="origin", speed=26.0),
    "S08": dict(lens=45, car="wheel_at_lookat", speed=26.0),
    "S09": dict(lens=22, car="at_lookat", speed=26.0),
    "S10": dict(lens=42, car="none", figure=dict(action="poses", seated=True),
                flash=(0.18, 0.57, 0.95)),     # camera flashes in the middle of the three pose changes
    "S11": dict(lens=30, car="at_lookat", flame=True, figure=dict(action="lean")),
    "S12": dict(lens=32, car="path", ease=2.0),
}


# --------------------------------------------------------------------------------------
# small helpers
# --------------------------------------------------------------------------------------
def s2l(c):
    """sRGB display value -> linear."""
    c = max(0.0, min(1.0, c))
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


class Style:
    grey = 0.66

    @classmethod
    def col(cls, key_or_val):
        v = PAL[key_or_val] * cls.grey if key_or_val in PAL and key_or_val != "bg" else (
            PAL["bg"] if key_or_val == "bg" else key_or_val)
        v = min(v, 0.98)
        l = s2l(v)
        return (l, l, l, 1.0)


def rnd(x):
    return int(math.floor(x + 0.5 + 1e-9))


def _iter_fcurves():
    """(owner name, fcurve) for every animated object / scene (slotted actions of Blender >= 4.4 and legacy)."""
    for idb in list(bpy.data.objects) + list(bpy.data.scenes):
        ad = getattr(idb, "animation_data", None)
        if not ad or not ad.action:
            continue
        act = ad.action
        if hasattr(act, "layers"):
            fcs = [fc for layer in act.layers for strip in layer.strips
                   for cb in strip.channelbags for fc in cb.fcurves]
        else:
            fcs = list(act.fcurves)
        for fc in fcs:
            yield idb.name, fc


def _key_id(owner, fc, k):
    return (owner, fc.data_path, fc.array_index, round(k.co[0], 4))


_FORCED_KEYS = set()


@contextmanager
def interp(kind):
    """Interpolation for keyframes inserted inside the block.

    keyframe_new_interpolation_type has no effect in Blender 5 (new keys always come out BEZIER), so the keys
    that appear during the block are found by diffing a snapshot and set explicitly. A key already set by an
    inner block keeps the inner kind."""
    pref = bpy.context.preferences.edit
    old = pref.keyframe_new_interpolation_type
    pref.keyframe_new_interpolation_type = kind
    before = {_key_id(n, fc, k) for n, fc in _iter_fcurves() for k in fc.keyframe_points}
    try:
        yield
    finally:
        pref.keyframe_new_interpolation_type = old
        for n, fc in _iter_fcurves():
            for k in fc.keyframe_points:
                kid = _key_id(n, fc, k)
                if kid not in before and kid not in _FORCED_KEYS:
                    k.interpolation = kind
                    _FORCED_KEYS.add(kid)


@contextmanager
def quiet():
    """Silence C-level stdout/stderr (Blender render progress, EGL warnings)."""
    sys.stdout.flush()
    sys.stderr.flush()
    s1, s2 = os.dup(1), os.dup(2)
    dn = os.open(os.devnull, os.O_WRONLY)
    os.dup2(dn, 1)
    os.dup2(dn, 2)
    try:
        yield
    finally:
        os.dup2(s1, 1)
        os.dup2(s2, 2)
        for fd in (s1, s2, dn):
            os.close(fd)


def lerp(a, b, t):
    return [a[i] + (b[i] - a[i]) * t for i in range(len(a))]


# --------------------------------------------------------------------------------------
# geometry builder: accumulate boxes / cylinders / spheres / prisms into one mesh
# --------------------------------------------------------------------------------------
AXIS = {"z": lambda p: p, "x": lambda p: (p[2], p[0], p[1]), "y": lambda p: (p[1], p[2], p[0])}


class Geo:
    def __init__(self):
        self.verts, self.faces, self.smooth = [], [], []

    def add(self, verts, faces, smooth=False):
        o = len(self.verts)
        self.verts.extend(tuple(v) for v in verts)
        for f in faces:
            self.faces.append([i + o for i in f])
            self.smooth.append(smooth)

    @staticmethod
    def xf(pts, c, rot=None):
        if rot is None:
            return [(p[0] + c[0], p[1] + c[1], p[2] + c[2]) for p in pts]
        m = Euler([math.radians(a) for a in rot], "XYZ").to_matrix()
        cv = Vector(c)
        return [tuple(m @ Vector(p) + cv) for p in pts]

    def box(self, c, s, rot=None):
        hx, hy, hz = s[0] / 2, s[1] / 2, s[2] / 2
        pts = [(-hx, -hy, -hz), (hx, -hy, -hz), (hx, hy, -hz), (-hx, hy, -hz),
               (-hx, -hy, hz), (hx, -hy, hz), (hx, hy, hz), (-hx, hy, hz)]
        faces = [(0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4), (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7)]
        self.add(self.xf(pts, c, rot), faces)

    def cyl(self, c, r, h, axis="z", seg=16, r_top=None, sxy=(1.0, 1.0), caps=True, smooth=True, rot=None):
        rt = r if r_top is None else r_top
        ring = [(math.cos(2 * math.pi * i / seg), math.sin(2 * math.pi * i / seg)) for i in range(seg)]
        fx = AXIS[axis]
        bot = [(r * sxy[0] * x, r * sxy[1] * y, -h / 2) for x, y in ring]
        if rt <= 1e-9:
            pts = [fx(p) for p in bot] + [fx((0, 0, h / 2))]
            faces = [(i, (i + 1) % seg, seg) for i in range(seg)]
            self.add(self.xf(pts, c, rot), faces, smooth)
        else:
            top = [(rt * sxy[0] * x, rt * sxy[1] * y, h / 2) for x, y in ring]
            pts = [fx(p) for p in bot + top]
            faces = [(i, (i + 1) % seg, seg + (i + 1) % seg, seg + i) for i in range(seg)]
            self.add(self.xf(pts, c, rot), faces, smooth)
            if caps:
                self.add(self.xf([fx(p) for p in top], c, rot), [tuple(range(seg))], False)
        if caps:
            self.add(self.xf([fx(p) for p in bot], c, rot), [tuple(reversed(range(seg)))], False)

    def sphere(self, c, r, seg=16, rings=10, s=(1.0, 1.0, 1.0)):
        pts = [(0, 0, r * s[2])]
        for j in range(1, rings):
            th = math.pi * j / rings
            for i in range(seg):
                ph = 2 * math.pi * i / seg
                pts.append((r * s[0] * math.sin(th) * math.cos(ph), r * s[1] * math.sin(th) * math.sin(ph),
                            r * s[2] * math.cos(th)))
        pts.append((0, 0, -r * s[2]))
        faces = [(0, 1 + i, 1 + (i + 1) % seg) for i in range(seg)]
        for j in range(rings - 2):
            a, b = 1 + j * seg, 1 + (j + 1) * seg
            for i in range(seg):
                faces.append((a + i, b + i, b + (i + 1) % seg, a + (i + 1) % seg))
        last, base = len(pts) - 1, 1 + (rings - 2) * seg
        faces += [(last, base + (i + 1) % seg, base + i) for i in range(seg)]
        self.add(self.xf(pts, c), faces, True)

    def lathe(self, prof, c, seg=14, rot=None):
        """solid of revolution about +z: prof = [(z, r), ...] from the base to the tip (r = 0 at the tip is fine)."""
        ring = [(math.cos(2 * math.pi * i / seg), math.sin(2 * math.pi * i / seg)) for i in range(seg)]
        pts, faces = [], []
        for z, r in prof:
            pts.extend((r * x, r * y, z) for x, y in ring)
        for j in range(len(prof) - 1):
            a, b = j * seg, (j + 1) * seg
            for i in range(seg):
                faces.append((a + i, a + (i + 1) % seg, b + (i + 1) % seg, b + i))
        self.add(self.xf(pts, c, rot), faces, False)

    def rrect_y(self, x0, x1, z0, z1, r, y, th, seg=8):
        """rounded-rectangle plate in the xz plane (x right, z up seen from -Y), thickness th along y centred at y;
        the visible face looks toward -Y (the camera behind the car)."""
        r = max(1e-4, min(r, (x1 - x0) / 2, (z1 - z0) / 2))
        pts = []
        for (cx, cz, a0) in ((x1 - r, z0 + r, -90.0), (x1 - r, z1 - r, 0.0), (x0 + r, z1 - r, 90.0), (x0 + r, z0 + r, 180.0)):
            for i in range(seg + 1):
                a = math.radians(a0 + 90.0 * i / seg)
                pts.append((cx + r * math.cos(a), cz + r * math.sin(a)))          # counter-clockwise in (x, z)
        n = len(pts)
        front = [(px, y - th / 2, pz) for px, pz in pts]
        back = [(px, y + th / 2, pz) for px, pz in pts]
        faces = [tuple(range(n)), tuple(reversed(range(n, 2 * n)))]
        faces += [(i, n + i, n + (i + 1) % n, (i + 1) % n) for i in range(n)]
        self.add(front + back, faces)

    def prism_x(self, pts_yz, xc, w, taper=None):
        """polygon in (y,z) (CCW seen from +x) extruded along x, centred at xc, width w.
        taper=(z0, z1, w1): width goes linearly from w (z<=z0) to w1 (z>=z1)."""
        n = len(pts_yz)

        def hw(z):
            if taper is None:
                return w / 2
            z0, z1, w1 = taper
            t = min(1.0, max(0.0, (z - z0) / (z1 - z0)))
            return (w + (w1 - w) * t) / 2

        L = [(xc - hw(z), y, z) for y, z in pts_yz]
        R = [(xc + hw(z), y, z) for y, z in pts_yz]
        faces = [(i, (i + 1) % n, n + (i + 1) % n, n + i) for i in range(n)]
        faces.append(tuple(range(n, 2 * n)))
        faces.append(tuple(reversed(range(n))))
        self.add(L + R, faces)

    def tube_y(self, prof_xz, y0, y1):
        n = len(prof_xz)
        A = [(x, y0, z) for x, z in prof_xz]
        B = [(x, y1, z) for x, z in prof_xz]
        faces = [(i, i + 1, n + i + 1, n + i) for i in range(n - 1)]
        self.add(A + B, faces)

    def ribbon(self, pa, pb, y):
        """flat band between two xz profiles at fixed y."""
        n = len(pa)
        pts = [(x, y, z) for x, z in pa] + [(x, y, z) for x, z in pb]
        faces = [(i, i + 1, n + i + 1, n + i) for i in range(n - 1)]
        self.add(pts, faces)


def new_empty(name, parent=None, loc=(0, 0, 0), rot=(0, 0, 0)):
    ob = bpy.data.objects.new(name, None)
    ob.empty_display_type = "PLAIN_AXES"
    ob.empty_display_size = 0.2
    ob.location = loc
    ob.rotation_euler = [math.radians(a) for a in rot]
    bpy.context.scene.collection.objects.link(ob)
    if parent is not None:
        ob.parent = parent
    return ob


def make_obj(name, geo, color, parent=None, loc=(0, 0, 0), rot=(0, 0, 0)):
    me = bpy.data.meshes.new(name)
    me.from_pydata(geo.verts, [], geo.faces)
    me.update()
    if any(geo.smooth):
        me.polygons.foreach_set("use_smooth", geo.smooth)
        me.update()
    ob = bpy.data.objects.new(name, me)
    ob.color = color
    ob.location = loc
    ob.rotation_euler = [math.radians(a) for a in rot]
    bpy.context.scene.collection.objects.link(ob)
    if parent is not None:
        ob.parent = parent
    return ob


# --------------------------------------------------------------------------------------
# hero coupe
# --------------------------------------------------------------------------------------
FLAME_PROFILE = [(0.0, 0.05), (0.12, 0.085), (0.35, 0.115), (0.62, 0.075), (0.85, 0.035), (1.0, 0.0)]   # unit-length teardrop
WHEELBASE = 2.78            # default wheelbase (m); axle midpoint stays at y = -0.01 (wheels at +1.38 / -1.40)
AXLE_MID = -0.01
CAR_DEFAULTS = dict(
    spoiler="wing",         # wing (low pearl-white coupe wing) | small (low trunk lip) | none
    wheelbase=WHEELBASE,
    lamp_gap=0.0,           # >0: second round lamp per side, this many metres toward the car centre line
    car_grey=1.0,           # multiplier on the display grey of the body (and wing)
    macro=False,            # macro rear-panel treatment (S06): dark panel overlay, bezel plate, lens disc
    panel_grey=0.17,        # display grey of the macro rear panel
    lamp_outer=None,        # display grey of the taillight outer disc / bezel (None = follows the ignition ramp)
    lamp_lens=None,         # macro: display grey of the lens disc, a number or [from, to]
    bezel=None,             # macro: bezel plate [x_right_of_lamp, z_top, corner_radius] (metres) or True
)


def build_car(tag, parent, pos, yaw_deg, flame=False, flame_pipe=0, opts=None):
    """90s sport coupe, forward = +Y, origin on the ground at the centre. Returns dict of handles.
    opts: see CAR_DEFAULTS (per-shot keys spoiler, wheelbase, lamp_gap, car_grey, macro...)."""
    o = dict(CAR_DEFAULTS)
    o.update({k: v for k, v in (opts or {}).items() if v is not None or k in ("lamp_outer", "lamp_lens", "bezel")})
    root = new_empty(f"{tag}_car", parent, loc=pos, rot=(0, 0, yaw_deg))
    C = Style.col
    body_col = Style.col(PAL["body"] * Style.grey * float(o["car_grey"]))
    # lower body: wedge side profile
    g = Geo()
    g.prism_x([(-2.2, 0.28), (2.0, 0.28), (2.2, 0.40), (2.1, 0.56), (1.0, 0.74), (-1.7, 0.90), (-2.2, 0.86)], 0.0, 1.76)
    # side skirts / bumpers hints
    g.box((0, 2.12, 0.36), (1.60, 0.14, 0.16))
    g.box((0, -2.14, 0.36), (1.60, 0.14, 0.16))
    make_obj(f"{tag}_body", g, body_col, root)
    # cabin
    g = Geo()
    g.prism_x([(-1.65, 0.70), (1.0, 0.70), (1.0, 0.76), (0.15, 1.22), (-0.95, 1.22), (-1.65, 0.90)], 0.0, 1.56,
              taper=(0.80, 1.22, 1.22))
    g.box((0.90, 0.45, 0.97), (0.14, 0.12, 0.08))     # mirrors
    g.box((-0.90, 0.45, 0.97), (0.14, 0.12, 0.08))
    make_obj(f"{tag}_cabin", g, Style.col(PAL["glass"] * Style.grey * float(o["car_grey"])), root)
    # rear spoiler: the real pearl-white coupe carries a LOW wing, its top about at roof height and ~1.26 m wide
    if o["spoiler"] == "wing":
        g = Geo()
        g.box((0, -2.05, 1.09), (1.26, 0.40, 0.045), rot=(-6, 0, 0))     # slab, top ~z 1.12
        g.box((0.36, -2.02, 0.99), (0.06, 0.14, 0.22))                   # two supports standing on the trunk lid
        g.box((-0.36, -2.02, 0.99), (0.06, 0.14, 0.22))
        g.box((0.63, -2.04, 1.11), (0.03, 0.44, 0.16))                   # end plates
        g.box((-0.63, -2.04, 1.11), (0.03, 0.44, 0.16))
        make_obj(f"{tag}_wing", g, body_col, root)
    elif o["spoiler"] == "small":
        g = Geo()
        g.box((0, -2.10, 0.93), (1.30, 0.20, 0.035), rot=(-8, 0, 0))     # small lip on the trunk lid
        g.box((0.55, -2.07, 0.90), (0.05, 0.12, 0.08))
        g.box((-0.55, -2.07, 0.90), (0.05, 0.12, 0.08))
        make_obj(f"{tag}_wing", g, body_col, root)
    # lights / plate / exhaust
    g = Geo()
    g.box((0.62, 2.2, 0.55), (0.34, 0.06, 0.12))
    g.box((-0.62, 2.2, 0.55), (0.34, 0.06, 0.12))
    g.box((0, -2.215, 0.52), (0.50, 0.03, 0.12))
    make_obj(f"{tag}_lamps", g, C("line"), root)
    g = Geo()
    g.box((0, 2.2, 0.38), (1.1, 0.06, 0.16))
    for sx in (-1, 1):
        g.cyl((sx * 0.36, -2.30, 0.34), 0.05, 0.2, axis="y", seg=10)
        g.box((sx * 0.885, 0.0, 0.50), (0.012, 2.1, 0.012))                 # character line between the wheels
        for dy in (-0.75, 0.55):
            g.box((sx * 0.885, dy, 0.64), (0.012, 0.012, 0.40))               # door seams
    make_obj(f"{tag}_dark", g, C("dark"), root)
    # taillights: round clusters (outer disc, dark ring, bright centre); macro style: bezel disc + lens disc + core
    lit_c = C("light")
    outer_c = lit_c if o["lamp_outer"] is None else Style.col(float(o["lamp_outer"]))
    xs_main = [sx * TAIL_X for sx in (-1, 1)]
    xs_gap = [sx * (TAIL_X - float(o["lamp_gap"])) for sx in (-1, 1)] if float(o["lamp_gap"]) > 0 else []

    def lamp_set(xs, nm):
        outer, ring, lens, core = Geo(), Geo(), Geo(), Geo()
        so, sc = (72, 48) if o["macro"] else (24, 16)            # smoother discs when the lamp fills the frame
        for x in xs:
            outer.cyl((x, TAIL_Y + 0.065, TAIL_Z), 0.118, 0.07, axis="y", seg=so, smooth=False)   # -2.245 .. -2.175
            if o["macro"]:
                lens.cyl((x, TAIL_Y + 0.058, TAIL_Z), 0.104, 0.07, axis="y", seg=so, smooth=False)  # lens disc inside the bezel
            else:
                ring.cyl((x, TAIL_Y + 0.055, TAIL_Z), 0.078, 0.08, axis="y", seg=24, smooth=False)  # to -2.255
            core.cyl((x, TAIL_Y + 0.040, TAIL_Z), 0.042, 0.09, axis="y", seg=sc, smooth=False)    # to -2.275
        h = {}
        h["outer"] = make_obj(f"{tag}_tail{nm}", outer, outer_c, root)
        if o["macro"]:
            h["lens"] = make_obj(f"{tag}_taillens{nm}", lens, C(0.12), root)
        else:
            make_obj(f"{tag}_tailring{nm}", ring, C("dark"), root)
        h["core"] = make_obj(f"{tag}_tailcore{nm}", core, lit_c, root)
        return h

    main = lamp_set(xs_main, "")
    tail, tail_core = main["outer"], main["core"]
    gap = lamp_set(xs_gap, "2") if xs_gap else None
    if o["macro"]:
        # dark rear panel laid over the real rear face (hides the deck / wing stubs that showed as a dark strip), a lighter
        # rounded bezel plate round the lamp group with a dark groove and the horizontal slot
        pc = Style.col(float(o["panel_grey"]))
        g = Geo()
        g.box((0, -2.205, 0.80), (1.80, 0.008, 1.10))
        make_obj(f"{tag}_macropanel", g, pc, root)
        if o["bezel"]:
            bz = o["bezel"] if isinstance(o["bezel"], (list, tuple)) else [0.154, 0.865, 0.09]
            xr, zt, rr = float(bz[0]), float(bz[1]), float(bz[2])
            x_main = max(xs_main)                               # the lamp that sits on the camera axis
            x0, x1 = x_main - 0.62, x_main + xr
            z0, z1 = TAIL_Z - 0.50, zt
            g = Geo()
            g.rrect_y(x0 - 0.014, x1 + 0.014, z0 - 0.014, z1 + 0.014, rr + 0.014, -2.2085, 0.004)
            make_obj(f"{tag}_groove", g, C(0.04), root)
            g = Geo()
            g.rrect_y(x0, x1, z0, z1, rr, -2.2125, 0.004)
            make_obj(f"{tag}_bezelplate", g, Style.col(float(o["panel_grey"]) * 1.35), root)
            g = Geo()
            g.box((x1 + 0.12, -2.2150, TAIL_Z - 0.017), (0.30, 0.004, 0.012))
            make_obj(f"{tag}_slot", g, C(0.04), root)
    # wheels with spokes
    wheels = []
    wb = float(o["wheelbase"])
    for sx in (-1, 1):
        for wy in (AXLE_MID + wb / 2, AXLE_MID - wb / 2):
            piv = new_empty(f"{tag}_wheel", root, loc=(sx * 0.76, wy, WHEEL_R))
            g = Geo()
            g.cyl((0, 0, 0), WHEEL_R, 0.26, axis="x", seg=24)
            make_obj(f"{tag}_tire", g, C("tire"), piv)
            g = Geo()
            g.cyl((0, 0, 0), 0.215, 0.272, axis="x", seg=24, smooth=False)
            make_obj(f"{tag}_rim", g, C("dark"), piv)
            g = Geo()
            for side in (-1, 1):
                for k in range(5):
                    g.box((side * 0.146, 0, 0), (0.022, 0.06, 0.40), rot=(k * 36.0, 0, 0))
                g.cyl((side * 0.148, 0, 0), 0.05, 0.022, axis="x", seg=12, smooth=False)
            make_obj(f"{tag}_spokes", g, C("spoke"), piv)
            wheels.append(piv)
    fl = []
    if flame is True:                       # legacy cue: thin 0.5 m cones at both pipes, hard-coded timing
        for sx in (-1, 1):
            g = Geo()
            g.cyl((0, 0, 0.25), 0.055, 0.5, r_top=0.0, seg=10, caps=False, smooth=False)
            ob = make_obj(f"{tag}_flame", g, C("light"), root, loc=(sx * 0.36, -2.4, 0.34), rot=(90, 0, 0))
            ob.scale = (1, 1, 0.001)
            fl.append(ob)
    elif flame:                             # flame list: teardrop of unit length, scaled in z by the cue length
        for sx in (-1, 1):
            if flame_pipe and sx != flame_pipe:
                continue
            g = Geo()
            g.lathe(FLAME_PROFILE, (0, 0, 0), seg=14)
            ob = make_obj(f"{tag}_flame", g, C("light"), root, loc=(sx * 0.36, -2.34, 0.34), rot=(90, 0, 0))
            ob.scale = (1, 1, 0.001)
            fl.append(ob)
    return dict(root=root, wheels=wheels, tail=tail, tail_core=tail_core, flames=fl,
                lens=main.get("lens"), tail2=(gap or {}).get("outer"), core2=(gap or {}).get("core"),
                lens2=(gap or {}).get("lens"))


# --------------------------------------------------------------------------------------
# mannequin
# --------------------------------------------------------------------------------------
REST = {n: (0, 0, 0) for n in ("hip_L", "hip_R", "knee_L", "knee_R", "sh_L", "sh_R", "el_L", "el_R",
                                "head", "spine", "lean")}
REST["sh_L"] = (0, 5, 0)
REST["sh_R"] = (0, -5, 0)
VISOR_LOC = (0.0, 0.098, 0.138)


def build_figure(tag, parent, torso_up=0.0, shoulder_w=0.45, visor_w=0.15, visor_h=0.04):
    """Mannequin, forward = +Y. torso_up (m) raises chest / shoulders / arms relative to the head pivot (shortens the neck:
    close-up bust preset); shoulder_w (m) = distance between the shoulder joints (default 0.45)."""
    C = Style.col
    root = new_empty(f"{tag}_root", parent)
    lean = new_empty(f"{tag}_lean", root)
    pelvis = new_empty(f"{tag}_pelvis", lean, loc=(0, 0, HIP_Z))
    spine = new_empty(f"{tag}_spine", pelvis)
    J = dict(lean=lean, pelvis=pelvis, spine=spine)
    tu, hs = float(torso_up), float(shoulder_w) / 2
    g = Geo()
    g.cyl((0, 0, -0.01), 0.165, 0.18, sxy=(1.0, 0.72), seg=20)
    g.cyl((0, 0, 0.30 + tu / 2), 0.180 * hs / 0.225, 0.40 + tu, sxy=(1.0, 0.70), seg=20)
    g.sphere((hs, 0, 0.455 + tu), 0.065, 12, 8)
    g.sphere((-hs, 0, 0.455 + tu), 0.065, 12, 8)
    g.cyl((0, 0, (0.47 + tu + 0.59) / 2), 0.045, 0.59 - 0.47 - tu, seg=10)
    make_obj(f"{tag}_torso", g, C("body"), spine)
    head = new_empty(f"{tag}_head", spine, loc=(0, 0, 0.57))
    J["head"] = head
    g = Geo()
    g.sphere((0, 0, 0.11), 0.105, 20, 12, s=(0.95, 1.0, 1.08))
    make_obj(f"{tag}_headmesh", g, C("body"), head)
    g = Geo()
    g.box((0, 0, 0), (float(visor_w), 0.05, float(visor_h)))
    visor = make_obj(f"{tag}_visor", g, C("dark"), head, loc=VISOR_LOC)
    for side, sx in (("L", -1), ("R", 1)):
        hip = new_empty(f"{tag}_hip{side}", pelvis, loc=(sx * 0.095, 0, -0.02))
        g = Geo()
        g.cyl((0, 0, -0.22), 0.068, 0.44, r_top=0.062, seg=14)
        g.sphere((0, 0, 0), 0.075, 12, 8)
        make_obj(f"{tag}_thigh{side}", g, C("body"), hip)
        knee = new_empty(f"{tag}_knee{side}", hip, loc=(0, 0, -0.44))
        g = Geo()
        g.cyl((0, 0, -0.215), 0.058, 0.43, r_top=0.062, seg=14)
        g.sphere((0, 0, 0), 0.062, 12, 8)
        g.box((0, 0.05, -0.43), (0.10, 0.26, 0.06))
        make_obj(f"{tag}_shin{side}", g, C("body"), knee)
        sh = new_empty(f"{tag}_sh{side}", spine, loc=(sx * hs, 0, 0.455 + tu))
        g = Geo()
        g.cyl((0, 0, -0.15), 0.042, 0.30, seg=12)
        make_obj(f"{tag}_uarm{side}", g, C("body"), sh)
        el = new_empty(f"{tag}_el{side}", sh, loc=(0, 0, -0.30))
        g = Geo()
        g.cyl((0, 0, -0.135), 0.036, 0.27, seg=12)
        g.sphere((0, 0, 0), 0.045, 10, 8)
        g.sphere((0, 0, -0.30), 0.05, 12, 8, s=(1.0, 0.55, 1.15))
        for fx in (-0.030, -0.010, 0.010, 0.030):                           # fingers
            g.cyl((fx, 0.0, -0.375), 0.0115, 0.085, seg=6)
        g.cyl((-sx * 0.052, 0.0, -0.335), 0.0125, 0.06, seg=6, rot=(0, sx * 35.0, 0))   # thumb
        make_obj(f"{tag}_farm{side}", g, C("body"), el)
        J[f"hip_{side}"], J[f"knee_{side}"], J[f"sh_{side}"], J[f"el_{side}"] = hip, knee, sh, el
    return dict(root=root, j=J, visor=visor)


def key_pose(F, frame, pose, visor_base=0.0):
    full = dict(REST)
    full.update({k: v for k, v in pose.items() if k in REST})
    for name, rot in full.items():
        ob = F["j"][name]
        ob.rotation_euler = [math.radians(a) for a in rot]
        ob.keyframe_insert("rotation_euler", frame=frame)
    p = F["j"]["pelvis"]
    p.location = (0, pose.get("pelvis_x", 0.0), pose.get("pelvis_z", HIP_Z))
    p.keyframe_insert("location", frame=frame)
    v = F["visor"]
    v.location = (VISOR_LOC[0], VISOR_LOC[1], VISOR_LOC[2] + visor_base + pose.get("visor_dz", 0.0))
    v.keyframe_insert("location", frame=frame)


def walk_pose(phase, lean_fwd=3.0):
    s, c = math.sin(phase), math.cos(phase)
    return {
        "hip_L": (26 * s, 0, 0), "hip_R": (-26 * s, 0, 0),
        "knee_L": (-45 * max(0.0, c), 0, 0), "knee_R": (-45 * max(0.0, -c), 0, 0),
        "sh_L": (-24 * s, 5, 0), "sh_R": (24 * s, -5, 0),
        "el_L": (20 + 14 * max(0.0, s), 0, 0), "el_R": (20 + 14 * max(0.0, -s), 0, 0),
        "head": (2 * math.sin(2 * phase), 0, 0), "spine": (lean_fwd, 0, 3 * s),
        "pelvis_z": HIP_Z - 0.012 + 0.014 * abs(c),
    }


def seated(extra=None):
    d = {"hip_L": (90, 0, 4), "hip_R": (90, 0, -4), "knee_L": (-90, 0, 0), "knee_R": (-90, 0, 0),
         "pelvis_z": SEAT_Z + 0.115, "spine": (-2, 0, 0)}
    if extra:
        d.update(extra)
    return d


# named poses of the mannequin (joint -> (x, y, z) degrees; x swings an arm forward, see REST) for the keyed
# 'figure_poses' list and for the close-up gestures of S05 / S10
POSE_LIB = {
    "stand": {},
    "chin": {"sh_R": (48, 0, 0), "el_R": (126, 0, 51)},                       # S10: right hand on the chin
    "tilt": {"head": (0, 9, 0)},                                              # head tilted 9 deg to the figure's left
    "temples": {"sh_R": (62, -34, 0), "el_R": (116, 0, 0), "sh_L": (62, 34, 0), "el_L": (116, 0, 0)},   # S05: fingers at the glasses
    "temple_R": {"sh_R": (62, -34, 0), "el_R": (116, 0, 0)},
    "temple_L": {"sh_L": (62, 34, 0), "el_L": (116, 0, 0)},
    "point_R": {"sh_R": (84, -10, 0), "el_R": (50, 0, 0)},                    # S05: hand stretched toward the lens
    "point_L": {"sh_L": (84, 10, 0), "el_L": (50, 0, 0)},
}


def resolve_pose(p):
    """pose spec -> joint dict: a POSE_LIB name, a joint dict, or a list of those merged left to right."""
    if isinstance(p, str):
        if p not in POSE_LIB:
            raise SystemExit(f"unknown pose {p!r} (have {', '.join(POSE_LIB)})")
        return dict(POSE_LIB[p])
    if isinstance(p, dict):
        return {k: (tuple(v) if isinstance(v, (list, tuple)) else v) for k, v in p.items()}
    d = {}
    for q in p:
        d.update(resolve_pose(q))
    return d


def animate_figure(F, action, f0, f1, fps, path, yaw, seated_flag=False, lean_sign=1.0, appear=None,
                   lean_deg=22.0, poses=None, visor_dz=0.0, pose_interp="BEZIER"):
    """Keyframe the mannequin. path = [p_start, p_end] (world-local coordinates).
    poses = [[t_s, pose], ...] keyed gesture (see POSE_LIB; any action name is replaced by it); visor_dz = static
    visor level (m) added for every pose."""
    root = F["root"]
    n = f1 - f0
    T = max(n, 1) / fps
    p0, p1 = path[0], path[-1]
    root.rotation_euler = (0, 0, math.radians(yaw))
    with interp("LINEAR"):
        root.location = p0
        root.keyframe_insert("location", frame=f0)
        root.location = p1
        root.keyframe_insert("location", frame=f1)
    if appear:                                         # None / 0 = visible from the first frame
        with interp("CONSTANT"):
            root.scale = (0.001, 0.001, 0.001)
            root.keyframe_insert("scale", frame=f0)
            root.scale = (1, 1, 1)
            root.keyframe_insert("scale", frame=f0 + max(1, rnd(appear * fps)))
    dist = math.dist(p0, p1)
    if action == "walk" and not poses:
        speed = dist / T if T > 0 else 0.0
        cps = min(2.3, max(0.8, speed / 1.45))
        with interp("LINEAR"):
            for f in range(f0, f1 + 1):
                t = (f - f0) / fps
                key_pose(F, f, walk_pose(2 * math.pi * cps * t, lean_fwd=3.0 + min(speed, 3.0) * 1.2), visor_dz)
        return
    sec = lambda t: f0 + rnd(t * fps)  # noqa: E731
    with interp(pose_interp if poses else "BEZIER"):
        if poses:
            seq = [(float(t_), resolve_pose(p_)) for t_, p_ in poses]
        elif action == "flick":
            up = {"sh_R": (78, -8, 0), "el_R": (112, 0, 0), "head": (-4, 0, -4)}
            seq = [
                (0.00, {"head": (3, 0, 0)}),
                (0.20, {"head": (3, 0, 0)}),
                (0.42, dict(up, visor_dz=0.0)),
                (0.52, dict(up, visor_dz=-0.034)),
                (0.62, dict(up, visor_dz=-0.034, head=(-6, 0, 0))),
                (0.72, {"sh_R": (40, -8, 0), "el_R": (60, 0, 0), "visor_dz": -0.034, "head": (-4, 0, 0)}),
                (0.82, {"sh_R": (100, -4, 0), "el_R": (62, 0, 0), "visor_dz": -0.034, "head": (-2, 0, 0)}),
                (0.92, {"sh_R": (108, -6, 0), "el_R": (4, 0, 0), "visor_dz": -0.034}),
                (1.00, {"sh_R": (110, -6, 0), "el_R": (10, 0, 0), "visor_dz": -0.034}),
            ]
        elif action == "poses":
            lap = {"sh_L": (18, 4, 0), "sh_R": (18, -4, 0), "el_L": (70, 0, 0), "el_R": (70, 0, 0)}
            pA = {"sh_R": (80, -12, 0), "el_R": (118, 0, 0), "sh_L": (18, 4, 0), "el_L": (70, 0, 0), "head": (0, -9, 0)}
            pB = {"sh_L": (82, 18, 0), "sh_R": (82, -18, 0), "el_L": (122, 0, 0), "el_R": (122, 0, 0), "head": (0, 7, 0)}
            pC = {"sh_L": (20, 140, 0), "sh_R": (20, -140, 0), "el_L": (15, 0, 0), "el_R": (15, 0, 0), "head": (-12, 0, 0)}
            seq = [(0.00, lap), (0.12, lap), (0.26, pA), (0.52, pA), (0.64, pB), (0.90, pB), (1.02, pC), (1.40, pC)]
            seq = [(t * T / 1.4, p) for t, p in seq]
        elif action == "lean":
            base = {"lean": (0, lean_deg * lean_sign, 0), "sh_L": (28, 4, 0), "sh_R": (28, -4, 0),
                    "el_L": (100, 0, 0), "el_R": (100, 0, 0), "knee_R": (-14, 0, 0), "hip_R": (8, 0, 0),
                    "head": (0, 4 * lean_sign, 0)}
            seq = [(0.0, base), (T * 0.5, dict(base, head=(-3, 4 * lean_sign, 0))), (T, base)]
        elif action == "lean_pockets":      # 'lean' with the arms down and the hands near the front pockets
            base = {"lean": (0, lean_deg * lean_sign, 0), "sh_L": (8, 4, 0), "sh_R": (8, -4, 0),
                    "el_L": (50, 0, 0), "el_R": (50, 0, 0), "knee_R": (-14, 0, 0), "hip_R": (8, 0, 0),
                    "head": (0, 4 * lean_sign, 0)}
            seq = [(0.0, base), (T * 0.5, dict(base, head=(-3, 4 * lean_sign, 0))), (T, base)]
        elif action == "chin":              # S10: right hand on the chin for ~0.4 s, then both arms down and the head tilts
            chin, tilt = POSE_LIB["chin"], POSE_LIB["tilt"]
            seq = [(0.0, chin), (0.38, chin), (0.55, tilt), (T, tilt)]
        else:  # stand
            seq = [(0.0, {}), (T, {})]
        for t, pose in seq:
            fr = f0 + min(n, max(0, rnd(t * fps)))
            if seated_flag:
                pose = seated(pose)
            key_pose(F, fr, pose, visor_dz)


# --------------------------------------------------------------------------------------
# environments (all geometry merged into a handful of meshes)
# --------------------------------------------------------------------------------------
def build_garage(tag, world, car_xy, flicker, opts=None):
    """Underground garage. opts (all optional, defaults = the original look): beams (0 = none, 1 = 0.56 m deep,
    float <1 = thinner), bay_lines (0/1), columns [[x,y],...] (explicit list replaces the grid), tubes
    [[x,y,length,yaw_deg],...] (explicit list replaces the grid), tube_w (m), ceiling_grey (display grey of the
    ceiling slab), structure_grey (multiplier on the grey of walls / columns / beams)."""
    opts = opts or {}
    C = Style.col
    sg = float(opts.get("structure_grey", 1.0))
    struct_c = Style.col(PAL["body"] * Style.grey * sg)
    cx, cy = car_xy
    g = Geo()   # floor
    g.box((0, 10, -0.1), (50, 110, 0.2))
    make_obj(f"{tag}_floor", g, C("floor"), world)
    g = Geo()   # ceiling
    g.box((0, 10, 3.15), (50, 110, 0.3))
    make_obj(f"{tag}_ceiling", g, C(opts["ceiling_grey"]) if "ceiling_grey" in opts else C("ceiling"), world)
    g = Geo()   # walls
    for sx in (-1, 1):
        g.box((sx * 25.25, 10, 1.65), (0.5, 110.5, 3.3))
    g.box((0, -45.25, 1.65), (50.5, 0.5, 3.3))
    g.box((0, 65.25, 1.65), (50.5, 0.5, 3.3))
    make_obj(f"{tag}_walls", g, struct_c, world)
    g = Geo()   # columns + beams
    xs = (-21.0, -7.0, 7.0, 21.0)
    ys = [-40.0 + 8 * k for k in range(14)]          # column rows every 8 m: y = -40 .. 64
    cols = opts.get("columns")
    cols = [(x, y) for x in xs for y in ys] if cols is None else cols
    for x, y in cols:
        g.box((x, y, 1.5), (0.8, 0.8, 3.0))
    bm = opts.get("beams", 1)
    bm = 1.0 if bm is True else (0.0 if bm is False else float(bm))
    if bm > 0:
        bd = 0.56 * bm                                # beam depth (and width scales with it for thin conduit-like beams)
        bw = 0.5 * min(1.0, max(bm, 0.25))
        for y in ys:
            g.box((0, y, 3.0 - bd / 2), (50, bw, bd))
        for x in xs:
            g.box((x, 10, 3.0 - bd / 2), (bw, 110, bd))
    if g.verts:
        make_obj(f"{tag}_cols", g, struct_c, world)
    # parking bay lines around the car (bays 2.8 m wide, the car sits in the bay centred on x=0)
    if opts.get("bay_lines", 1):
        g = Geo()
        for k in range(-6, 6):
            g.box((1.4 + 2.8 * k, cy, 0.006), (0.10, 5.8, 0.012))
        g.box((0, cy + 2.9, 0.006), (33.6, 0.10, 0.012))
        make_obj(f"{tag}_lines", g, C("line"), world)
    # aisle dashes along Y (left of the bays) for depth cue
    g = Geo()
    for k in range(-8, 12):
        g.box((-17.5, k * 6.0, 0.006), (0.14, 2.6, 0.012))
    make_obj(f"{tag}_dash", g, C("line"), world)
    # ceiling light tubes
    tubes = []
    tw = float(opts.get("tube_w", 0.12))
    ty = [-44.0 + 4 * k for k in range(27)]
    explicit = opts.get("tubes")
    if flicker and not explicit:
        for x in (-3.5, 3.5):
            for y in ty:
                gg = Geo()
                gg.box((0, 0, 0), (tw, 1.7, 0.06))
                tubes.append(make_obj(f"{tag}_tube", gg, C("light"), world, loc=(x, y, 2.95)))
        xs2 = (-10.5, 10.5)
    else:
        xs2 = (-10.5, -3.5, 3.5, 10.5)
    g = Geo()
    if explicit:                                  # explicit tubes [[x, y, length, yaw_deg], ...]
        for t in explicit:
            g.box((t[0], t[1], 2.93), (tw, t[2], 0.06), rot=(0, 0, t[3] if len(t) > 3 else 0.0))
    else:
        for x in xs2:
            for y in ty:
                g.box((x, y, 2.95), (tw, 1.7, 0.06))
    make_obj(f"{tag}_tubes", g, C("light"), world)
    return tubes


def build_highway(tag, world, opts=None):
    """Night highway. opts (all optional, defaults = the original look): skyline (scale of the background tower
    heights, 0 = no towers), poles / gantry / lanes / rails (0 hides that group), open (1 = empty airfield: only an
    endless flat ground, no road structure at all), horizon_lights {x:[x0,x1], y:dist, z:height, n:count, size:m}
    (a low string of small lights, e.g. S12)."""
    opts = opts or {}
    C = Style.col
    is_open = bool(opts.get("open", 0))
    on = lambda k: bool(opts.get(k, 1)) and not is_open   # noqa: E731
    g = Geo()
    if is_open:
        g.box((0, 120, -0.55), (4000, 4000, 0.8))          # endless ground (the far clip plane is the horizon)
    else:
        g.box((0, 120, -0.55), (400, 540, 0.8))
    make_obj(f"{tag}_ground", g, C("ground"), world)
    if on("lanes") or on("rails") or on("poles") or on("gantry"):
        g = Geo()
        g.box((0, 120, -0.15), (16, 540, 0.3))
        make_obj(f"{tag}_road", g, C("floor"), world)
    if on("lanes"):
        g = Geo()
        for y in range(-140, 390, 6):
            for x in (-1.75, 1.75):
                g.box((x, y + 1.5, 0.012), (0.15, 3.0, 0.024))
        for x in (-5.5, 5.5):
            g.box((x, 120, 0.012), (0.18, 540, 0.024))
        make_obj(f"{tag}_lanes", g, C("line"), world)
    if on("rails"):
        g = Geo()
        for sx in (-1, 1):
            g.box((sx * 8.8, 120, 0.72), (0.12, 540, 0.34))
            for y in range(-140, 390, 4):
                g.box((sx * 8.8, y, 0.4), (0.10, 0.10, 0.8))
        make_obj(f"{tag}_rails", g, C("body"), world)
    if on("poles"):
        g = Geo()
        for y in range(-140, 390, 30):
            for sx in (-1, 1):
                g.box((sx * 10.5, y, 4.8), (0.2, 0.2, 9.6))
                g.box((sx * 8.8, y, 9.5), (3.4, 0.14, 0.14))
                g.box((sx * 7.2, y, 9.38), (0.9, 0.5, 0.14))
        make_obj(f"{tag}_poles", g, C("body"), world)
    if on("gantry"):
        g = Geo()
        for y in (70, 190, 310, -50):
            for sx in (-1, 1):
                g.box((sx * 9.6, y, 3.8), (0.55, 0.55, 7.6))
            g.box((0, y, 7.5), (19.8, 0.6, 0.7))
            g.box((-3.0, y - 0.35, 5.9), (6.2, 0.2, 2.2))
            g.box((4.2, y - 0.35, 5.9), (4.2, 0.2, 2.2))
        make_obj(f"{tag}_gantry", g, C("line"), world)
    sky = 0.0 if is_open else float(opts.get("skyline", 1.0))
    rng = random.Random(11)
    g = Geo()
    for _ in range(80):
        side = rng.choice((-1, 1))
        x = side * rng.uniform(45, 170)
        y = rng.uniform(-100, 380)
        w, d, h = rng.uniform(10, 28), rng.uniform(10, 28), rng.uniform(12, 90)
        g.box((x, y, h * sky / 2), (w, d, h * sky))
    for _ in range(40):
        x = rng.uniform(-190, 190)
        y = rng.uniform(395, 430)
        w, d, h = rng.uniform(10, 26), rng.uniform(10, 24), rng.uniform(25, 120)
        g.box((x, y, h * sky / 2), (w, d, h * sky))
    if sky > 0:                              # skyline 0 = no background towers (the real night sky is black)
        make_obj(f"{tag}_skyline", g, C("ground"), world)
    hl = opts.get("horizon_lights")
    if hl:
        g = Geo()
        x0, x1 = hl.get("x", [-50.0, -8.0])
        nl = max(2, int(hl.get("n", 10)))
        sz = float(hl.get("size", 0.8))
        for i in range(nl):
            g.box((x0 + (x1 - x0) * i / (nl - 1), float(hl.get("y", 120.0)), float(hl.get("z", 1.0))), (sz, sz, sz))
        make_obj(f"{tag}_horizon_lights", g, C("light"), world)


def tunnel_profile(inset=0.0, half_w=5.8, wall_h=3.0, arch_h=5.6, n=14):
    hw = half_w - inset
    ah = arch_h - inset
    pts = [(-hw, 0.0), (-hw, wall_h)]
    for k in range(1, n):
        a = math.pi - math.pi * k / n
        pts.append((hw * math.cos(a), wall_h + ah * math.sin(a)))
    pts += [(hw, wall_h), (hw, 0.0)]
    return pts


def build_tunnel(tag, world, opts=None):
    """Road tunnel. opts (all optional, defaults = the original look): half_w (5.8), wall_h (3.0), arch_h (5.6),
    ribs (1/0) + rib_step (4.0), lamp_x (4.0), lamp_z (6.82), lamp_len (1.3), lamp_w (0.55), strip (1 = continuous
    ceiling lamp strip instead of single lamps), wall_lamps (1/0), dash_x (1.9), dash_len (3.0), dash_period (6.0),
    edge_x (4.4, or [left, right] offsets of the solid edge lines), kerb (1/0), exit (1 = bright tunnel exit slab)."""
    opts = opts or {}
    C = Style.col
    y0, y1 = -60.0, 220.0
    hw = float(opts.get("half_w", 5.8))
    wh, ah = float(opts.get("wall_h", 3.0)), float(opts.get("arch_h", 5.6))
    prof = lambda inset=0.0: tunnel_profile(inset, hw, wh, ah)   # noqa: E731
    g = Geo()
    g.box((0, (y0 + y1) / 2, -0.15), (2 * hw + 0.2, y1 - y0, 0.3))
    make_obj(f"{tag}_road", g, C("floor"), world)
    g = Geo()
    g.tube_y(prof(), y0, y1)
    make_obj(f"{tag}_shell", g, C("ground"), world)
    if opts.get("ribs", 1):
        g = Geo()
        outer, inner = prof(), prof(0.4)
        step = float(opts.get("rib_step", 4.0))
        y = y0
        while y <= y1:
            g.tube_y(inner, y - 0.25, y + 0.25)
            g.ribbon(outer, inner, y - 0.25)
            g.ribbon(outer, inner, y + 0.25)
            y += step
        make_obj(f"{tag}_ribs", g, C("body"), world)
    g = Geo()
    lx, lz = float(opts.get("lamp_x", 4.0)), float(opts.get("lamp_z", 6.82))
    if opts.get("strip"):
        for sx in (-1, 1):
            g.box((sx * lx, (y0 + y1) / 2, lz), (0.30, y1 - y0, 0.14))
    else:
        ll, lw = float(opts.get("lamp_len", 1.3)), float(opts.get("lamp_w", 0.55))
        for yy in range(int(y0), int(y1), 4):
            for sx in (-1, 1):
                g.box((sx * lx, yy + 2.0, lz), (lw, ll, 0.14))
    make_obj(f"{tag}_lamps", g, C("light"), world)
    if opts.get("wall_lamps", 1):
        g = Geo()   # wall-mounted lamp boxes every 6 m (offset so they never sit on a rib): they give the
        for yy in range(int(y0), int(y1), 6):   # lamp rhythm in the low S08 wheel close-up, where the ceiling is out of frame
            for sx in (-1, 1):
                g.box((sx * (hw - 0.10), yy + 3.0, WALL_LAMP_Z), (0.14, 1.1, 0.22))
        make_obj(f"{tag}_walllamps", g, C("light"), world)
    g = Geo()
    dx, dl, dp = float(opts.get("dash_x", 1.9)), float(opts.get("dash_len", 3.0)), float(opts.get("dash_period", 6.0))
    yy = float(y0)
    while yy < y1:
        for x in (-dx, dx):
            g.box((x, yy + dl / 2, 0.012), (0.15, dl, 0.024))
        yy += dp
    ex = opts.get("edge_x", 4.4)
    exl, exr = (ex if isinstance(ex, (list, tuple)) else (ex, ex))
    for x in (-abs(exl), abs(exr)):
        g.box((x, (y0 + y1) / 2, 0.012), (0.18, y1 - y0, 0.024))
    if opts.get("kerb", 1):
        for sx in (-1, 1):
            g.box((sx * (hw - 0.5), (y0 + y1) / 2, 0.2), (1.0, y1 - y0, 0.4))
    make_obj(f"{tag}_lanes", g, C("line"), world)
    if opts.get("exit"):                      # bright tunnel exit: a lit slab filling the far opening
        g = Geo()
        g.box((0, y1 - 0.3, (wh + ah) / 2 * 0.9), (2 * hw - 0.6, 0.2, (wh + ah) * 0.85))
        make_obj(f"{tag}_exit", g, C("light"), world)


def build_booth(tag, world, opts=None):
    """Photo booth. opts (optional): window (0/1, default 1: the 0.3 m camera window behind the head), arch
    [x_c, z_c, half_w, sag(, thickness)] (a smile-shaped light ribbon on the back wall), strips [[x, width], ...]
    (full-height light strips at the back wall)."""
    opts = opts or {}
    C = Style.col
    g = Geo()
    g.box((0, 2, -0.1), (30, 30, 0.2))
    make_obj(f"{tag}_floor", g, C("floor"), world)
    g = Geo()   # tile lines for depth
    for k in range(-8, 9):
        g.box((k * 1.0, 2, 0.006), (0.04, 30, 0.012))
        g.box((0, k * 1.0 + 2, 0.006), (30, 0.04, 0.012))
    make_obj(f"{tag}_tiles", g, C("line"), world)
    g = Geo()   # room walls
    g.box((0, 2.0, 3.0), (30, 0.3, 6.0))
    g.box((-9, -5, 3.0), (0.3, 16, 6.0))
    g.box((9, -5, 3.0), (0.3, 16, 6.0))
    g.box((0, -5, 6.15), (30, 30, 0.3))
    make_obj(f"{tag}_room", g, C("ground"), world)
    g = Geo()   # booth shell
    g.box((0, 1.11, 1.2), (1.9, 0.08, 2.4))
    for sx in (-1, 1):
        g.box((sx * 0.91, 0.4, 1.2), (0.08, 1.5, 2.4))
    g.box((0, 0.4, 2.46), (2.06, 1.66, 0.12))
    g.box((0, -0.33, 2.2), (1.9, 0.10, 0.36))
    g.box((0, -0.3, 2.78), (1.3, 0.2, 0.34))
    make_obj(f"{tag}_booth", g, C("body"), world)
    g = Geo()   # curtain + rod
    for sx in (-1, 1):
        g.box((sx * 0.66, -0.28, 1.05), (0.52, 0.05, 1.7))
    make_obj(f"{tag}_curtain", g, C("glass"), world)
    g = Geo()   # camera window, stool, foot rest
    if opts.get("window", 1):
        g.box((0, 1.06, 1.5), (0.3, 0.04, 0.3))
    g.cyl((0, 0.4, SEAT_Z - 0.025), 0.20, 0.05, seg=20)
    g.cyl((0, 0.4, 0.27), 0.035, 0.54, seg=10)
    g.cyl((0, 0.4, 0.015), 0.20, 0.03, seg=20)
    g.box((0, 0.86, 0.165), (0.62, 0.26, 0.03))
    for sx in (-1, 1):
        g.box((sx * 0.26, 0.86, 0.09), (0.03, 0.03, 0.15))
    make_obj(f"{tag}_stool", g, C("dark"), world)
    g = Geo()   # neon: curved arch over the back wall (smile: lowest at x_c) + vertical strips at the wall corners
    if opts.get("arch"):
        xc, zc, hw_, sag = opts["arch"][:4]
        th = opts["arch"][4] if len(opts["arch"]) > 4 else 0.06
        n_ = 24
        lo = [(xc - hw_ + 2 * hw_ * i / n_, zc + sag * ((2 * i / n_ - 1) ** 2)) for i in range(n_ + 1)]
        g.ribbon(lo, [(x, z + th) for x, z in lo], 1.055)
    for sx_, w_ in opts.get("strips") or []:
        g.box((sx_, 1.05, 1.2), (w_, 0.04, 2.4))
    if g.verts:
        make_obj(f"{tag}_neon", g, C("light"), world)


# --------------------------------------------------------------------------------------
# per-shot build
# --------------------------------------------------------------------------------------
def noise(t, ph, amp):
    return amp * (0.6 * math.sin(2 * math.pi * 1.7 * t + ph[0]) + 0.4 * math.sin(2 * math.pi * 3.9 * t + ph[1]))


def heading_of(dv):
    """Horizontal heading (rad) of an aim vector, in the convention of aim_rotation (0 = looking along +Y)."""
    return math.atan2(-dv[0], dv[1])


def aim_rotation(dv, roll=0.0, yaw_ref=None, prev=None):
    """XYZ euler of a camera (view = local -Z, image-up = local +Y) looking along dv with no roll.

    Same orientation as a Track-To (-Z, up Y) constraint when yaw_ref is None, plus an optional roll
    (rad) about the view axis. With yaw_ref (heading in rad) the heading is held fixed and the pitch is the
    signed angle off straight-down along that heading, so an aim that passes through the zenith sweeps
    smoothly through 0 instead of flipping the picture by 180 degrees like Track-To does.
    prev = previous euler (keeps the angles continuous from frame to frame)."""
    h = math.hypot(dv[0], dv[1])
    if yaw_ref is None:
        psi = heading_of(dv) if h > 1e-9 else 0.0
        th = math.atan2(h, -dv[2])                      # 0 = straight down, 90 deg = horizontal
    else:
        psi = yaw_ref
        th = math.atan2(dv[0] * -math.sin(psi) + dv[1] * math.cos(psi), -dv[2])
    m = Matrix.Rotation(psi, 3, "Z") @ Matrix.Rotation(th, 3, "X") @ Matrix.Rotation(roll, 3, "Z")
    return m.to_euler("XYZ", prev) if prev is not None else m.to_euler("XYZ")


def force_interpolation(idb, data_path, kind):
    """Set the interpolation of every key of one animated property. (The interp() preference above does not
    take effect in headless Blender 5, where new keys always come out BEZIER, so cues that need a hard
    step set it explicitly.)"""
    ad = idb.animation_data
    if not ad or not ad.action:
        return
    act, fcs = ad.action, []
    if hasattr(act, "layers"):                                   # Blender >= 4.4 slotted actions
        for layer in act.layers:
            for strip in layer.strips:
                for cb in strip.channelbags:
                    fcs.extend(cb.fcurves)
    else:
        fcs = list(act.fcurves)
    for fc in fcs:
        if fc.data_path == data_path:
            for k in fc.keyframe_points:
                k.interpolation = kind


def key_flash(scene, f0, f1, fps, times_s):
    """Camera-flash cue: exposure pops (FLASH_EV[0] on the flash frame, FLASH_EV[1] on the next, 0 elsewhere).
    Keyed on the scene's view transform with constant interpolation; outside [f0, f1] the curve holds 0, so
    the other shots are not touched."""
    ev = {f0: 0.0, f1: 0.0}
    for t in times_s:
        fr = f0 + max(0, min(f1 - f0, rnd(t * fps)))
        ev[fr] = FLASH_EV[0]
        if fr + 1 <= f1 and ev.get(fr + 1, 0.0) < FLASH_EV[1]:
            ev[fr + 1] = FLASH_EV[1]
        if fr + 2 <= f1:
            ev.setdefault(fr + 2, 0.0)
    vs = scene.view_settings
    for fr in sorted(ev):
        vs.exposure = ev[fr]
        vs.keyframe_insert("exposure", frame=fr)
    force_interpolation(scene, "view_settings.exposure", "CONSTANT")
    vs.exposure = 0.0


def resolve_car(sid, pv, recipe, cam, look):
    """-> None or (pos, yaw_deg).  The shot's own "car" key ("none" | origin | at_lookat | pos:x,y | ...) overrides the recipe."""
    if str(pv.get("car", recipe.get("car", ""))) == "none":
        return None
    if "car_pos" in pv:
        return list(pv["car_pos"]), float(pv.get("car_yaw", 0.0))
    if "car_path" in pv:
        return list(pv["car_path"][0]), float(pv.get("car_yaw", 0.0))
    mode = pv.get("car", recipe.get("car", "origin"))
    yaw = float(pv.get("car_yaw", 0.0))
    if mode in ("origin", "path"):
        return [0.0, 0.0, 0.0], yaw
    if mode == "at_lookat":
        return [look[0], look[1], 0.0], yaw
    if mode.startswith("pos:"):
        x, y = mode[4:].split(",")
        return [float(x), float(y), 0.0], yaw
    if mode == "wheel_at_lookat":
        sx = 1.0 if cam[0] > look[0] else -1.0
        return [look[0] - sx * 0.76, look[1] - 1.38, 0.0], yaw
    if mode == "macro_taillight":
        dx, dy = look[0] - cam[0], look[1] - cam[1]
        n = math.hypot(dx, dy) or 1.0
        yaw = math.degrees(math.atan2(-dx / n, dy / n))   # car forward = viewing direction (rear faces camera)
        cy_, sy_ = math.cos(math.radians(yaw)), math.sin(math.radians(yaw))
        best = None
        for s in (-1, 1):
            lx, ly = s * TAIL_X, TAIL_Y
            wx, wy = lx * cy_ - ly * sy_, lx * sy_ + ly * cy_
            c = [look[0] - wx, look[1] - wy, 0.0]
            if best is None or abs(c[0]) < abs(best[0]):
                best = c
        return best, yaw
    raise SystemExit(f"unknown car mode {mode!r} for {sid}")


def key_taillight(car, mode, pv, f0, f1, fps):
    """Taillight colour cue. mode: lit | off | ignite | ignite_quick (per-shot key "taillight").
    ignite: the core (and, unless lamp_outer fixes it, the outer disc) ramps from display grey ignite_from to ignite_to
    over ignite_s seconds (default = the whole shot) with ease-out exponent ignite_pow (1 = linear), keyed every
    frame in DISPLAY space so the screen luma rises smoothly; the macro lens disc follows lamp_lens [from, to];
    neighbour lamps (lamp_gap) stay dark during ignition."""
    n = f1 - f0
    lit_disp = min(PAL["light"] * Style.grey, 0.98)
    c_from = float(pv.get("ignite_from", 0.10))
    c_to = float(pv.get("ignite_to", lit_disp))
    lens_spec = pv.get("lamp_lens")
    if lens_spec is not None and not isinstance(lens_spec, (list, tuple)):
        lens_spec = [lens_spec, lens_spec]
    outer_fixed = pv.get("lamp_outer") is not None
    dim = Style.col(c_from)

    def setc(ob, col, frame=None):
        if ob is None:
            return
        ob.color = col
        if frame is not None:
            ob.keyframe_insert("color", frame=frame)

    if lens_spec is not None:                                    # constant starting colour of the lens discs
        for ob in (car.get("lens"), car.get("lens2")):
            setc(ob, Style.col(float(lens_spec[0])))
    if mode == "off" or mode.startswith("ignite"):
        for ob in (car.get("tail2"), car.get("core2")):          # neighbour lamps stay dark while the main one ignites
            setc(ob, dim)
    if mode == "lit":
        if lens_spec is not None:
            setc(car.get("lens"), Style.col(float(lens_spec[1])))
        return
    ramped = [car["tail_core"]] + ([] if outer_fixed else [car["tail"]])
    if mode == "off":
        for ob in ramped:
            setc(ob, dim)
        return
    if mode == "ignite_quick":                                   # legacy: flickers on at +0.3 s (colour keys in linear light)
        lit = Style.col("light")
        t_on = f0 + rnd(0.30 * fps)
        for ob in ramped:
            setc(ob, dim, f0)
            for k, c_ in ((t_on - 4, dim), (t_on - 3, lit), (t_on - 2, dim), (t_on, lit)):
                setc(ob, c_, max(f0, k))
            setc(ob, lit, min(f1, t_on))
        return
    if mode != "ignite":
        raise SystemExit(f"unknown taillight mode {mode!r} (lit | ignite | ignite_quick | off)")
    ign_s = float(pv.get("ignite_s", n / fps if n else 1.0))
    pw = float(pv.get("ignite_pow", 1.0))
    for f in range(f0, f1 + 1):
        u = min(1.0, ((f - f0) / fps) / max(1e-6, ign_s))
        e = 1.0 - (1.0 - u) ** pw
        for ob in ramped:
            setc(ob, Style.col(c_from + (c_to - c_from) * e), f)
        if lens_spec is not None:
            setc(car.get("lens"), Style.col(float(lens_spec[0]) + (float(lens_spec[1]) - float(lens_spec[0])) * e), f)


def build_shot(shot, idx_in_env, f0, f1, fps):
    sid, env = shot["id"], shot["env"]
    if env not in ENV_X:
        raise SystemExit(f"{sid}: unknown env {env!r} (have {', '.join(ENV_X)})")
    pv = shot["previs"]
    recipe = dict(RECIPES.get(sid, dict(lens=32, car="at_lookat")))
    for k_json, k_rec in (("lens_mm", "lens"), ("speed", "speed"), ("handheld", "handheld"),
                          ("car_ease", "ease"), ("taillight", "taillight"), ("flicker", "flicker")):
        if k_json in pv:
            recipe[k_rec] = pv[k_json]
    if "lights_on" in pv:                                      # alias: lights_on true = no flicker-on cue
        recipe["flicker"] = not bool(pv["lights_on"])
    fig_rec = dict(recipe.get("figure") or {})
    if ("figure_path" in pv or "figure_poses" in pv) and not fig_rec:
        fig_rec = dict(action="stand")
    if "figure_action" in pv:
        fig_rec["action"] = pv["figure_action"]
    if "figure_appear" in pv:                                  # seconds until the figure shows up; 0 / null = from frame 0
        fig_rec["appear"] = pv["figure_appear"]
    env_opts = dict(pv.get("env_opts") or {})
    for k_ in ("skyline", "poles"):                            # top-level aliases of the highway env_opts
        if k_ in pv:
            env_opts.setdefault(k_, pv[k_])
    origin = (ENV_X[env], SHOT_Y_STEP * idx_in_env, 0.0)
    world = new_empty(f"{sid}_world", None, loc=origin)
    n = f1 - f0                       # key distance (last frame index - first frame index)
    T = n / fps
    cam_from, cam_to = pv["cam_from"], pv["cam_to"]
    look_from = pv["look_at"]
    look_to = pv.get("look_at_to", look_from)
    cam_ease = float(pv.get("cam_ease", 1.0))
    speed = 0.0 if "car_path" in pv else float(recipe.get("speed", 0.0))
    car_def = resolve_car(sid, pv, recipe, cam_from, look_from)
    car_xy = (car_def[0][0], car_def[0][1]) if car_def else (0.0, 0.0)

    # --- environment
    tubes = []
    if env == "garage":
        tubes = build_garage(sid, world, car_xy, recipe.get("flicker", False), env_opts)
    elif env == "highway":
        build_highway(sid, world, env_opts)
    elif env == "tunnel":
        build_tunnel(sid, world, env_opts)
    elif env == "booth":
        build_booth(sid, world, env_opts)

    def conv(f):
        return speed * (f - f0) / fps

    # --- car
    car = None
    if car_def:
        pos, yaw = car_def
        flame_cue = pv.get("flame")
        copts = {k_: pv[k_] for k_ in ("spoiler", "wheelbase", "lamp_gap", "car_grey", "panel_grey", "lamp_outer",
                                      "bezel") if k_ in pv}
        copts["macro"] = bool(pv.get("macro", recipe.get("car") == "macro_taillight" or pv.get("car") == "macro_taillight"))
        car = build_car(sid, world, pos, yaw, flame=(flame_cue if flame_cue else bool(recipe.get("flame"))),
                        flame_pipe=int(pv.get("flame_pipe", 0)), opts=copts)
        root = car["root"]
        with interp("LINEAR"):
            if "car_path" in pv:
                pts = pv["car_path"]
                ease = float(recipe.get("ease", pv.get("car_ease", 1.0)))
                v0 = float(pv.get("car_v0", 0.0))             # initial speed (m/s): d(t) = v0 t + (L - v0 T) u^ease
                seg_len = [math.dist(pts[i], pts[i + 1]) for i in range(len(pts) - 1)]
                total = sum(seg_len) or 1.0
                v0T = min(max(0.0, v0) * T, total)
                for f in range(f0, f1 + 1):
                    uu = (f - f0) / n if n else 0.0
                    d = v0T * uu + (total - v0T) * uu ** ease
                    u = d / total
                    i = 0
                    while i < len(seg_len) - 1 and d > seg_len[i]:
                        d -= seg_len[i]
                        i += 1
                    p = lerp(pts[i], pts[i + 1], d / seg_len[i] if seg_len[i] else 0.0)
                    root.location = p
                    root.keyframe_insert("location", frame=f)
                    for w in car["wheels"]:
                        w.rotation_euler = (-(u * total) / WHEEL_R, 0, 0)
                        w.keyframe_insert("rotation_euler", frame=f)
            elif speed > 0:
                root.location = pos
                root.keyframe_insert("location", frame=f0)
                root.location = (pos[0], pos[1] + conv(f1), pos[2])
                root.keyframe_insert("location", frame=f1)
                for w in car["wheels"]:
                    w.rotation_euler = (0, 0, 0)
                    w.keyframe_insert("rotation_euler", frame=f0)
                    w.rotation_euler = (-conv(f1) / WHEEL_R, 0, 0)
                    w.keyframe_insert("rotation_euler", frame=f1)
            key_taillight(car, str(recipe.get("taillight", "lit")), pv, f0, f1, fps)
        if car["flames"]:
            with interp("CONSTANT"):
                for ob in car["flames"]:
                    if isinstance(flame_cue, list) and flame_cue:           # [[t_on, t_off, length_m(, width_m)], ...] in seconds
                        keys = {f0: (0.001, 0.0)}
                        for item in flame_cue:
                            t_on, t_off, length = item[0], item[1], item[2]
                            width = item[3] if len(item) > 3 else 0.0
                            a_, b_ = f0 + min(n, max(0, rnd(t_on * fps))), f0 + min(n, max(0, rnd(t_off * fps)))
                            keys[a_] = (float(length), float(width))
                            keys.setdefault(b_, (0.001, 0.0))
                        for fr in sorted(keys):
                            L_, W_ = keys[fr]
                            sw = (W_ / 0.23) if W_ else max(1.0, 0.6 + 0.4 * L_)    # W_ = max diameter in m (optional 4th item)
                            ob.scale = (sw, sw, L_)
                            ob.keyframe_insert("scale", frame=fr)
                        continue
                    for k, sc_ in ((0, 0.001), (0.50, 1.0), (0.62, 0.001), (0.78, 0.7), (0.86, 0.001)):
                        ob.scale = (1, 1, sc_)
                        ob.keyframe_insert("scale", frame=f0 + rnd(k * n))
    # --- figure
    fig = None
    if fig_rec:
        path = pv.get("figure_path") or fig_rec.get("path")
        if path is None:
            path = [[0.0, 0.0, 0.0], [0.0, 0.0, 0.0]]
        action = fig_rec.get("action", "stand")
        if "figure_yaw" in pv:
            yaw = float(pv["figure_yaw"])
        else:
            dvec = (path[-1][0] - path[0][0], path[-1][1] - path[0][1])
            if math.hypot(*dvec) < 1e-4:
                dvec = (cam_from[0] - path[0][0], cam_from[1] - path[0][1])
            yaw = math.degrees(math.atan2(-dvec[0], dvec[1]))
        lean_sign = 1.0
        if action in ("lean", "lean_pockets") and car_def:
            rx = (math.cos(math.radians(yaw)), math.sin(math.radians(yaw)))
            lean_sign = 1.0 if (rx[0] * (car_def[0][0] - path[0][0]) + rx[1] * (car_def[0][1] - path[0][1])) > 0 else -1.0
        fig = build_figure(sid + "_man", world, torso_up=float(pv.get("torso_up", 0.0)),
                           shoulder_w=float(pv.get("shoulder_w", 0.45)), visor_w=float(pv.get("visor_w", 0.15)),
                           visor_h=float(pv.get("visor_h", 0.04)))
        animate_figure(fig, action, f0, f1, fps, path, yaw, seated_flag=bool(fig_rec.get("seated")),
                       lean_sign=lean_sign, appear=fig_rec.get("appear"),
                       lean_deg=float(pv.get("figure_lean_deg", 22.0)), poses=pv.get("figure_poses"),
                       visor_dz=float(pv.get("visor_dz", 0.0)), pose_interp=str(pv.get("figure_pose_interp", "BEZIER")).upper())
        if "figure_scale" in pv:                           # about the root, on the lean empty (the root scale is the 'appear' cue)
            fs_ = float(pv["figure_scale"])
            fig["j"]["lean"].scale = (fs_, fs_, fs_)
        if "head_scale" in pv:
            hs_ = float(pv["head_scale"])
            fig["j"]["head"].scale = (hs_, hs_, hs_)
    # --- garage lights flicker on one by one
    if tubes:
        dim, lit = Style.col(0.12), Style.col("light")
        tubes_sorted = sorted(tubes, key=lambda o: abs(o.location.y - cam_from[1]))
        for i, ob in enumerate(tubes_sorted):
            t_on = f0 + rnd((i / max(1, len(tubes_sorted) - 1)) * 0.80 * n)
            ob.color = dim
            with interp("CONSTANT"):
                ob.keyframe_insert("color", frame=f0)
                for k, c_ in ((t_on, lit), (t_on + 1, dim), (t_on + 2, lit)):
                    if k <= f1:
                        ob.color = c_
                        ob.keyframe_insert("color", frame=k)
    # --- camera-flash cue (exposure pops on the scene view transform)
    flash = pv.get("flash", recipe.get("flash"))
    if flash:
        key_flash(bpy.context.scene, f0, f1, fps, flash)
    # --- camera
    cdata = bpy.data.cameras.new(f"{sid}_cam")
    cdata.lens = float(recipe.get("lens", 32))
    cdata.clip_start, cdata.clip_end = 0.03, 700.0
    cam = bpy.data.objects.new(f"{sid}_cam", cdata)
    bpy.context.scene.collection.objects.link(cam)
    cam.parent = world
    tgt = new_empty(f"{sid}_look", world)
    hh = float(recipe.get("handheld", 0.0))
    roll_amp = math.radians(HANDHELD_ROLL_DEG_PER_M * hh)

    def aim_vec(u):
        """camera -> look target at normalised shot time u (the convoy offset moves both, so it cancels)."""
        uc = u ** cam_ease
        c_, l_ = lerp(cam_from, cam_to, uc), lerp(look_from, look_to, uc)
        return [l_[i] - c_[i] for i in range(3)]

    # Does the aim pass (nearly) straight down? Track-To (up = +Y) flips its roll by 180 degrees at the zenith,
    # so such a shot (S09 top-down) gets roll-free rotation keys instead: heading fixed at the start aim.
    aims = [aim_vec(i / 40.0) for i in range(41)]
    ratios = [math.hypot(d[0], d[1]) / max(1e-6, abs(d[2])) for d in aims]
    zenith = (min(ratios) < ZENITH_TOL < max(ratios)) and aims[0][2] < 0 and aims[-1][2] < 0
    yaw_ref = heading_of(next(d for d in aims if math.hypot(d[0], d[1]) > 1e-6)) if zenith else None
    explicit_rot = zenith or roll_amp > 0           # per-frame rotation keys instead of the Track-To constraint
    if not explicit_rot:
        con = cam.constraints.new("TRACK_TO")
        con.target = tgt
        con.track_axis = "TRACK_NEGATIVE_Z"
        con.up_axis = "UP_Y"
    rng = random.Random(sid)
    ph = [[rng.uniform(0, 6.28) for _ in range(2)] for _ in range(6)]
    frames_keyed = list(range(f0, f1 + 1)) if (hh > 0 or explicit_rot or cam_ease != 1.0) else [f0, f1]
    prev_rot = None
    with interp("LINEAR"):
        for f in frames_keyed:
            u = (f - f0) / n if n else 0.0
            uc = u ** cam_ease
            t = (f - f0) / fps
            c = lerp(cam_from, cam_to, uc)
            lk = lerp(look_from, look_to, uc)
            c[1] += conv(f)
            lk[1] += conv(f)
            if hh > 0:
                c = [c[0] + noise(t, ph[0], hh), c[1] + noise(t, ph[1], hh * 0.6), c[2] + noise(t, ph[2], hh)]
                lk = [lk[0] + noise(t, ph[3], hh * 2), lk[1], lk[2] + noise(t, ph[4], hh * 2)]
            cam.location = c
            cam.keyframe_insert("location", frame=f)
            tgt.location = lk
            tgt.keyframe_insert("location", frame=f)
            if explicit_rot:
                prev_rot = aim_rotation([lk[i] - c[i] for i in range(3)], roll=noise(t, ph[5], roll_amp),
                                        yaw_ref=yaw_ref, prev=prev_rot)
                cam.rotation_euler = prev_rot
                cam.keyframe_insert("rotation_euler", frame=f)
        if "lens_to_mm" in pv:
            cdata.lens = float(recipe.get("lens", 32))
            cdata.keyframe_insert("lens", frame=f0)
            cdata.lens = float(pv["lens_to_mm"])
            cdata.keyframe_insert("lens", frame=f1)
    return cam


# --------------------------------------------------------------------------------------
# scene / render
# --------------------------------------------------------------------------------------
def setup_scene(width, height, fps, aa):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    sc = bpy.context.scene
    sc.render.engine = "BLENDER_WORKBENCH"
    sc.render.resolution_x, sc.render.resolution_y = width, height
    sc.render.resolution_percentage = 100
    sc.render.fps = fps
    sc.render.image_settings.file_format = "PNG"
    sc.render.image_settings.color_mode = "RGB"
    sc.render.film_transparent = False
    sc.view_settings.view_transform = "Standard"
    sc.view_settings.look = "None"
    sc.display.render_aa = aa
    sh = sc.display.shading
    sh.light = "STUDIO"
    sh.color_type = "OBJECT"
    sh.show_object_outline = False
    sh.show_cavity = False
    sh.show_shadows = False
    sh.show_specular_highlight = False
    sh.use_world_space_lighting = False
    w = bpy.data.worlds.new("previs_world")
    l = s2l(PAL["bg"])
    w.color = (l, l, l)
    sc.world = w
    return sc


def frame_table(shots, fps):
    out = []
    for s in shots:
        a = rnd(s["start"] * fps)
        b = rnd((s["start"] + s["dur"]) * fps) - 1
        out.append((s, a, b))
    return out


def png_size(path):
    """(width, height) from the PNG header."""
    with open(path, "rb") as fh:
        head = fh.read(24)
    return struct.unpack(">II", head[16:24])


def encode(frames, frames_dir, out_path, fps, crf):
    seq = Path(frames_dir) / "_seq"
    if seq.exists():
        shutil.rmtree(seq)
    seq.mkdir(parents=True)
    for i, fr in enumerate(frames):
        os.symlink(Path(frames_dir) / f"f_{fr:04d}.png", seq / f"s_{i:05d}.png")
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-framerate", str(fps), "-i", str(seq / "s_%05d.png"),
           "-c:v", "libx264", "-preset", "medium", "-crf", str(crf), "-pix_fmt", "yuv420p", "-an",
           "-movflags", "+faststart", str(out_path)]
    subprocess.run(cmd, check=True)
    shutil.rmtree(seq)


def main(args):
    cfg = json.load(open(args.shotlist))
    fps = int(cfg["format"]["fps"])
    shots = cfg["shots"]
    table = frame_table(shots, fps)
    total = rnd(cfg["format"]["duration_s"] * fps)
    if args.list:
        for s, a, b in table:
            print(f"{s['id']}  env={s['env']:<8} frames {a:4d}-{b:4d}  ({b - a + 1} fr, {s['dur']:.2f}s)")
        print(f"total {table[-1][2] + 1} frames (format says {total})")
        return 0
    want = [x.strip().upper() for x in args.shots.split(",") if x.strip()]
    if want:
        ids = {s["id"] for s, _, _ in table}
        bad = [w for w in want if w not in ids]
        if bad:
            raise SystemExit(f"unknown shot ids {bad}; have {sorted(ids)}")
    Style.grey = args.grey
    scale = max(5.0, args.scale)
    width = max(2, int(round(1280 * scale / 100 / 2)) * 2)
    height = max(2, int(round(720 * scale / 100 / 2)) * 2)
    frames_dir = Path(args.frames_dir)
    frames_dir.mkdir(parents=True, exist_ok=True)
    full_run = not want and (scale >= 100 or args.encode_only)
    if args.out:
        out = Path(args.out)
    elif full_run:
        out = DEFAULT_OUT
    else:
        out = frames_dir.parent / "previs_partial.mp4"

    if args.encode_only:
        all_frames = [fr for _, a, b in table for fr in range(a, b + 1)]
        missing = [fr for fr in all_frames if not (frames_dir / f"f_{fr:04d}.png").exists()]
        if missing:
            raise SystemExit(f"--encode-only: {len(missing)} frames missing in {frames_dir}, e.g. f_{missing[0]:04d}.png")
        sizes = {png_size(frames_dir / f"f_{fr:04d}.png") for fr in all_frames}
        if len(sizes) != 1:
            raise SystemExit(f"--encode-only: frames have mixed sizes {sorted(sizes)}; re-render them at one --scale")
        encode(all_frames, frames_dir, out, fps, args.crf)
        print(f"encoded {len(all_frames)} frames {sizes.pop()} ->", out)
        return 0

    t_build = time.time()
    sc = setup_scene(width, height, fps, args.aa)
    seen = {}
    cams = []
    for s, a, b in table:
        if want and s["id"] not in want:
            continue
        k = seen.get(s["env"], 0)
        seen[s["env"]] = k + 1
        cam = build_shot(s, k, a, b, fps)
        cams.append((s, a, b, cam))
    print(f"built {len(cams)} shots, {len(bpy.data.objects)} objects in {time.time() - t_build:.1f}s")
    if args.save_blend:
        bpy.ops.wm.save_as_mainfile(filepath=str(Path(args.save_blend).resolve()))
        print("saved", args.save_blend)
    if args.no_render:
        return 0

    t_render = time.time()
    rendered = []
    for s, a, b, cam in cams:
        for fr in range(a, b + 1):
            p = frames_dir / f"f_{fr:04d}.png"
            if p.exists():
                p.unlink()
        sc.camera = cam
        sc.frame_start, sc.frame_end = a, b
        sc.render.filepath = str(frames_dir / "f_")
        t0 = time.time()
        with quiet():
            bpy.ops.render.render(animation=True)
        missing = [fr for fr in range(a, b + 1) if not (frames_dir / f"f_{fr:04d}.png").exists()]
        if missing:
            raise SystemExit(f"{s['id']}: {len(missing)} frames missing after render, e.g. {missing[:3]}")
        rendered.extend(range(a, b + 1))
        print(f"{s['id']} frames {a}-{b} ({b - a + 1}) rendered in {time.time() - t0:.1f}s", flush=True)
    dt = time.time() - t_render
    print(f"rendered {len(rendered)} frames at {width}x{height} in {dt:.1f}s ({dt / max(1, len(rendered)):.2f}s/frame)")
    if args.frames_only:
        print("frames in", frames_dir)
        return 0
    encode(rendered, frames_dir, out, fps, args.crf)
    print("wrote", out)
    return 0


if __name__ == "__main__":
    sys.exit(main(ARGS))
