#!/usr/bin/env python
"""Measure the animated wave-line background of the layout reference ad.

Reads a reference video (NOT stored in the project), traces the thin wave lines
that are visible in the three background gaps (above the top card, between the
cards, below the bottom card) over time, and writes a compact keyframed model to
compose/wave_model.json, which compose_ad.py renders.

Usage (from the project dir):
  <python> compose/measure_waves.py --ref /path/to/ref.mp4 [--out compose/wave_model.json]

Seeds below are approximate anchor points (x, y at t=6.5 s, 720x1280 reference
pixels) of each visible wave segment; the tracer snaps to the real pixels.
"""
import argparse, json, os, subprocess, sys, tempfile, glob
import numpy as np
from PIL import Image
from numpy.lib.stride_tricks import sliding_window_view

W, H = 720, 1280
REGIONS = {"top": (0, 223), "mid": (626, 711), "bot": (1112, 1279)}
# areas occupied by header text / logo (their strokes must not be mistaken for waves)
MASKS = [(268, 452, 140, 200), (324, 398, 66, 142)]
STEP = 8                     # x spacing of the stored control points
KEY_TIMES = [0.0, 2.5, 5.0, 7.5, 10.0, 12.5, 15.0]   # uniform; the 15.0 key is read from the last measured frame
SEED_T = 6.5

# name, kind (t=teal-ish, g=grey), region, seed anchors (x, y) at the curve's seed time (default SEED_T);
# y=None means "the single run of that kind in the column" (only used where one curve of that kind exists)
SEEDS = [
    ("T1_light_teal",  "t", "top", [(48, 36.1), (264, 20.2), (480, 72.5), (696, 0.8)]),
    ("T2_dark_teal",   "t", "top", [(48, 55.4), (240, 111.7), (456, 34.4), (648, 124.3)]),
    ("T3_grey",        "g", "top", [(24, None), (120, None), (600, None)], 14.5),
    ("T5_teal_corner", "t", "top", [(696, 203.7)]),
    ("M1_grey",        "g", "mid", [(72, 628.5), (192, 669.5), (288, 693.4), (456, 643.9), (648, 661.2)]),
    ("M2a_teal_hill",  "t", "mid", [(144, 699.2), (240, 666.2), (360, 697.8)]),
    ("M2b_teal_rise",  "t", "mid", [(600, 687.0), (648, 651.1), (672, 636.1)]),
    ("B1a_teal_left",  "t", "bot", [(24, 1160.5), (96, 1146.1), (144, 1125.4)]),
    ("B1b_teal_right", "t", "bot", [(360, 1123.5), (480, 1163.7), (552, 1144.3)]),
    ("B2_teal_low",    "t", "bot", [(48, 1248.5), (240, 1225.7), (360, 1261.0), (648, 1243.9), (696, 1222.5)]),
]


def detect(img, region):
    """Return {x: [(yc, kind)]} line runs in the region (kind t=teal-ish, g=grey)."""
    y0, y1 = REGIONS[region]
    sub = img[y0:y1 + 1]
    s = sub.sum(axis=2)
    pad = np.pad(s, ((12, 12), (0, 0)), mode="edge")
    bgb = sliding_window_view(pad, 25, axis=0).max(axis=2)
    dark = bgb - s
    r, g, b = sub[..., 0], sub[..., 1], sub[..., 2]
    teal = (g - r) > 14
    for (xa, xb, ya, yb) in MASKS:
        ya_, yb_ = max(ya, y0) - y0, min(yb, y1) - y0
        if yb_ >= ya_:
            dark[ya_:yb_ + 1, xa:xb + 1] = 0
    out = {}
    for x in range(W):
        col = dark[:, x]
        ys = np.where(col > 45)[0]
        items = []
        if len(ys):
            runs, s0, p = [], ys[0], ys[0]
            for v in ys[1:]:
                if v != p + 1:
                    runs.append((s0, p)); s0 = v
                p = v
            runs.append((s0, p))
            for a, bb in runs:
                if bb - a > 9:
                    continue
                w = col[a:bb + 1]
                yc = float((np.arange(a, bb + 1) * w).sum() / w.sum())
                idx = a + int(np.argmax(w))
                items.append((yc + y0, "t" if teal[idx, x] else "g"))
        out[x] = items
    return out


def pick(items, kind, pred, tol):
    best = None
    for (y, k) in items:
        if k != kind:
            continue
        d = 0.0 if pred is None else abs(y - pred)
        if (pred is None or d <= tol) and (best is None or d < best[0]):
            best = (d, y)
    return None if best is None else best[1]


def trace_seed(runs, kind, anchors):
    """Trace one curve along x at the seed time; returns {x: y} for x on the STEP grid."""
    pts = {}
    # snap anchors
    for (xa, ya) in anchors:
        xa = int(round(xa / STEP) * STEP)
        y = pick(runs.get(xa, []), kind, ya, 6)
        if y is not None:
            pts[xa] = y
    if not pts:
        raise RuntimeError("seed %r not found" % (anchors,))
    for (x0, y0) in sorted(pts.items()):
        for direction in (1, -1):
            x = x0
            hist = [(x0, y0)]
            miss = 0
            while True:
                x += direction * STEP
                if x < 0 or x > W - 1:
                    break
                if len(hist) >= 2:
                    (xa, ya), (xb, yb) = hist[-2], hist[-1]
                    slope = (yb - ya) / (xb - xa)
                    tol = 4.0 + 6.0 * min(abs(slope), 1.0)
                else:
                    slope, tol = 0.0, 11.0
                pred = hist[-1][1] + slope * (x - hist[-1][0])
                y = pick(runs.get(x, []), kind, pred, tol)
                if y is None:
                    miss += 1
                    if miss > 6:
                        break
                    hist.append((x, pred))      # coast through crossings / occlusions
                    continue
                miss = 0
                pts.setdefault(x, y)
                hist.append((x, pts[x]))
    return pts


