#!/usr/bin/env python
"""Placeholder videos for layout tests while the real renders do not exist yet.

Default: the Seedance stand-in (bottom card): teal-orange gradient, big text
'SEEDANCE 2.5 RENDER PENDING', the current shot id / environment / time-in-shot changing in sync
with shotlist.json, a light sweep and a flash at every cut.

--style grey makes the stand-in for the top card: a mid-grey flat-shaded 'blockout' look with the
same shot ids ('BLENDER PREVIS PENDING').

Usage (from the project dir):
  python compose/make_placeholder_bottom.py [--out PATH] [--shotlist shotlist.json] [--style teal|grey]
Default outputs: <scratch>/placeholder_bottom.mp4 (teal) or <scratch>/placeholder_top.mp4 (grey).
"""
import argparse
import json
import os
import subprocess
import sys

import numpy as np
from PIL import Image, ImageDraw, ImageFont

SCRATCH = "/tmp/claude-0/-home-user-tonno/4a068dc4-eaa2-5f84-917a-5a917d76cf58/scratchpad"
FONTS = ["/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
         "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"]


def font(size):
    for p in FONTS:
        if os.path.exists(p):
            return ImageFont.truetype(p, size)
    return ImageFont.load_default()


def shot_at(shots, t):
    for s in shots:
        if s["start"] <= t < s["start"] + s["dur"]:
            return s
    return shots[-1]


def centered(draw, y, text, f, fill, W):
    bb = draw.textbbox((0, 0), text, font=f)
    draw.text(((W - (bb[2] - bb[0])) / 2 - bb[0], y), text, font=f, fill=fill)


def text_overlay(shot, style, W, H, idx, nshots):
    im = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    title = "SEEDANCE 2.5 RENDER PENDING" if style == "teal" else "BLENDER PREVIS PENDING"
    shadow = (0, 0, 0, 110)
    white = (255, 255, 255, 255)
    f1, f2, f3 = font(54), font(250), font(46)
    for dx, dy in ((3, 3),):
        d.text((0, 0), "", font=f1)
    # title (two shadow passes for legibility)
    for off, col in ((4, shadow), (0, white)):
        bb = d.textbbox((0, 0), title, font=f1)
        d.text(((W - (bb[2] - bb[0])) / 2 - bb[0] + off, 128 + off), title, font=f1, fill=col)
        bb = d.textbbox((0, 0), shot["id"], font=f2)
        d.text(((W - (bb[2] - bb[0])) / 2 - bb[0] + off, 215 + off), shot["id"], font=f2, fill=col)
        sub = "%s  |  %.1f s  |  %d/%d" % (shot["env"], shot["dur"], idx + 1, nshots)
        bb = d.textbbox((0, 0), sub, font=f3)
        d.text(((W - (bb[2] - bb[0])) / 2 - bb[0] + off, 500 + off), sub, font=f3, fill=col)
    return np.asarray(im, dtype=np.float32)


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--shotlist", default=os.path.join(here, "..", "shotlist.json"))
    ap.add_argument("--style", choices=["teal", "grey"], default="teal")
    ap.add_argument("--out", default=None)
    ap.add_argument("--size", default="1280x720")
    ap.add_argument("--fps", type=int, default=24)
    ap.add_argument("--duration", type=float, default=None, help="default: shotlist format.duration_s")
    a = ap.parse_args()

    sl = json.load(open(a.shotlist))
    shots = sl["shots"]
    dur = a.duration or sl["format"]["duration_s"]
    W, H = (int(v) for v in a.size.lower().split("x"))
    fps = a.fps
    out = a.out or os.path.join(SCRATCH, "placeholder_bottom.mp4" if a.style == "teal" else "placeholder_top.mp4")
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    n = int(round(dur * fps))

    yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
    diag = (xx / W * 0.75 + yy / H * 0.25)                   # 0..1 diagonal coordinate
    overlays = [text_overlay(s, a.style, W, H, i, len(shots)) for i, s in enumerate(shots)]
    ids = {s["id"]: i for i, s in enumerate(shots)}

    cmd = ["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", "%dx%d" % (W, H),
           "-r", str(fps), "-i", "-", "-c:v", "libx264", "-preset", "fast", "-crf", "18", "-pix_fmt", "yuv420p",
           "-movflags", "+faststart", out]
    enc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    for i in range(n):
        t = i / fps
        s = shot_at(shots, t)
        k = ids[s["id"]]
        tin = t - s["start"]
        if a.style == "teal":
            # teal -> orange gradient whose phase shifts with each shot, plus a travelling light band
            ph = (diag + 0.07 * k + 0.02 * t) % 1.0
            tri = 1.0 - np.abs(2.0 * ph - 1.0)
            c0 = np.array([8, 66, 82], dtype=np.float32)
            c1 = np.array([236, 122, 38], dtype=np.float32)
            frame = c0 + (c1 - c0) * tri[..., None]
            band = np.exp(-(((xx / W) - ((t * 0.35 + 0.1 * k) % 1.3 - 0.15)) ** 2) / 0.004)[..., None]
            frame = frame + band * np.array([60, 70, 70], dtype=np.float32)
        else:
            # flat-shaded grey 'blockout': dark ceiling, mid wall, light floor and a few boxes that move with the shot
            frame = np.empty((H, W, 3), dtype=np.float32)
            frame[:] = (66, 66, 66)
            frame[: int(H * 0.38)] = (48, 48, 48)
            frame[int(H * 0.62):] = (92, 92, 92)
            bx = int((0.15 + 0.7 * ((tin / max(s["dur"], 1e-3) + 0.13 * k) % 1.0)) * W)
            frame[int(H * 0.42):int(H * 0.66), max(bx - 150, 0):min(bx + 150, W)] = (118, 118, 118)
            frame[int(H * 0.58):int(H * 0.66), max(bx - 150, 0):min(bx + 150, W)] = (84, 84, 84)
            frame += (np.sin(xx / W * 6.0 + 0.5 * k) * 4.0)[..., None]
        # flash at the cut
        if tin < 3.0 / fps:
            frame = frame + (1.0 - tin * fps / 3.0) * 90.0
        ov = overlays[k]
        a_ = ov[..., 3:4] / 255.0
        frame = frame * (1 - a_) + ov[..., :3] * a_
        # shot-local progress bar
        pw = int(W * 0.5 * min(tin / s["dur"], 1.0))
        frame[H - 56:H - 44, int(W * 0.25):int(W * 0.25) + pw] = (255, 255, 255)
        frame[H - 56:H - 44, int(W * 0.25) + pw:int(W * 0.75)] *= 0.55
        enc.stdin.write(np.clip(frame, 0, 255).astype(np.uint8).tobytes())
    enc.stdin.close()
    rc = enc.wait()
    if rc:
        sys.exit("ffmpeg failed (%d)" % rc)
    print("wrote", out, "(%d frames, %dx%d @%d fps, %.2fs)" % (n, W, H, fps, n / fps))


if __name__ == "__main__":
    main()
