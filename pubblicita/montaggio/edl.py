"""EDL di montaggio: lettura, validazione e risoluzione della timeline.

Formato (JSON)::

    {"fps": 24, "bpm": 115, "size": [1920, 1080],
     "audio": {"src": null | "musica.wav", "offset_s": 0},
     "shots": [
        {"id": "s01", "frames": 8,            # oppure "beats": 1
         "top":    {"src": "blockout_01.mp4", "in": 0, "speed": 1.0},
         "bottom": {"src": "seedance/s01.mp4", "in": 0, "speed": 1.0},
         "note": ""}
     ]}

- ``in`` è l'indice di frame (a 24 fps) nella sorgente già conformata a 24 fps.
- ``speed`` > 1 accelera, < 1 rallenta (la sorgente consumata è frames × speed).
- Top e bottom di uno shot hanno sempre la stessa durata: la durata è dello shot.
- Percorsi relativi: prima rispetto alla cartella dell'EDL, poi alla cartella corrente.
- Oltre a ``src`` (video o immagine fissa) una sorgente può essere ``{"color": "#202428"}``,
  utile come segnaposto finché un clip non esiste.
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from pathlib import Path

from . import media
from .ritmo import boundaries

FPS = 24


class EDLError(ValueError):
    """EDL non valida: il messaggio indica lo shot e il problema."""


@dataclass
class Source:
    track: str
    src: Path | None
    color: str | None
    in_frame: int
    speed: float
    info: media.MediaInfo | None = None

    def last_needed(self, frames: int) -> int:
        """Ultimo frame sorgente (indice a 24 fps) toccato da uno shot di ``frames`` frame."""
        return self.in_frame + int(math.ceil((frames - 1) * self.speed - 1e-9))

    def to_json(self) -> dict:
        d = {"in": self.in_frame, "speed": self.speed}
        if self.src is not None:
            d["src"] = str(self.src)
        else:
            d["color"] = self.color
        return d


@dataclass
class Shot:
    id: str
    index: int
    start_frame: int
    end_frame: int
    beats: float | None
    top: Source
    bottom: Source
    note: str = ""

    @property
    def frames(self) -> int:
        return self.end_frame - self.start_frame


@dataclass
class Timeline:
    fps: int
    bpm: float
    size: tuple[int, int]
    shots: list[Shot]
    audio_src: Path | None = None
    audio_offset_s: float = 0.0
    edl_path: Path | None = None
    warnings: list[str] = field(default_factory=list)

    @property
    def total_frames(self) -> int:
        return self.shots[-1].end_frame if self.shots else 0

    @property
    def duration_s(self) -> float:
        return self.total_frames / self.fps

    def to_json(self) -> dict:
        fps = self.fps
        return {
            "fps": fps,
            "bpm": self.bpm,
            "size": list(self.size),
            "total_frames": self.total_frames,
            "duration_s": round(self.duration_s, 6),
            "cuts_frames": [s.end_frame for s in self.shots[:-1]],
            "cuts_s": [round(s.end_frame / fps, 4) for s in self.shots[:-1]],
            "audio": {"src": str(self.audio_src) if self.audio_src else None,
                      "offset_s": self.audio_offset_s},
            "shots": [
                {
                    "id": s.id,
                    "index": s.index,
                    "start_frame": s.start_frame,
                    "end_frame": s.end_frame,
                    "frames": s.frames,
                    "start_s": round(s.start_frame / fps, 4),
                    "end_s": round(s.end_frame / fps, 4),
                    "beats": s.beats,
                    "top": s.top.to_json(),
                    "bottom": s.bottom.to_json(),
                    "note": s.note,
                }
                for s in self.shots
            ],
            "warnings": self.warnings,
        }


def _resolve(path: str, base: Path | None) -> Path:
    p = Path(path).expanduser()
    if p.is_absolute():
        return p
    if base is not None and (base / p).exists():
        return (base / p).resolve()
    if p.exists():
        return p.resolve()
    return (base / p) if base is not None else p


def _where_searched(path: str, base: Path | None) -> str:
    if Path(path).expanduser().is_absolute():
        return "percorso assoluto"
    dirs = ([str(base)] if base is not None else []) + [str(Path.cwd())]
    return "cercata in: " + ", ".join(dirs)


def load(path: str | Path) -> dict:
    p = Path(path)
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise EDLError(f"EDL inesistente: {p}") from None
    except json.JSONDecodeError as e:
        raise EDLError(f"EDL non è JSON valido ({p}): {e}") from None
    return data


def resolve(edl: dict, base_dir: str | Path | None = None, check_media: bool = True,
            edl_path: Path | None = None) -> Timeline:
    """Valida l'EDL e calcola i confini di ogni shot in frame.

    Con ``check_media`` legge ogni sorgente con ffprobe e verifica che ``in`` + durata
    (tenendo conto di ``speed``) non superi la fine del clip.
    """
    if not isinstance(edl, dict):
        raise EDLError("l'EDL deve essere un oggetto JSON")
    base = Path(base_dir) if base_dir is not None else None
    fps = edl.get("fps", FPS)
    if fps != FPS:
        raise EDLError(f"fps={fps}: la pipeline lavora solo a {FPS} fps")
    bpm = edl.get("bpm", 115)
    if not isinstance(bpm, (int, float)) or bpm <= 0:
        raise EDLError(f"bpm non valido: {bpm!r}")
    size = edl.get("size", [1920, 1080])
    if (not isinstance(size, (list, tuple)) or len(size) != 2
            or not all(isinstance(v, int) and v > 0 and v % 2 == 0 for v in size)):
        raise EDLError(f"size non valida: {size!r} (servono due interi pari, es. [1920, 1080])")
    shots_in = edl.get("shots")
    if not isinstance(shots_in, list) or not shots_in:
        raise EDLError("l'EDL non contiene shot ('shots' vuoto o mancante)")

    durations = []
    ids = set()
    for i, s in enumerate(shots_in):
        sid = str(s.get("id") or f"s{i + 1:02d}") if isinstance(s, dict) else f"#{i + 1}"
        if not isinstance(s, dict):
            raise EDLError(f"shot {sid}: deve essere un oggetto")
        if sid in ids:
            raise EDLError(f"shot {sid}: id duplicato")
        ids.add(sid)
        has_f, has_b = "frames" in s, "beats" in s
        if has_f == has_b:
            raise EDLError(f"shot {sid}: serve esattamente uno tra 'frames' e 'beats'")
        if has_f:
            v = s["frames"]
            if not isinstance(v, int) or isinstance(v, bool) or v <= 0:
                raise EDLError(f"shot {sid}: 'frames' deve essere un intero positivo (trovato {v!r})")
            durations.append(("frames", v))
        else:
            v = s["beats"]
            if not isinstance(v, (int, float)) or isinstance(v, bool) or v <= 0:
                raise EDLError(f"shot {sid}: 'beats' deve essere un numero positivo (trovato {v!r})")
            durations.append(("beats", v))
        for track in ("top", "bottom"):
            if not isinstance(s.get(track), dict):
                raise EDLError(f"shot {sid}: manca la sorgente '{track}'")
    try:
        cuts = boundaries(durations, bpm, fps)
    except ValueError as e:
        raise EDLError(str(e)) from None

    tl = Timeline(fps, bpm, (size[0], size[1]), [], edl_path=edl_path)
    info_cache: dict[Path, media.MediaInfo] = {}
    for s, c in zip(shots_in, cuts):
        sid = str(s.get("id") or f"s{c.index + 1:02d}")
        srcs = {}
        for track in ("top", "bottom"):
            srcs[track] = _source(sid, track, s[track], base, check_media, c.frames, info_cache)
        tl.shots.append(Shot(sid, c.index, c.start_frame, c.end_frame, c.beats,
                             srcs["top"], srcs["bottom"], str(s.get("note", ""))))

    audio = edl.get("audio") or {}
    if not isinstance(audio, dict):
        raise EDLError("'audio' deve essere un oggetto {\"src\": ..., \"offset_s\": ...}")
    if audio.get("src"):
        ap = _resolve(audio["src"], base)
        if check_media and not ap.exists():
            raise EDLError(f"audio: file mancante: {audio['src']} ({_where_searched(audio['src'], base)})")
        tl.audio_src = ap
    off = audio.get("offset_s", 0) or 0
    if not isinstance(off, (int, float)):
        raise EDLError(f"audio: offset_s non valido: {off!r}")
    tl.audio_offset_s = float(off)
    return tl


def _source(sid, track, d, base, check_media, frames, cache) -> Source:
    where = f"shot {sid} ({track})"
    in_frame = d.get("in", 0)
    if not isinstance(in_frame, int) or isinstance(in_frame, bool) or in_frame < 0:
        raise EDLError(f"{where}: 'in' deve essere un indice di frame intero ≥ 0 (trovato {in_frame!r})")
    speed = d.get("speed", 1.0)
    if not isinstance(speed, (int, float)) or isinstance(speed, bool) or not (0.05 <= speed <= 20):
        raise EDLError(f"{where}: 'speed' fuori intervallo (0.05–20): {speed!r}")
    if d.get("src"):
        path = _resolve(str(d["src"]), base)
        src = Source(track, path, None, in_frame, float(speed))
        if check_media:
            if not path.exists():
                raise EDLError(f"{where}: sorgente mancante: {d['src']} ({_where_searched(d['src'], base)})")
            if path not in cache:
                try:
                    cache[path] = media.probe(path)
                except media.MediaError as e:
                    raise EDLError(f"{where}: sorgente illeggibile: {e}") from None
            src.info = cache[path]
            avail = src.info.frames_at(FPS)
            last = src.last_needed(frames)
            if last >= avail:
                raise EDLError(
                    f"{where}: in={in_frame} + {frames} frame (speed {speed}) arriva al frame "
                    f"{last}, oltre la fine della sorgente ({avail} frame a {FPS} fps): {path.name}")
        return src
    if d.get("color"):
        return Source(track, None, str(d["color"]), in_frame, float(speed))
    raise EDLError(f"{where}: manca 'src' (oppure 'color' per un segnaposto)")
