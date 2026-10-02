#!/usr/bin/env python3
"""Assemble out/clips/<shot>.mp4 (4 s Seedance clips) into out/final_ai.mp4 (stdlib + ffmpeg).

* every clip is conformed to 1280x720 / 24 fps (scale-to-fill + centre crop, SAR 1)
* for each shot of shotlist.json a window of exactly round-cut length is taken from its clip:
    window start = shot["use_from"] (seconds into the clip) if present,
                   else --trim-mode start|center|end (default center)
* the windows are joined with hard cuts; frame counts come from cumulative rounding of the shot
  durations, so the film is exactly format.duration_s * 24 = 360 frames (15.0 s)
* a clip shorter than its shot holds its last frame (and goes silent) for the missing frames and prints a WARNING on
  stderr; a clip that is not 16:9 is centre-cropped and also gets a WARNING
* audio (--audio keep|drop|silence): always an AAC track of 15.0 s; 'keep' cuts the matching audio
  window of every clip with a 40 ms fade at each cut (no pops); 'drop' and 'silence' both discard the
  clip audio and write a silent AAC track of the same length
"""
from __future__ import annotations

import argparse
import json
import math
import re
import shutil
import subprocess
import sys
from pathlib import Path

FPS = 24
OUT_W, OUT_H = 1280, 720
SAMPLE_RATE = 48000
SAMPLES_PER_FRAME = SAMPLE_RATE // FPS          # 2000: audio stays sample-exact against the video frames
FADE_SAMPLES = SAMPLE_RATE * 40 // 1000         # 40 ms = 1920 samples
EXIT_OK, EXIT_FAIL, EXIT_USAGE = 0, 1, 2
ID_RE = re.compile(r"^[A-Za-z0-9_-]+$")           # shot ids become file names: no path separators, no dots
TARGET_ASPECT = OUT_W / OUT_H
ASPECT_TOL = 0.02


class UsageError(Exception):
    pass


