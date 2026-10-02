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
  handheld             camera shake amplitude in metres (0 = off)
  car_pos [x,y,z], car_yaw (deg), car_path [[x,y,z],...], car_ease (exponent)
  figure_path [[x,y,z],[x,y,z]], figure_action (walk|flick|poses|lean|stand),
  figure_yaw (deg)
All coordinates are relative to the shot's own world origin (shots live in
separate worlds 1000 m apart, so they never see each other).
"""
import argparse
import json
import math
import os
import random
import shutil
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
from mathutils import Euler, Vector  # noqa: E402

# --------------------------------------------------------------------------------------
# constants
# --------------------------------------------------------------------------------------
ENV_X = {"garage": 0.0, "highway": 1000.0, "tunnel": 2000.0, "booth": 3000.0}   # env offset in X (m)
SHOT_Y_STEP = 1000.0                                                              # repeated env -> offset in Y
WHEEL_R = 0.33
HIP_Z = 0.92
SEAT_Z = 0.55
TAIL_X, TAIL_Z, TAIL_Y = 0.56, 0.74, -2.275     # TAIL_Y = outer surface of the round taillight (rear panel at -2.2)

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
    "S04": dict(lens=32, car="pos:1.7,1.2", handheld=0.015, figure=dict(action="walk")),
    "S05": dict(lens=70, car="pos:1.5,3.0", figure=dict(action="flick")),
    "S06": dict(lens=40, car="macro_taillight", taillight="ignite"),
    "S07": dict(lens=32, car="origin", speed=26.0),
    "S08": dict(lens=45, car="wheel_at_lookat", speed=26.0),
    "S09": dict(lens=22, car="at_lookat", speed=26.0),
    "S10": dict(lens=42, car="none", figure=dict(action="poses", seated=True)),
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


@contextmanager
def interp(kind):
    """Default interpolation for keyframes inserted inside the block."""
    pref = bpy.context.preferences.edit
    old = pref.keyframe_new_interpolation_type
    pref.keyframe_new_interpolation_type = kind
    try:
        yield
    finally:
        pref.keyframe_new_interpolation_type = old


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
def build_car(tag, parent, pos, yaw_deg, flame=False):
    """90s sport coupe, forward = +Y, origin on the ground at the centre. Returns dict of handles."""
    root = new_empty(f"{tag}_car", parent, loc=pos, rot=(0, 0, yaw_deg))
    C = Style.col
    # lower body: wedge side profile
    g = Geo()
    g.prism_x([(-2.2, 0.28), (2.0, 0.28), (2.2, 0.40), (2.1, 0.56), (1.0, 0.74), (-1.7, 0.90), (-2.2, 0.86)], 0.0, 1.76)
    # side skirts / bumpers hints
    g.box((0, 2.12, 0.36), (1.60, 0.14, 0.16))
    g.box((0, -2.14, 0.36), (1.60, 0.14, 0.16))
    make_obj(f"{tag}_body", g, C("body"), root)
    # cabin
    g = Geo()
    g.prism_x([(-1.65, 0.70), (1.0, 0.70), (1.0, 0.76), (0.15, 1.22), (-0.95, 1.22), (-1.65, 0.90)], 0.0, 1.56,
              taper=(0.80, 1.22, 1.22))
    g.box((0.90, 0.45, 0.97), (0.14, 0.12, 0.08))     # mirrors
    g.box((-0.90, 0.45, 0.97), (0.14, 0.12, 0.08))
    make_obj(f"{tag}_cabin", g, C("glass"), root)
    # rear wing
    g = Geo()
    g.box((0, -2.02, 1.29), (1.74, 0.46, 0.05), rot=(-6, 0, 0))
    g.box((0.60, -2.0, 1.08), (0.07, 0.16, 0.42))
    g.box((-0.60, -2.0, 1.08), (0.07, 0.16, 0.42))
    g.box((0.88, -2.02, 1.30), (0.04, 0.52, 0.22))
    g.box((-0.88, -2.02, 1.30), (0.04, 0.52, 0.22))
    make_obj(f"{tag}_wing", g, C("body"), root)
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
    # taillights: two round clusters (outer disc, dark ring, bright centre)
    outer, ring, core = Geo(), Geo(), Geo()
    for sx in (-1, 1):
        outer.cyl((sx * TAIL_X, TAIL_Y + 0.065, TAIL_Z), 0.118, 0.07, axis="y", seg=24, smooth=False)   # -2.245 .. -2.175
        ring.cyl((sx * TAIL_X, TAIL_Y + 0.055, TAIL_Z), 0.078, 0.08, axis="y", seg=24, smooth=False)    # to -2.255
        core.cyl((sx * TAIL_X, TAIL_Y + 0.040, TAIL_Z), 0.042, 0.09, axis="y", seg=16, smooth=False)    # to -2.275
    tail = make_obj(f"{tag}_tail", outer, C("light"), root)
    make_obj(f"{tag}_tailring", ring, C("dark"), root)
    tail_core = make_obj(f"{tag}_tailcore", core, C("light"), root)
    # wheels with spokes
    wheels = []
    for sx in (-1, 1):
        for wy in (1.38, -1.40):
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
    if flame:
        for sx in (-1, 1):
            g = Geo()
            g.cyl((0, 0, 0.25), 0.055, 0.5, r_top=0.0, seg=10, caps=False, smooth=False)
            ob = make_obj(f"{tag}_flame", g, C("light"), root, loc=(sx * 0.36, -2.4, 0.34), rot=(90, 0, 0))
            ob.scale = (1, 1, 0.001)
            fl.append(ob)
    return dict(root=root, wheels=wheels, tail=tail, tail_core=tail_core, flames=fl)


# --------------------------------------------------------------------------------------
# mannequin
# --------------------------------------------------------------------------------------
REST = {n: (0, 0, 0) for n in ("hip_L", "hip_R", "knee_L", "knee_R", "sh_L", "sh_R", "el_L", "el_R",
                                "head", "spine", "lean")}
REST["sh_L"] = (0, 5, 0)
REST["sh_R"] = (0, -5, 0)
VISOR_LOC = (0.0, 0.098, 0.138)


def build_figure(tag, parent):
    C = Style.col
    root = new_empty(f"{tag}_root", parent)
    lean = new_empty(f"{tag}_lean", root)
    pelvis = new_empty(f"{tag}_pelvis", lean, loc=(0, 0, HIP_Z))
    spine = new_empty(f"{tag}_spine", pelvis)
    J = dict(lean=lean, pelvis=pelvis, spine=spine)
    g = Geo()
    g.cyl((0, 0, -0.01), 0.165, 0.18, sxy=(1.0, 0.72), seg=20)
    g.cyl((0, 0, 0.30), 0.180, 0.40, sxy=(1.0, 0.70), seg=20)
    g.sphere((0.225, 0, 0.455), 0.065, 12, 8)
    g.sphere((-0.225, 0, 0.455), 0.065, 12, 8)
    g.cyl((0, 0, 0.53), 0.045, 0.12, seg=10)
    make_obj(f"{tag}_torso", g, C("body"), spine)
    head = new_empty(f"{tag}_head", spine, loc=(0, 0, 0.57))
    J["head"] = head
    g = Geo()
    g.sphere((0, 0, 0.11), 0.105, 20, 12, s=(0.95, 1.0, 1.08))
    make_obj(f"{tag}_headmesh", g, C("body"), head)
    g = Geo()
    g.box((0, 0, 0), (0.15, 0.05, 0.04))
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
        sh = new_empty(f"{tag}_sh{side}", spine, loc=(sx * 0.225, 0, 0.455))
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


def key_pose(F, frame, pose):
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
    v.location = (VISOR_LOC[0], VISOR_LOC[1], VISOR_LOC[2] + pose.get("visor_dz", 0.0))
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


def animate_figure(F, action, f0, f1, fps, path, yaw, seated_flag=False, lean_sign=1.0, appear=None):
    """Keyframe the mannequin. path = [p_start, p_end] (world-local coordinates)."""
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
    if appear is not None:
        with interp("CONSTANT"):
            root.scale = (0.001, 0.001, 0.001)
            root.keyframe_insert("scale", frame=f0)
            root.scale = (1, 1, 1)
            root.keyframe_insert("scale", frame=f0 + max(1, rnd(appear * fps)))
    dist = math.dist(p0, p1)
    if action == "walk":
        speed = dist / T if T > 0 else 0.0
        cps = min(2.3, max(0.8, speed / 1.45))
        with interp("LINEAR"):
            for f in range(f0, f1 + 1):
                t = (f - f0) / fps
                key_pose(F, f, walk_pose(2 * math.pi * cps * t, lean_fwd=3.0 + min(speed, 3.0) * 1.2))
        return
    sec = lambda t: f0 + rnd(t * fps)  # noqa: E731
    with interp("BEZIER"):
        if action == "flick":
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
            base = {"lean": (0, 22.0 * lean_sign, 0), "sh_L": (28, 4, 0), "sh_R": (28, -4, 0),
                    "el_L": (100, 0, 0), "el_R": (100, 0, 0), "knee_R": (-14, 0, 0), "hip_R": (8, 0, 0),
                    "head": (0, 4 * lean_sign, 0)}
            seq = [(0.0, base), (T * 0.5, dict(base, head=(-3, 4 * lean_sign, 0))), (T, base)]
        else:  # stand
            seq = [(0.0, {}), (T, {})]
        for t, pose in seq:
            fr = f0 + min(n, max(0, rnd(t * fps)))
            if seated_flag:
                pose = seated(pose)
            key_pose(F, fr, pose)


# --------------------------------------------------------------------------------------
# environments (all geometry merged into a handful of meshes)
# --------------------------------------------------------------------------------------
def build_garage(tag, world, car_xy, flicker):
    C = Style.col
    cx, cy = car_xy
    g = Geo()   # floor
    g.box((0, 10, -0.1), (50, 110, 0.2))
    make_obj(f"{tag}_floor", g, C("floor"), world)
    g = Geo()   # ceiling
    g.box((0, 10, 3.15), (50, 110, 0.3))
    make_obj(f"{tag}_ceiling", g, C("ceiling"), world)
    g = Geo()   # walls
    for sx in (-1, 1):
        g.box((sx * 25.25, 10, 1.65), (0.5, 110.5, 3.3))
    g.box((0, -45.25, 1.65), (50.5, 0.5, 3.3))
    g.box((0, 65.25, 1.65), (50.5, 0.5, 3.3))
    make_obj(f"{tag}_walls", g, C("body"), world)
    g = Geo()   # columns + beams
    xs = (-21.0, -7.0, 7.0, 21.0)
    ys = [-40.0 + 8 * k for k in range(14)]          # column rows every 8 m: y = -40 .. 64
    for x in xs:
        for y in ys:
            g.box((x, y, 1.5), (0.8, 0.8, 3.0))
    for y in ys:
        g.box((0, y, 2.72), (50, 0.5, 0.56))
    for x in xs:
        g.box((x, 10, 2.72), (0.5, 110, 0.56))
    make_obj(f"{tag}_cols", g, C("body"), world)
    # parking bay lines around the car (bays 2.8 m wide, the car sits in the bay centred on x=0)
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
    ty = [-44.0 + 4 * k for k in range(27)]
    if flicker:
        for x in (-3.5, 3.5):
            for y in ty:
                gg = Geo()
                gg.box((0, 0, 0), (0.12, 1.7, 0.06))
                tubes.append(make_obj(f"{tag}_tube", gg, C("light"), world, loc=(x, y, 2.95)))
        xs2 = (-10.5, 10.5)
    else:
        xs2 = (-10.5, -3.5, 3.5, 10.5)
    g = Geo()
    for x in xs2:
        for y in ty:
            g.box((x, y, 2.95), (0.12, 1.7, 0.06))
    make_obj(f"{tag}_tubes", g, C("light"), world)
    return tubes


def build_highway(tag, world):
    C = Style.col
    g = Geo()
    g.box((0, 120, -0.55), (400, 540, 0.8))
    make_obj(f"{tag}_ground", g, C("ground"), world)
    g = Geo()
    g.box((0, 120, -0.15), (16, 540, 0.3))
    make_obj(f"{tag}_road", g, C("floor"), world)
    g = Geo()
    for y in range(-140, 390, 6):
        for x in (-1.75, 1.75):
            g.box((x, y + 1.5, 0.012), (0.15, 3.0, 0.024))
    for x in (-5.5, 5.5):
        g.box((x, 120, 0.012), (0.18, 540, 0.024))
    make_obj(f"{tag}_lanes", g, C("line"), world)
    g = Geo()
    for sx in (-1, 1):
        g.box((sx * 8.8, 120, 0.72), (0.12, 540, 0.34))
        for y in range(-140, 390, 4):
            g.box((sx * 8.8, y, 0.4), (0.10, 0.10, 0.8))
    make_obj(f"{tag}_rails", g, C("body"), world)
    g = Geo()
    for y in range(-140, 390, 30):
        for sx in (-1, 1):
            g.box((sx * 10.5, y, 4.8), (0.2, 0.2, 9.6))
            g.box((sx * 8.8, y, 9.5), (3.4, 0.14, 0.14))
            g.box((sx * 7.2, y, 9.38), (0.9, 0.5, 0.14))
    make_obj(f"{tag}_poles", g, C("body"), world)
    g = Geo()
    for y in (70, 190, 310, -50):
        for sx in (-1, 1):
            g.box((sx * 9.6, y, 3.8), (0.55, 0.55, 7.6))
        g.box((0, y, 7.5), (19.8, 0.6, 0.7))
        g.box((-3.0, y - 0.35, 5.9), (6.2, 0.2, 2.2))
        g.box((4.2, y - 0.35, 5.9), (4.2, 0.2, 2.2))
    make_obj(f"{tag}_gantry", g, C("line"), world)
    rng = random.Random(11)
    g = Geo()
    for _ in range(80):
        side = rng.choice((-1, 1))
        x = side * rng.uniform(45, 170)
        y = rng.uniform(-100, 380)
        w, d, h = rng.uniform(10, 28), rng.uniform(10, 28), rng.uniform(12, 90)
        g.box((x, y, h / 2), (w, d, h))
    for _ in range(40):
        x = rng.uniform(-190, 190)
        y = rng.uniform(395, 430)
        w, d, h = rng.uniform(10, 26), rng.uniform(10, 24), rng.uniform(25, 120)
        g.box((x, y, h / 2), (w, d, h))
    make_obj(f"{tag}_skyline", g, C("ground"), world)


def tunnel_profile(inset=0.0, half_w=5.8, wall_h=3.0, arch_h=5.6, n=14):
    hw = half_w - inset
    ah = arch_h - inset
    pts = [(-hw, 0.0), (-hw, wall_h)]
    for k in range(1, n):
        a = math.pi - math.pi * k / n
        pts.append((hw * math.cos(a), wall_h + ah * math.sin(a)))
    pts += [(hw, wall_h), (hw, 0.0)]
    return pts


def build_tunnel(tag, world):
    C = Style.col
    y0, y1 = -60.0, 220.0
    g = Geo()
    g.box((0, (y0 + y1) / 2, -0.15), (11.8, y1 - y0, 0.3))
    make_obj(f"{tag}_road", g, C("floor"), world)
    g = Geo()
    g.tube_y(tunnel_profile(), y0, y1)
    make_obj(f"{tag}_shell", g, C("ground"), world)
    g = Geo()
    outer, inner = tunnel_profile(), tunnel_profile(inset=0.4)
    y = y0
    while y <= y1:
        g.tube_y(inner, y - 0.25, y + 0.25)
        g.ribbon(outer, inner, y - 0.25)
        g.ribbon(outer, inner, y + 0.25)
        y += 4.0
    make_obj(f"{tag}_ribs", g, C("body"), world)
    g = Geo()
    for yy in range(int(y0), int(y1), 4):
        for sx in (-1, 1):
            g.box((sx * 4.0, yy + 2.0, 6.82), (0.55, 1.3, 0.14))
    make_obj(f"{tag}_lamps", g, C("light"), world)
    g = Geo()
    for yy in range(int(y0), int(y1), 6):
        for x in (-1.9, 1.9):
            g.box((x, yy + 1.5, 0.012), (0.15, 3.0, 0.024))
    for x in (-4.4, 4.4):
        g.box((x, (y0 + y1) / 2, 0.012), (0.18, y1 - y0, 0.024))
    for sx in (-1, 1):
        g.box((sx * 5.3, (y0 + y1) / 2, 0.2), (1.0, y1 - y0, 0.4))
    make_obj(f"{tag}_lanes", g, C("line"), world)


def build_booth(tag, world):
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
    g.box((0, 1.06, 1.5), (0.3, 0.04, 0.3))
    g.cyl((0, 0.4, SEAT_Z - 0.025), 0.20, 0.05, seg=20)
    g.cyl((0, 0.4, 0.27), 0.035, 0.54, seg=10)
    g.cyl((0, 0.4, 0.015), 0.20, 0.03, seg=20)
    g.box((0, 0.86, 0.165), (0.62, 0.26, 0.03))
    for sx in (-1, 1):
        g.box((sx * 0.26, 0.86, 0.09), (0.03, 0.03, 0.15))
    make_obj(f"{tag}_stool", g, C("dark"), world)


# --------------------------------------------------------------------------------------
# per-shot build
# --------------------------------------------------------------------------------------
def noise(t, ph, amp):
    return amp * (0.6 * math.sin(2 * math.pi * 1.7 * t + ph[0]) + 0.4 * math.sin(2 * math.pi * 3.9 * t + ph[1]))


def resolve_car(sid, pv, recipe, cam, look):
    """-> None or (pos, yaw_deg)."""
    if "car_pos" in pv:
        return list(pv["car_pos"]), float(pv.get("car_yaw", 0.0))
    if "car_path" in pv:
        return list(pv["car_path"][0]), float(pv.get("car_yaw", 0.0))
    mode = recipe.get("car", "origin")
    yaw = float(pv.get("car_yaw", 0.0))
    if mode == "none":
        return None
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


def build_shot(shot, idx_in_env, f0, f1, fps):
    sid, env = shot["id"], shot["env"]
    if env not in ENV_X:
        raise SystemExit(f"{sid}: unknown env {env!r} (have {', '.join(ENV_X)})")
    pv = shot["previs"]
    recipe = dict(RECIPES.get(sid, dict(lens=32, car="at_lookat")))
    for k_json, k_rec in (("lens_mm", "lens"), ("speed", "speed"), ("handheld", "handheld"),
                          ("car_ease", "ease")):
        if k_json in pv:
            recipe[k_rec] = pv[k_json]
    fig_rec = dict(recipe.get("figure") or {})
    if "figure_path" in pv and not fig_rec:
        fig_rec = dict(action="stand")
    if "figure_action" in pv:
        fig_rec["action"] = pv["figure_action"]
    origin = (ENV_X[env], SHOT_Y_STEP * idx_in_env, 0.0)
    world = new_empty(f"{sid}_world", None, loc=origin)
    n = f1 - f0                       # key distance (last frame index - first frame index)
    T = n / fps
    cam_from, cam_to = pv["cam_from"], pv["cam_to"]
    look_from = pv["look_at"]
    look_to = pv.get("look_at_to", look_from)
    speed = 0.0 if "car_path" in pv else float(recipe.get("speed", 0.0))
    car_def = resolve_car(sid, pv, recipe, cam_from, look_from)
    car_xy = (car_def[0][0], car_def[0][1]) if car_def else (0.0, 0.0)

    # --- environment
    tubes = []
    if env == "garage":
        tubes = build_garage(sid, world, car_xy, recipe.get("flicker", False))
    elif env == "highway":
        build_highway(sid, world)
    elif env == "tunnel":
        build_tunnel(sid, world)
    elif env == "booth":
        build_booth(sid, world)

    def conv(f):
        return speed * (f - f0) / fps

    # --- car
    car = None
    if car_def:
        pos, yaw = car_def
        car = build_car(sid, world, pos, yaw, flame=bool(recipe.get("flame")))
        root = car["root"]
        with interp("LINEAR"):
            if "car_path" in pv:
                pts = pv["car_path"]
                ease = float(recipe.get("ease", pv.get("car_ease", 1.0)))
                seg_len = [math.dist(pts[i], pts[i + 1]) for i in range(len(pts) - 1)]
                total = sum(seg_len) or 1.0
                for f in range(f0, f1 + 1):
                    u = ((f - f0) / n) ** ease if n else 0.0
                    d = u * total
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
            # taillight ignition
            tl = recipe.get("taillight", "lit")
            if tl.startswith("ignite"):
                dim, lit = Style.col(0.10), Style.col("light")
                t_on = f0 + (rnd(0.30 * fps) if tl == "ignite_quick" else rnd(0.85 * n))
                for ob in (car["tail"], car["tail_core"]):
                    ob.color = dim
                    ob.keyframe_insert("color", frame=f0)
                    if tl == "ignite_quick":     # flicker on
                        for k, c_ in ((t_on - 4, dim), (t_on - 3, lit), (t_on - 2, dim), (t_on, lit)):
                            ob.color = c_
                            ob.keyframe_insert("color", frame=max(f0, k))
                    ob.color = lit
                    ob.keyframe_insert("color", frame=min(f1, t_on) if tl == "ignite_quick" else f0 + n)
        if car["flames"]:
            with interp("CONSTANT"):
                for ob in car["flames"]:
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
        if action == "lean" and car_def:
            rx = (math.cos(math.radians(yaw)), math.sin(math.radians(yaw)))
            lean_sign = 1.0 if (rx[0] * (car_def[0][0] - path[0][0]) + rx[1] * (car_def[0][1] - path[0][1])) > 0 else -1.0
        fig = build_figure(sid + "_man", world)
        animate_figure(fig, action, f0, f1, fps, path, yaw, seated_flag=bool(fig_rec.get("seated")),
                       lean_sign=lean_sign, appear=fig_rec.get("appear"))
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
    # --- camera
    cdata = bpy.data.cameras.new(f"{sid}_cam")
    cdata.lens = float(recipe.get("lens", 32))
    cdata.clip_start, cdata.clip_end = 0.03, 700.0
    cam = bpy.data.objects.new(f"{sid}_cam", cdata)
    bpy.context.scene.collection.objects.link(cam)
    cam.parent = world
    tgt = new_empty(f"{sid}_look", world)
    con = cam.constraints.new("TRACK_TO")
    con.target = tgt
    con.track_axis = "TRACK_NEGATIVE_Z"
    con.up_axis = "UP_Y"
    hh = float(recipe.get("handheld", 0.0))
    rng = random.Random(sid)
    ph = [[rng.uniform(0, 6.28) for _ in range(2)] for _ in range(6)]
    frames_keyed = list(range(f0, f1 + 1)) if hh > 0 else [f0, f1]
    with interp("LINEAR"):
        for f in frames_keyed:
            u = (f - f0) / n if n else 0.0
            t = (f - f0) / fps
            c = lerp(cam_from, cam_to, u)
            lk = lerp(look_from, look_to, u)
            c[1] += conv(f)
            lk[1] += conv(f)
            if hh > 0:
                c = [c[0] + noise(t, ph[0], hh), c[1] + noise(t, ph[1], hh * 0.6), c[2] + noise(t, ph[2], hh)]
                lk = [lk[0] + noise(t, ph[3], hh * 2), lk[1], lk[2] + noise(t, ph[4], hh * 2)]
            cam.location = c
            cam.keyframe_insert("location", frame=f)
            tgt.location = lk
            tgt.keyframe_insert("location", frame=f)
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
    full_run = not want and scale >= 100
    if args.out:
        out = Path(args.out)
    elif full_run:
        out = DEFAULT_OUT
    else:
        out = frames_dir.parent / "previs_partial.mp4"

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
