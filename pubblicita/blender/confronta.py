"""Confronto visivo tra un clip bersaglio (es. shot Seedance) e il render blockout.

Affianca i fotogrammi dei due video agli stessi istanti in una griglia PNG:
una riga per istante, colonne "bersaglio | blockout" (piu' una sovrapposizione
al 50% con ``--overlay``). Serve ad allineare camera e tempi del blockout allo
shot AI. Non richiede Blender: usa ffmpeg/ffprobe, Pillow e numpy.

Esempi:
    python3 -m pubblicita.blender.confronta --target pubblicita/output/seedance/s03.mp4 \\
        --blockout pubblicita/output/blender/s03.mp4 --tempi 0,0.5,1,1.5 --out griglia.png
    python3 -m pubblicita.blender.confronta --target s03.mp4 --blockout s03.mp4 --n 5 --offset-frames 3 --overlay
    python3 -m pubblicita.blender.confronta --target s03.mp4 --blockout s03.mp4 --stima-offset 1.0

Convenzione dell'offset: l'istante t del bersaglio viene confrontato con
l'istante t + offset del blockout (offset positivo = il blockout e' in ritardo
e va "anticipato" saltandone l'inizio, cioe' "in" = offset * 24 nell'EDL).
Il blockout puo' anche essere un PNG (still di ``build_shot.py --still``).
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

FPS = 24
IMMAGINI = {".png", ".jpg", ".jpeg", ".webp"}


def _ffmpeg() -> str:
    return shutil.which("ffmpeg") or "/usr/bin/ffmpeg"


def _ffprobe() -> str:
    return shutil.which("ffprobe") or "/usr/bin/ffprobe"


def e_immagine(percorso: str | Path) -> bool:
    return Path(percorso).suffix.lower() in IMMAGINI


def info(percorso: str | Path) -> dict:
    """Durata (s), fps e dimensioni del primo stream video."""
    if e_immagine(percorso):
        with Image.open(percorso) as im:
            return {"duration": float("inf"), "fps": float(FPS), "width": im.width, "height": im.height}
    out = subprocess.run(
        [_ffprobe(), "-v", "error", "-select_streams", "v:0", "-show_entries",
         "stream=width,height,r_frame_rate,duration:format=duration", "-of", "json", str(percorso)],
        check=True, capture_output=True, text=True).stdout
    d = json.loads(out)
    st = d["streams"][0]
    num, den = (int(x) for x in st.get("r_frame_rate", "24/1").split("/"))
    dur = st.get("duration") or d.get("format", {}).get("duration") or 0
    return {"duration": float(dur), "fps": num / den if den else float(FPS),
            "width": int(st["width"]), "height": int(st["height"])}


def estrai(percorso: str | Path, t: float, larghezza: int, durata: float | None = None,
           fps: float = FPS) -> Image.Image:
    """Fotogramma all'istante ``t`` (secondi) ridimensionato a ``larghezza``."""
    if e_immagine(percorso):
        im = Image.open(percorso).convert("RGB")
        return im.resize((larghezza, round(im.height * larghezza / im.width / 2) * 2), Image.LANCZOS)
    if durata is not None and durata > 0:
        t = min(max(0.0, t), max(0.0, durata - 0.5 / fps))
    cmd = [_ffmpeg(), "-v", "error", "-ss", f"{max(0.0, t):.4f}", "-i", str(percorso), "-frames:v", "1",
           "-vf", f"scale={larghezza}:-2", "-f", "image2pipe", "-vcodec", "png", "pipe:1"]
    dati = subprocess.run(cmd, check=True, capture_output=True).stdout
    if not dati:
        raise RuntimeError(f"nessun fotogramma da {percorso} a t={t:.3f}s")
    from io import BytesIO

    return Image.open(BytesIO(dati)).convert("RGB")


def _font(dim: int):
    try:
        return ImageFont.load_default(size=dim)
    except TypeError:  # Pillow < 10.1
        return ImageFont.load_default()


def istanti_da_argomenti(tempi: str | None, frames: str | None, n: int | None, durata: float) -> list[float]:
    """Istanti (secondi) da --tempi, --frames (a 24 fps, centro del frame) o --n equidistanti."""
    if tempi:
        return [float(x) for x in tempi.split(",") if x.strip()]
    if frames:
        return [(int(x) + 0.5) / FPS for x in frames.split(",") if x.strip()]
    n = n or 4
    if not np.isfinite(durata) or durata <= 0:
        return [0.0]
    passo = durata / n
    return [round(passo * (i + 0.5), 3) for i in range(n)]


