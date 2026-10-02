#!/usr/bin/env python3
"""contact_sheet.py - first / middle / last frame of every shot from the previs PNG sequence.

  <venv>/bin/python previs/contact_sheet.py --frames-dir <dir with f_0000.png..> --out sheet.png [--cols 3] [--width 480]
Needs Pillow only. Frame ranges come from ../shotlist.json (same rounding as build_previs.py).
"""
import argparse
import json
import math
import os
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

HERE = Path(__file__).resolve().parent


def rnd(x):
    return int(math.floor(x + 0.5 + 1e-9))


def main():
    ap = argparse.ArgumentParser(description="Contact sheet (first/middle/last frame per shot) of the previs frames.")
    ap.add_argument("--shotlist", default=str(HERE.parent / "shotlist.json"))
    ap.add_argument("--frames-dir", default=os.environ.get("PREVIS_FRAMES_DIR") or str(Path(tempfile.gettempdir()) / "previs_frames"))
    ap.add_argument("--out", default="previs_sheet.png")
    ap.add_argument("--width", type=int, default=480, help="width of one thumbnail in px")
    ap.add_argument("--shots", default="", help="subset, e.g. S01,S02")
    ap.add_argument("--per-shot", type=int, default=3, help="frames per shot (default 3: first/middle/last)")
    a = ap.parse_args()
    cfg = json.load(open(a.shotlist))
    fps = cfg["format"]["fps"]
    want = {x.strip().upper() for x in a.shots.split(",") if x.strip()}
    rows = []
    for s in cfg["shots"]:
        if want and s["id"] not in want:
            continue
        f0 = rnd(s["start"] * fps)
        f1 = rnd((s["start"] + s["dur"]) * fps) - 1
        k = max(2, a.per_shot)
        picks = [f0 + rnd((f1 - f0) * i / (k - 1)) for i in range(k)]
        rows.append((s, picks))
    fd = Path(a.frames_dir)
    first = Image.open(fd / f"f_{rows[0][1][0]:04d}.png")
    tw = a.width
    th = round(tw * first.height / first.width)
    pad, lab = 4, 20
    W = pad + (tw + pad) * len(rows[0][1])
    H = pad + (th + lab + pad) * len(rows)
    sheet = Image.new("RGB", (W, H), (20, 20, 20))
    d = ImageDraw.Draw(sheet)
    try:
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 13)
    except OSError:
        font = ImageFont.load_default()
    for r, (s, picks) in enumerate(rows):
        y = pad + r * (th + lab + pad)
        d.text((pad + 2, y + 3), f"{s['id']} {s['env']}  {s['camera'][:110]}", fill=(235, 235, 235), font=font)
        for c, fr in enumerate(picks):
            im = Image.open(fd / f"f_{fr:04d}.png").convert("RGB").resize((tw, th), Image.LANCZOS)
            sheet.paste(im, (pad + c * (tw + pad), y + lab))
    sheet.save(a.out)
    print("wrote", a.out, sheet.size)


if __name__ == "__main__":
    main()
