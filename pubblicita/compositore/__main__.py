"""CLI del compositore.

    python3 -m pubblicita.compositore --top top.mp4 --bottom bottom.mp4 --out spot.mp4 \\
        [--audio musica.wav | --audio-from-bottom] [--config mio.json] [--duration 14] [--still 2.6 ...]
    python3 -m pubblicita.compositore spot --edl edl.json --out spot.mp4 [--config ...] [--work-dir DIR]
"""
from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path

from pubblicita.montaggio.edl import EDLError
from pubblicita.montaggio.media import MediaError

from .config import DEFAULT_LAYOUT, load_layout
from .render import compose


def _progress(enabled: bool):
    if not enabled:
        return None
    state = {"t": 0.0}

    def cb(n, total):
        now = time.time()
        if n == total or now - state["t"] > 2:
            state["t"] = now
            print(f"\r  frame {n}/{total}", end="" if n < total else "\n", file=sys.stderr, flush=True)
    return cb


def _common(ap: argparse.ArgumentParser) -> None:
    ap.add_argument("--config", help=f"JSON fuso sopra il layout di default ({DEFAULT_LAYOUT.name})")
    ap.add_argument("--out", required=True, help="file .mp4 (oppure .png con --still)")
    ap.add_argument("--duration", type=float, help="durata in secondi (default: quella del pannello inferiore)")
    ap.add_argument("--no-audio-track", action="store_true", help="senza audio non aggiungere la traccia muta")
    ap.add_argument("--quiet", action="store_true")


def main_compose(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="python3 -m pubblicita.compositore",
                                 description="Impagina due video nei pannelli dello spot 9:16.")
    ap.add_argument("--top", required=True, help="video del pannello superiore (blockout Blender)")
    ap.add_argument("--bottom", required=True, help="video del pannello inferiore (render finale)")
    ap.add_argument("--audio", help="traccia audio (tagliata/allungata alla durata, fade-out finale)")
    ap.add_argument("--audio-from-bottom", action="store_true", help="usa l'audio del video inferiore")
    ap.add_argument("--still", type=float, nargs="+", metavar="SEC",
                    help="scrive solo i frame ai tempi indicati come PNG (anteprima rapida)")
    _common(ap)
    a = ap.parse_args(argv)
    cfg = load_layout(a.config)
    res = compose(a.top, a.bottom, a.out, cfg, audio=a.audio, audio_from_bottom=a.audio_from_bottom,
                  duration=a.duration, mute_track=not a.no_audio_track, stills=a.still,
                  progress_cb=_progress(not a.quiet))
    for p in res["outputs"]:
        print(p)
    if not a.quiet:
        print(f"{res['frames']} frame ({res['duration_s']:.3f} s) in {res['seconds']:.1f} s", file=sys.stderr)
    return 0


def main_spot(argv: list[str]) -> int:
    from pubblicita.montaggio import load, resolve
    from pubblicita.montaggio.render import render

    ap = argparse.ArgumentParser(prog="python3 -m pubblicita.compositore spot",
                                 description="Montaggio (EDL → tracce) + impaginazione in un solo comando.")
    ap.add_argument("--edl", required=True)
    ap.add_argument("--work-dir", help="cartella per tracce e timeline (default: <out>_montaggio/)")
    ap.add_argument("--audio", help="sostituisce l'audio dell'EDL")
    _common(ap)
    a = ap.parse_args(argv)
    edl = Path(a.edl)
    tl = resolve(load(edl), base_dir=edl.resolve().parent, edl_path=edl)
    out = Path(a.out)
    work = Path(a.work_dir) if a.work_dir else out.with_name(out.stem + "_montaggio")
    if not a.quiet:
        print(f"montaggio: {len(tl.shots)} shot, {tl.total_frames} frame → {work}", file=sys.stderr)
    tracks = render(tl, work)
    cfg = load_layout(a.config)
    audio = a.audio or tracks.get("audio")
    res = compose(tracks["top"], tracks["bottom"], out, cfg, audio=audio,
                  duration=a.duration or tl.duration_s, mute_track=not a.no_audio_track,
                  progress_cb=_progress(not a.quiet))
    for p in res["outputs"]:
        print(p)
    return 0


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(message)s")
    try:
        if argv and argv[0] == "spot":
            return main_spot(argv[1:])
        return main_compose(argv)
    except (EDLError, MediaError, ValueError, FileNotFoundError) as e:
        print(f"errore: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