def griglia(target: str | Path, blockout: str | Path, istanti: list[float], offset: float = 0.0,
            larghezza: int = 480, overlay: bool = False) -> Image.Image:
    """Costruisce la griglia di confronto e la restituisce come immagine PIL."""
    it, ib = info(target), info(blockout)
    righe = []
    for t in istanti:
        a = estrai(target, t, larghezza, it["duration"], it["fps"])
        b = estrai(blockout, t + offset, larghezza, ib["duration"], ib["fps"])
        if b.size != a.size:
            b = b.resize(a.size, Image.LANCZOS)
        celle = [(a, f"bersaglio  t={t:.2f}s"), (b, f"blockout  t={t + offset:.2f}s  f={int((t + offset) * FPS)}")]
        if overlay:
            celle.append((Image.blend(a, b, 0.5), "sovrapposizione 50%"))
        righe.append(celle)
    cw, ch = righe[0][0][0].size
    barra = max(18, larghezza // 22)
    marg = 6
    ncol = len(righe[0])
    W = ncol * cw + (ncol + 1) * marg
    H = len(righe) * (ch + barra) + (len(righe) + 1) * marg
    tela = Image.new("RGB", (W, H), (24, 24, 26))
    dis = ImageDraw.Draw(tela)
    font = _font(max(11, barra - 6))
    for r, celle in enumerate(righe):
        y = marg + r * (ch + barra + marg)
        for c, (im, testo) in enumerate(celle):
            x = marg + c * (cw + marg)
            dis.text((x + 4, y + 2), testo, fill=(235, 235, 235), font=font)
            tela.paste(im, (x, y + barra))
    return tela


def _bordi(fotogrammi: np.ndarray) -> np.ndarray:
    """Modulo del gradiente normalizzato per ogni fotogramma (N, H, W)."""
    f = fotogrammi.astype(np.float32)
    gx = np.zeros_like(f)
    gy = np.zeros_like(f)
    gx[:, :, 1:-1] = f[:, :, 2:] - f[:, :, :-2]
    gy[:, 1:-1, :] = f[:, 2:, :] - f[:, :-2, :]
    g = np.sqrt(gx * gx + gy * gy)
    g -= g.mean(axis=(1, 2), keepdims=True)
    g /= g.std(axis=(1, 2), keepdims=True) + 1e-6
    return g


def leggi_grigi(percorso: str | Path, larghezza: int = 96, altezza: int = 54) -> np.ndarray:
    """Tutto il clip conformato a 24 fps, in scala di grigi e piccolo: array (N, H, W)."""
    if e_immagine(percorso):
        im = Image.open(percorso).convert("L").resize((larghezza, altezza))
        return np.asarray(im, dtype=np.uint8)[None]
    cmd = [_ffmpeg(), "-v", "error", "-i", str(percorso), "-vf",
           f"fps={FPS},scale={larghezza}:{altezza},format=gray", "-f", "rawvideo", "pipe:1"]
    dati = subprocess.run(cmd, check=True, capture_output=True).stdout
    return np.frombuffer(dati, dtype=np.uint8).reshape(-1, altezza, larghezza)


def stima_offset(target: str | Path, blockout: str | Path, massimo_s: float = 1.0) -> list[tuple[int, float]]:
    """Prova gli offset in frame entro +-``massimo_s`` e li ordina per somiglianza dei bordi.

    Restituisce [(offset_frame, punteggio), ...] dal migliore. E' una stima
    indicativa: blockout e render fotorealistico condividono soprattutto la
    composizione, quindi conviene sempre controllare la griglia a occhio.
    """
    a = _bordi(leggi_grigi(target))
    b = _bordi(leggi_grigi(blockout))
    m = int(round(massimo_s * FPS))
    risultati = []
    for off in range(-m, m + 1):
        idx_a = [i for i in range(len(a)) if 0 <= i + off < len(b)]
        if len(idx_a) < max(3, len(a) // 4):
            continue
        punteggi = [(a[i] * b[i + off]).mean() for i in idx_a]
        risultati.append((off, float(np.mean(punteggi))))
    risultati.sort(key=lambda x: -x[1])
    return risultati


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python3 -m pubblicita.blender.confronta",
                                description="Griglia di confronto bersaglio (shot AI) / blockout")
    p.add_argument("--target", required=True, help="clip bersaglio (es. shot Seedance) o immagine")
    p.add_argument("--blockout", required=True, help="render blockout (mp4 o PNG)")
    g = p.add_mutually_exclusive_group()
    g.add_argument("--tempi", help="istanti in secondi separati da virgola, es. 0,0.5,1.2")
    g.add_argument("--frames", help="frame (24 fps) separati da virgola, es. 0,12,23")
    g.add_argument("--n", type=int, help="numero di istanti equidistanti (default 4)")
    o = p.add_mutually_exclusive_group()
    o.add_argument("--offset", type=float, default=0.0, help="offset del blockout in secondi")
    o.add_argument("--offset-frames", type=int, help="offset del blockout in frame a 24 fps")
    p.add_argument("--larghezza", type=int, default=480, help="larghezza di ogni cella (px)")
    p.add_argument("--overlay", action="store_true", help="aggiunge la colonna di sovrapposizione al 50%%")
    p.add_argument("--stima-offset", type=float, metavar="SECONDI",
                   help="stima l'offset migliore entro +-SECONDI e lo usa per la griglia")
    p.add_argument("--out", help="PNG di uscita (default: confronto_<target>.png accanto al blockout)")
    args = p.parse_args(argv)

    offset = args.offset if args.offset_frames is None else args.offset_frames / FPS
    if args.stima_offset:
        classifica = stima_offset(args.target, args.blockout, args.stima_offset)
        if classifica:
            migliori = ", ".join(f"{o:+d}f ({s:.3f})" for o, s in classifica[:3])
            print(f"offset stimato: {classifica[0][0]:+d} frame  (migliori: {migliori})")
            offset = classifica[0][0] / FPS
    durata = info(args.target)["duration"]
    istanti = istanti_da_argomenti(args.tempi, args.frames, args.n, durata)
    img = griglia(args.target, args.blockout, istanti, offset, args.larghezza, args.overlay)
    out = Path(args.out) if args.out else Path(args.blockout).with_name(f"confronto_{Path(args.target).stem}.png")
    out.parent.mkdir(parents=True, exist_ok=True)
    img.save(out)
    print(f"griglia: {out}  ({len(istanti)} istanti, offset {offset:+.3f}s)")
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