def follow(runs, kind, prev, grid):
    """Follow a curve to the next frame. `prev` is the full previous curve {x: y} on `grid`.
    Snap to the nearest run where one exists; elsewhere carry the previous y shifted by the
    median displacement of the nearest snapped points (temporally consistent gap filling)."""
    found = {}
    for x in grid:
        yy = pick(runs.get(x, []), kind, prev[x], 9.0)
        if yy is not None:
            found[x] = yy
    if len(found) < 6:
        return dict(prev)
    fx = np.array(sorted(found)); disp = np.array([found[x] - prev[x] for x in fx])
    out = {}
    for x in grid:
        if x in found:
            out[x] = found[x]
        else:
            near = np.argsort(np.abs(fx - x))[:4]
            out[x] = prev[x] + float(np.median(disp[near]))
    return smooth(out, grid)


def cr_time(K, t):
    """Catmull-Rom interpolation across uniformly spaced keyframes K[k] (arrays) at time t."""
    n = len(KEY_TIMES)
    f = min(max(t / (KEY_TIMES[1] - KEY_TIMES[0]), 0.0), n - 1.0)
    j = min(int(f), n - 2); u = f - j
    p0, p1, p2, p3 = K[max(j - 1, 0)], K[j], K[j + 1], K[min(j + 2, n - 1)]
    return 0.5 * (2 * p1 + (-p0 + p2) * u + (2 * p0 - 5 * p1 + 4 * p2 - p3) * u * u + (-p0 + 3 * p1 - 3 * p2 + p3) * u ** 3)


def smooth(curve, grid):
    arr = np.array([curve[x] for x in grid])
    sm = arr.copy()
    sm[1:-1] = 0.25 * arr[:-2] + 0.5 * arr[1:-1] + 0.25 * arr[2:]
    return {x: float(v) for x, v in zip(grid, sm)}


def fill_gaps(pts, grid):
    """Interior gaps of the seed trace: cubic through the nearest valid neighbours."""
    xs = np.array(sorted(pts)); ys = np.array([pts[x] for x in xs])
    out = {}
    for x in grid:
        if x in pts:
            out[x] = pts[x]; continue
        near = np.argsort(np.abs(xs - x))[:8]
        co = np.polyfit(xs[near] - x, ys[near], 3 if len(near) >= 6 else 1)
        out[x] = float(np.polyval(co, 0.0))
    return smooth(out, grid)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--ref", required=True, help="reference video (720x1280) to measure")
    ap.add_argument("--out", default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "wave_model.json"))
    ap.add_argument("--workdir", default=None, help="temp dir for extracted frames")
    a = ap.parse_args()
    work = a.workdir or tempfile.mkdtemp(prefix="waves_")
    os.makedirs(work, exist_ok=True)
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", a.ref, "-vf", "fps=2", os.path.join(work, "w_%03d.png")], check=True)
    files = sorted(glob.glob(os.path.join(work, "w_*.png")))
    nfr = len(files)
    times = [i * 0.5 for i in range(nfr)]
    frames_runs = []
    for f in files:
        img = np.array(Image.open(f).convert("RGB")).astype(float)
        frames_runs.append({reg: detect(img, reg) for reg in REGIONS})
    curves = []
    max_err, worst = 0.0, None
    for entry in SEEDS:
        name, kind, reg, anchors = entry[:4]
        seed_i = int(round((entry[4] if len(entry) > 4 else SEED_T) / 0.5))
        seed_pts = trace_seed(frames_runs[seed_i][reg], kind, anchors)
        grid = list(range(min(seed_pts), max(seed_pts) + 1, STEP))
        seed_curve = fill_gaps(seed_pts, grid)
        series = [None] * nfr
        series[seed_i] = seed_curve
        for i in range(seed_i + 1, nfr):
            series[i] = follow(frames_runs[i][reg], kind, series[i - 1], grid)
        for i in range(seed_i - 1, -1, -1):
            series[i] = follow(frames_runs[i][reg], kind, series[i + 1], grid)
        print("%-16s x-range %3d..%3d (%d pts, %d gap-filled)" % (name, grid[0], grid[-1], len(grid), len(grid) - len(seed_pts)))
        kf = []
        for kt in KEY_TIMES:
            i = min(nfr - 1, int(round(kt / 0.5)))
            kf.append([round(series[i][x], 1) for x in grid])
        K = np.array(kf)
        for i in range(nfr):   # error of the keyframe model (Catmull-Rom in time, as compose_ad.py renders it)
            interp = cr_time(K, times[i])
            e = float(np.abs(interp - np.array([series[i][x] for x in grid])).mean())
            if e > max_err:
                max_err, worst = e, (name, times[i])
        curves.append({"name": name, "kind": kind, "region": reg, "x": grid, "y": kf})
    model = {
        "note": "Wave-line model measured on the layout reference (720x1280 units). y[k][i] is the curve height at x[i] "
                "at KEY_TIMES[k]; render with Catmull-Rom in x and smooth interpolation in time (ping-pong beyond %.1fs)." % KEY_TIMES[-1],
        "key_times": KEY_TIMES, "step_px": STEP, "curves": curves,
    }
    with open(a.out, "w") as f:
        json.dump(model, f, separators=(",", ":"))
    print("wrote", a.out, "bytes", os.path.getsize(a.out), "| worst per-frame mean |keyframe model - measured|: %.2f px (at %s)" % (max_err, worst))


if __name__ == "__main__":
    main()
