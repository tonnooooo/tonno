"""Renderizza uno shot blockout da una spec JSON (da lanciare con Blender).

Uso:
    blender -b --factory-startup --python pubblicita/blender/build_shot.py -- \\
        --spec pubblicita/blender/esempi/strada_notte.json --out pubblicita/output/blender/strada.mp4 \\
        [--res 1280x720] [--samples 24] [--frames 0-47] [--still 12] [--preview] \\
        [--save-blend scena.blend] [--keep-frames]

Produce un mp4 H.264 a 24 fps senza audio (CRF dalla spec, default 14) e un
resoconto ``<out>.render.json``. Con ``--still N`` renderizza solo il frame N
in PNG (se ``--out`` finisce in .mp4 si usa lo stesso nome con .png).
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

RADICE = Path(__file__).resolve().parents[2]
if str(RADICE) not in sys.path:
    sys.path.insert(0, str(RADICE))

from pubblicita.blender import moto, spec as S  # noqa: E402


def argomenti(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="build_shot.py", description="Render di uno shot blockout da spec JSON")
    p.add_argument("--spec", required=True, help="file JSON della spec (vedi SPEC.md)")
    p.add_argument("--out", required=True, help="mp4 di uscita (o PNG con --still)")
    p.add_argument("--res", help="risoluzione WxH (default dalla spec, 1280x720)")
    p.add_argument("--samples", type=int, help="campioni Cycles (default dalla spec, 24)")
    p.add_argument("--frames", help="intervallo a-b di frame (base 0, estremi inclusi)")
    p.add_argument("--still", type=int, help="renderizza solo questo frame in PNG")
    p.add_argument("--preview", action="store_true", help="anteprima veloce: 640x360, 8 campioni, niente motion blur")
    p.add_argument("--save-blend", help="salva anche la scena .blend per aprirla in Blender")
    p.add_argument("--keep-frames", action="store_true", help="conserva i PNG intermedi accanto all'mp4")
    return p.parse_args(argv)


def codifica_mp4(cartella: Path, primo: int, out: Path, crf: int) -> None:
    ffmpeg = shutil.which("ffmpeg") or "/usr/bin/ffmpeg"
    cmd = [ffmpeg, "-y", "-loglevel", "error", "-framerate", str(S.FPS), "-start_number", str(primo),
           "-i", str(cartella / "f_%05d.png"),
           "-vf", "scale=out_color_matrix=bt709:out_range=tv,format=yuv420p",
           "-c:v", "libx264", "-preset", "medium", "-crf", str(crf), "-r", str(S.FPS),
           "-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709",
           "-an", "-movflags", "+faststart", str(out)]
    subprocess.run(cmd, check=True)


def main(argv: list[str]) -> int:
    args = argomenti(argv)
    try:
        spec = S.carica(args.spec)
    except S.SpecErrore as exc:
        print(exc, file=sys.stderr)
        return 2
    meta, render = spec["meta"], spec["render"]
    if args.preview:
        meta["resolution"] = [640, 360]
        render["samples"] = 8
        render["motion_blur"] = False
    if args.res:
        meta["resolution"] = list(moto.risoluzione(args.res))
    if args.samples:
        render["samples"] = int(args.samples)
    frames = int(meta["frames"])

    import bpy  # noqa: F401  (disponibile solo dentro Blender)
    from pubblicita.blender import kit

    t0 = time.time()
    kit.costruisci_scena(spec)
    t_scena = time.time() - t0
    out = Path(args.out).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    if args.save_blend:
        bpy.ops.wm.save_as_mainfile(filepath=str(Path(args.save_blend).resolve()))

    resoconto = {"spec": str(Path(args.spec).resolve()), "id": meta["id"], "fps": S.FPS,
                 "resolution": meta["resolution"], "samples": render["samples"],
                 "scene_seconds": round(t_scena, 2), "blender": bpy.app.version_string}

    if args.still is not None:
        if not 0 <= args.still < frames:
            print(f"--still {args.still} fuori dallo shot (0-{frames - 1})", file=sys.stderr)
            return 2
        png = out.with_suffix(".png") if out.suffix.lower() != ".png" else out
        t1 = time.time()
        kit.renderizza_frame(str(png), args.still)
        dt = time.time() - t1
        print(f"STILL {png} frame={args.still} {dt:.2f}s (scena {t_scena:.2f}s)")
        resoconto.update(still=args.still, file=str(png), seconds_per_frame=round(dt, 2))
        png.with_suffix(".render.json").write_text(json.dumps(resoconto, indent=2), encoding="utf-8")
        return 0

    a, b = moto.range_frames(args.frames, frames)
    tmp = Path(tempfile.mkdtemp(prefix=f"blockout_{meta['id']}_"))
    tempi = []
    try:
        for f in moto.iter_frame(a, b):
            t1 = time.time()
            kit.renderizza_frame(str(tmp / f"f_{f:05d}.png"), f)
            tempi.append(time.time() - t1)
            print(f"FRAME {f} {tempi[-1]:.2f}s", flush=True)
        codifica_mp4(tmp, a, out, int(render.get("crf", 14)))
        if args.keep_frames:
            dest = out.with_suffix("")
            dest = dest.parent / (dest.name + "_frames")
            if dest.exists():
                shutil.rmtree(dest)
            shutil.copytree(tmp, dest)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    medio = sum(tempi) / len(tempi)
    resoconto.update(frames=[a, b], file=str(out), seconds_per_frame=round(medio, 2),
                     render_seconds=round(sum(tempi), 2))
    out.with_suffix(".render.json").write_text(json.dumps(resoconto, indent=2), encoding="utf-8")
    print(f"MP4 {out} frame {a}-{b} ({b - a + 1}) media {medio:.2f}s/frame, scena {t_scena:.2f}s")
    return 0


if __name__ == "__main__":
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    try:
        codice = main(argv)
    except SystemExit:
        raise
    except Exception:  # Blender altrimenti uscirebbe con codice 0 anche dopo un errore
        import traceback

        traceback.print_exc()
        codice = 1
    if codice:
        sys.exit(codice)
