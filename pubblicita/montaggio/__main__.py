"""CLI del montaggio: ``python3 -m pubblicita.montaggio {render,beats,analyze,check}``."""
from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

from . import load, resolve
from .edl import EDLError
from .media import MediaError
from .ritmo import beats_table


def _cmd_render(a) -> int:
    from .render import render

    p = Path(a.edl)
    tl = resolve(load(p), base_dir=p.resolve().parent, edl_path=p)
    print(f"EDL ok: {len(tl.shots)} shot, {tl.total_frames} frame ({tl.duration_s:.3f} s) a {tl.fps} fps")
    res = render(tl, a.out_dir, crf=a.crf, preset=a.preset)
    for k in ("top", "bottom", "audio", "timeline"):
        if res.get(k):
            print(f"  {k:8s} {res[k]}")
    return 0


def _cmd_check(a) -> int:
    p = Path(a.edl)
    tl = resolve(load(p), base_dir=p.resolve().parent, check_media=not a.no_media, edl_path=p)
    _print_table([
        {"shot": s.id, "beats": s.beats, "start_frame": s.start_frame, "end_frame": s.end_frame,
         "frames": s.frames, "start_s": round(s.start_frame / tl.fps, 4), "end_s": round(s.end_frame / tl.fps, 4)}
        for s in tl.shots])
    print(f"totale: {tl.total_frames} frame = {tl.duration_s:.3f} s")
    return 0


def _print_table(rows: list[dict]) -> None:
    if not rows:
        return
    keys = list(rows[0].keys())
    fmt = lambda v: "-" if v is None else (f"{v:g}" if isinstance(v, float) else str(v))
    widths = {k: max(len(k), *(len(fmt(r[k])) for r in rows)) for k in keys}
    print("  ".join(k.rjust(widths[k]) for k in keys))
    for r in rows:
        print("  ".join(fmt(r[k]).rjust(widths[k]) for k in keys))


def _cmd_beats(a) -> int:
    rows = beats_table(a.pattern, a.bpm, a.fps)
    if a.json:
        print(json.dumps(rows, indent=2))
        return 0
    _print_table(rows)
    tot = rows[-1]["end_frame"]
    print(f"totale: {tot} frame = {tot / a.fps:.3f} s  (1 battito = {60 / a.bpm * a.fps:.4f} frame a {a.bpm:g} bpm)")
    return 0


def _cmd_analyze(a) -> int:
    from .analisi import detect_cuts

    res = detect_cuts(a.video, crop=a.crop, threshold=a.threshold, min_gap_frames=a.min_gap)
    if a.json:
        print(json.dumps(res, indent=2))
        return 0
    print(f"{res['video']}  crop={res['crop']}  soglia={res['threshold']}  {res['total_frames']} frame")
    _print_table([{"taglio": i + 1, "frame": c["frame"], "s": c["s"], "score": c["score"]}
                  for i, c in enumerate(res["cuts"])])
    print("durate (frame):", ",".join(map(str, res["durations_frames"])))
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python3 -m pubblicita.montaggio",
                                 description="Montaggio a tempo: EDL → tracce dei pannelli.")
    sub = ap.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("render", help="EDL → top.mp4, bottom.mp4, timeline.json [, audio.wav]")
    r.add_argument("--edl", required=True)
    r.add_argument("--out-dir", required=True)
    r.add_argument("--crf", type=int, default=10, help="qualità degli intermedi (≤12, default 10)")
    r.add_argument("--preset", default="fast")
    r.set_defaults(fn=_cmd_render)

    c = sub.add_parser("check", help="valida l'EDL e stampa la tabella dei tagli")
    c.add_argument("--edl", required=True)
    c.add_argument("--no-media", action="store_true", help="non aprire le sorgenti")
    c.set_defaults(fn=_cmd_check)

    b = sub.add_parser("beats", help="tabella dei tagli da un pattern di battiti")
    b.add_argument("--bpm", type=float, required=True)
    b.add_argument("--pattern", required=True, help='es. "1,0.5,0.5,1/3"')
    b.add_argument("--fps", type=int, default=24)
    b.add_argument("--json", action="store_true")
    b.set_defaults(fn=_cmd_beats)

    z = sub.add_parser("analyze", help="rileva i tagli di un video (scene detection)")
    z.add_argument("--video", required=True)
    z.add_argument("--crop", help="w:h:x:y, es. 1056:594:12:1070 per il pannello inferiore")
    z.add_argument("--threshold", type=float, default=0.3)
    z.add_argument("--min-gap", type=int, default=3, help="frame minimi tra due tagli")
    z.add_argument("--json", action="store_true")
    z.set_defaults(fn=_cmd_analyze)

    a = ap.parse_args(argv)
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(message)s")
    try:
        return a.fn(a)
    except (EDLError, MediaError, ValueError) as e:
        print(f"errore: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