def load_shotlist(path: Path) -> dict:
    """Read and validate shotlist.json (ids are used in file names, so they are checked strictly)."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise UsageError(f"cannot read shotlist {path}: {e}")
    shots = data.get("shots") if isinstance(data, dict) else None
    if not isinstance(shots, list) or not shots:
        raise UsageError(f"{path} has no 'shots' list")
    seen = set()
    for i, s in enumerate(shots):
        sid = s.get("id") if isinstance(s, dict) else None
        if not isinstance(sid, str) or not ID_RE.fullmatch(sid):
            raise UsageError(f"shot #{i + 1}: invalid id {sid!r} (allowed: letters, digits, '_' and '-'; ids become file names)")
        if sid in seen:
            raise UsageError(f"duplicate shot id {sid!r} in {path}")
        seen.add(sid)
        dur = s.get("dur")
        if isinstance(dur, bool) or not isinstance(dur, (int, float)) or not math.isfinite(dur) or dur <= 0:
            raise UsageError(f"shot {sid}: 'dur' must be a positive number of seconds, got {dur!r}")
    return data


def half_up(x: float) -> int:
    return int(math.floor(x + 0.5 + 1e-9))


def ffprobe(path: Path) -> dict:
    try:
        out = subprocess.run(["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)],
                             capture_output=True, text=True, timeout=60)
    except FileNotFoundError:
        raise UsageError("ffprobe/ffmpeg not found in PATH")
    if out.returncode != 0 or not out.stdout.strip():
        raise UsageError(f"cannot read {path} (corrupt or not a video?): {out.stderr.strip()[:200]}")
    j = json.loads(out.stdout)
    v = next((s for s in j["streams"] if s.get("codec_type") == "video"), None)
    a = next((s for s in j["streams"] if s.get("codec_type") == "audio"), None)
    if v is None:
        raise UsageError(f"{path} has no video stream")
    dur = float(v.get("duration") or j["format"].get("duration") or 0)
    return {"duration": dur, "width": v.get("width"), "height": v.get("height"), "has_audio": a is not None,
            "fps": v.get("r_frame_rate")}


def shot_frames(shots: list, total_frames: int) -> list:
    """Per-shot frame counts from cumulative rounding (no drift, sum == total_frames)."""
    cum_ms, prev, counts = 0, 0, []
    for s in shots:
        cum_ms += round(s["dur"] * 1000)
        end = half_up(cum_ms * FPS / 1000)
        counts.append(end - prev)
        prev = end
    if prev != total_frames:
        raise UsageError(f"shot durations add up to {prev} frames but format.duration_s needs {total_frames}; fix shotlist.json")
    if any(c < 1 for c in counts):
        raise UsageError("a shot is shorter than one frame")
    return counts


def parse_use_from(shot: dict):
    """Optional per-shot 'use_from' -> float seconds (or None). Anything else is a clear usage error."""
    raw = shot.get("use_from")
    if raw is None:
        return None
    try:
        if isinstance(raw, bool):
            raise ValueError
        v = float(raw)
    except (TypeError, ValueError):
        raise UsageError(f"shot {shot['id']}: use_from must be a number (seconds into the clip), got {raw!r}")
    if not math.isfinite(v):
        raise UsageError(f"shot {shot['id']}: use_from must be a finite number, got {raw!r}")
    return v


def plan_shot(shot: dict, n: int, info: dict | None, trim_mode: str) -> dict:
    """Window selection for one shot. info None = clip missing (black card)."""
    p = {"id": shot["id"], "frames": n, "src_dur": None, "start_f": 0, "pad_f": 0, "note": "", "missing": info is None,
         "has_audio": bool(info and info["has_audio"]), "warnings": []}
    use_from = parse_use_from(shot)
    if info is None:
        p["note"] = "MISSING -> black card"
        return p
    # ffprobe prints 6 decimals (5 frames = 0.208333 s): floor() would lose a frame, so round to the nearest frame
    src_frames = max(1, half_up(info["duration"] * FPS))
    p["src_dur"], p["src_frames"] = info["duration"], src_frames
    win = n / FPS
    if use_from is not None:
        t0, how = use_from, "use_from"
    elif trim_mode == "start":
        t0, how = 0.0, "start"
    elif trim_mode == "end":
        t0, how = info["duration"] - win, "end"
    else:
        t0, how = (info["duration"] - win) / 2, "center"
    sf = half_up(t0 * FPS)
    notes = [how]
    hi = max(0, src_frames - n)
    if sf < 0 or sf > hi:
        notes.append(f"clamped from {sf / FPS:.3f}s")
        sf = min(max(sf, 0), hi)
    if src_frames < n:
        p["pad_f"] = n - src_frames
        notes.append(f"clip shorter than shot: last frame held for {p['pad_f']} frames")
        p["warnings"].append(f"shot {shot['id']}: clip is {info['duration']:.3f} s ({src_frames} frames) but the shot needs "
                             f"{win:.3f} s ({n} frames); the last frame is held for {p['pad_f']} frames")
    w, h = info.get("width"), info.get("height")
    if w and h and abs((w / h) / TARGET_ASPECT - 1) > ASPECT_TOL:
        notes.append(f"cropped (aspect {w / h:.2f} -> 16:9)")
        p["warnings"].append(f"shot {shot['id']}: clip is {w}x{h} (aspect {w / h:.2f}), not 16:9; it is scaled to fill and "
                             f"CENTRE-CROPPED to 1280x720, so part of the frame is lost")
    if not info["has_audio"]:
        notes.append("no audio stream")
    p["start_f"], p["note"] = sf, ", ".join(notes)
    return p


def build_filtergraph(plans: list, audio_mode: str, total_frames: int) -> tuple[str, list]:
    """-> (filter_complex, list of input clip paths in -i order). plans carry 'path' for existing clips."""
    inputs, parts, v_labels, a_labels = [], [], [], []
    keep = audio_mode == "keep"
    for i, p in enumerate(plans):
        n, L = p["frames"], p["frames"] * SAMPLES_PER_FRAME
        if p["missing"]:
            parts.append(f"color=c=black:s={OUT_W}x{OUT_H}:r={FPS},trim=end_frame={n},setpts=PTS-STARTPTS,setsar=1,format=yuv420p[v{i}]")
        else:
            k = len(inputs)
            inputs.append(p["path"])
            sf = p["start_f"]
            # take everything from the window start, clone the last frame a little beyond what is needed, then cut to
            # exactly n frames: the segment length is exact even when the probed duration is off by a frame
            parts.append(f"[{k}:v]setpts=PTS-STARTPTS,fps={FPS},trim=start_frame={sf},setpts=PTS-STARTPTS,"
                         f"tpad=stop_mode=clone:stop={p['pad_f'] + 2},trim=end_frame={n},setpts=PTS-STARTPTS,"
                         f"scale={OUT_W}:{OUT_H}:force_original_aspect_ratio=increase:flags=lanczos,crop={OUT_W}:{OUT_H},"
                         f"setsar=1,format=yuv420p[v{i}]")
        v_labels.append(f"[v{i}]")
        if keep:
            if p["missing"] or not p["has_audio"]:
                parts.append(f"anullsrc=r={SAMPLE_RATE}:cl=stereo,atrim=end_sample={L},asetpts=PTS-STARTPTS[a{i}]")
            else:
                a0 = p["start_f"] * SAMPLES_PER_FRAME
                # pad with silence BEFORE trimming: a window that starts after the end of a short audio track must
                # still yield L samples of silence (atrim on an already ended stream makes ffmpeg fail)
                parts.append(f"[{inputs.index(p['path'])}:a]asetpts=PTS-STARTPTS,aresample={SAMPLE_RATE},"
                             f"aformat=sample_fmts=fltp:channel_layouts=stereo,apad,"
                             f"atrim=start_sample={a0}:end_sample={a0 + L},asetpts=PTS-STARTPTS,"
                             f"afade=t=in:ss=0:ns={FADE_SAMPLES},afade=t=out:ss={L - FADE_SAMPLES}:ns={FADE_SAMPLES}[a{i}]")
            a_labels.append(f"[a{i}]")
    n_shots = len(plans)
    if keep:
        inter = "".join(f"{v}{a}" for v, a in zip(v_labels, a_labels))
        parts.append(f"{inter}concat=n={n_shots}:v=1:a=1[vcat][acat]")
        parts.append(f"[acat]atrim=end_sample={total_frames * SAMPLES_PER_FRAME},asetpts=PTS-STARTPTS[aout]")
    else:
        parts.append("".join(v_labels) + f"concat=n={n_shots}:v=1:a=0[vcat]")
        parts.append(f"anullsrc=r={SAMPLE_RATE}:cl=stereo,atrim=end_sample={total_frames * SAMPLES_PER_FRAME},asetpts=PTS-STARTPTS[aout]")
    parts.append(f"[vcat]trim=end_frame={total_frames},setpts=PTS-STARTPTS[vout]")
    return ";".join(parts), inputs


def measure_output(path: Path) -> dict:
    j = json.loads(subprocess.run(
        ["ffprobe", "-v", "error", "-count_frames", "-show_streams", "-show_format", "-of", "json", str(path)],
        capture_output=True, text=True, check=True).stdout)
    v = next(s for s in j["streams"] if s["codec_type"] == "video")
    a = next((s for s in j["streams"] if s["codec_type"] == "audio"), None)
    # decoded sample count of the audio track (exact, independent of container rounding)
    nbytes = len(subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-map", "0:a:0", "-f", "s16le", "-ac", "2",
                                 "-ar", str(SAMPLE_RATE), "-"], capture_output=True, check=True).stdout)
    return {"frames": int(v["nb_read_frames"]), "width": v["width"], "height": v["height"], "fps": v["r_frame_rate"],
            "pix_fmt": v["pix_fmt"], "vcodec": v["codec_name"], "format_duration": float(j["format"]["duration"]),
            "video_duration": float(v.get("duration") or 0),
            "acodec": a["codec_name"] if a else None, "audio_duration": float(a.get("duration") or 0) if a else None,
            "audio_decoded_s": nbytes / 4 / SAMPLE_RATE}


def build_parser() -> argparse.ArgumentParser:
    here = Path(__file__).resolve().parent
    p = argparse.ArgumentParser(prog="assemble_clips.py", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter,
                                epilog="shotlist.json may carry an optional per-shot \"use_from\": seconds into the 4 s clip where the window starts.")
    p.add_argument("--project-dir", type=Path, default=here.parent, help="default: parent of this script's directory")
    p.add_argument("--shotlist", type=Path, help="default <project-dir>/shotlist.json")
    p.add_argument("--clips-dir", type=Path, help="default <project-dir>/out/clips")
    p.add_argument("--output", type=Path, help="default <project-dir>/out/final_ai.mp4")
    p.add_argument("--trim-mode", choices=["start", "center", "end"], default="center",
                   help="window position when a shot has no use_from (default center)")
    p.add_argument("--audio", choices=["keep", "drop", "silence"], default="keep",
                   help="keep: per-shot audio windows with 40 ms fades; drop/silence: silent AAC track (default keep)")
    p.add_argument("--allow-missing", action="store_true", help="fill shots whose clip is missing with a black card (default: error)")
    p.add_argument("--crf", type=int, default=16, help="x264 crf (default 16)")
    p.add_argument("--preset", default="medium", help="x264 preset (default medium)")
    p.add_argument("--dry-run", action="store_true", help="print the plan table and the ffmpeg command, render nothing")
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    try:
        for tool in ("ffmpeg", "ffprobe"):
            if not shutil.which(tool):
                raise UsageError(f"{tool} not found in PATH")
        project = args.project_dir.resolve()
        shotlist = args.shotlist or project / "shotlist.json"
        clips_dir = args.clips_dir or project / "out" / "clips"
        output = args.output or project / "out" / "final_ai.mp4"
        data = load_shotlist(shotlist)
        shots = data["shots"]
        fmt = data.get("format", {})
        if int(fmt.get("fps", FPS)) != FPS:
            raise UsageError(f"shotlist fps {fmt.get('fps')} != {FPS}")
        total_frames = half_up(float(fmt.get("duration_s", sum(s["dur"] for s in shots))) * FPS)
        counts = shot_frames(shots, total_frames)

        missing = [s["id"] for s in shots if not (clips_dir / f"{s['id']}.mp4").is_file()]
        if missing and not args.allow_missing:
            raise UsageError(f"missing clip(s) for shot(s) {', '.join(missing)} in {clips_dir}. Generate them with generate_clips.py "
                             f"or pass --allow-missing to fill them with a black card.")
        plans = []
        for s, n in zip(shots, counts):
            path = clips_dir / f"{s['id']}.mp4"
            info = None if s["id"] in missing else ffprobe(path)
            p = plan_shot(s, n, info, args.trim_mode)
            p["path"] = str(path)
            if info and (info["width"], info["height"]) != (OUT_W, OUT_H):
                p["note"] += f", rescaled {info['width']}x{info['height']}"
            plans.append(p)

        print(f"{'shot':<5} {'frames':>6} {'cut s':>6} {'src dur s':>9}  {'window used (s)':<19} audio  note")
        for p in plans:
            win = "-" if p["missing"] else f"[{p['start_f'] / FPS:6.3f}, {(p['start_f'] + p['frames']) / FPS:6.3f}]"
            src = "-" if p["src_dur"] is None else f"{p['src_dur']:.3f}"
            aud = "-" if p["missing"] else ("yes" if p["has_audio"] else "no")
            print(f"{p['id']:<5} {p['frames']:>6} {p['frames'] / FPS:>6.3f} {src:>9}  {win:<19} {aud:<5}  {p['note']}")
        print(f"total {sum(counts)} frames = {sum(counts) / FPS:.3f} s @ {FPS} fps, audio mode: {args.audio}")
        for p in plans:
            for w in p["warnings"]:
                print(f"WARNING: {w}", file=sys.stderr)

        graph, inputs = build_filtergraph(plans, args.audio, total_frames)
        tmp = output.with_name(output.stem + ".partial.mp4")
        cmd = ["ffmpeg", "-v", "error", "-stats", "-y"]
        for path in inputs:
            cmd += ["-i", path]
        cmd += ["-filter_complex", graph, "-map", "[vout]", "-map", "[aout]",
                "-c:v", "libx264", "-preset", args.preset, "-crf", str(args.crf), "-pix_fmt", "yuv420p", "-profile:v", "high",
                "-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709",
                "-r", str(FPS), "-fps_mode", "cfr", "-frames:v", str(total_frames),
                "-c:a", "aac", "-b:a", "192k", "-ar", str(SAMPLE_RATE), "-ac", "2", "-t", f"{total_frames / FPS:.3f}",
                "-movflags", "+faststart", str(tmp)]
        if args.dry_run:
            print("\nffmpeg command (filter_complex shown separately):")
            print("  " + " ".join(c if c != graph else "<filter_complex>" for c in cmd))
            print("\nfilter_complex:\n  " + graph.replace(";", ";\n  "))
            return EXIT_OK
        output.parent.mkdir(parents=True, exist_ok=True)
        r = subprocess.run(cmd, text=True, stderr=subprocess.PIPE)
        if r.returncode != 0:
            tmp.unlink(missing_ok=True)
            lines = [l.strip() for l in re.split(r"[\r\n]+", r.stderr) if l.strip() and not re.match(r"(frame|size)=", l.strip())]
            print(f"ffmpeg failed (rc {r.returncode}):\n" + "\n".join(lines[-15:]), file=sys.stderr)
            return EXIT_FAIL
        m = measure_output(tmp)
        ok = (m["frames"] == total_frames and (m["width"], m["height"]) == (OUT_W, OUT_H) and m["fps"] == f"{FPS}/1"
              and m["acodec"] == "aac" and abs((m["audio_duration"] or 0) - total_frames / FPS) < 0.002
              and abs(m["audio_decoded_s"] - total_frames / FPS) < 0.025)   # AAC works in 1024-sample frames
        if not ok:
            print(f"verification FAILED, keeping {tmp}: {m}", file=sys.stderr)
            return EXIT_FAIL
        tmp.replace(output)
        print(f"\nwrote {output}\n  {m['vcodec']} {m['pix_fmt']} {m['width']}x{m['height']} {m['fps']} fps, {m['frames']} frames, "
              f"video {m['video_duration']:.3f} s; {m['acodec']} audio {m['audio_duration']:.3f} s (container), "
              f"{m['audio_decoded_s']:.3f} s decoded incl. AAC frame padding; file {output.stat().st_size / 1e6:.2f} MB")
        return EXIT_OK
    except UsageError as e:
        print(f"error: {e}", file=sys.stderr)
        return EXIT_USAGE


if __name__ == "__main__":
    sys.exit(main())
