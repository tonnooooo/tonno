#!/usr/bin/env python3
"""End-to-end tests for generate_clips.py / assemble_clips.py against mock_server.py (no real API, no network).

Run:   python test_adapter.py [--keep] [--workdir DIR]
Uses a fake random canary API key and a throw-away project copy under the scratchpad (or a temp dir);
the real project's out/clips and out/final_ai.mp4 are never touched (checked at the end).
"""
from __future__ import annotations

import argparse
import array
import base64
import json
import os
import re
import secrets
import shutil
import struct
import subprocess
import sys
import tempfile
import time
import traceback
import urllib.error
import urllib.parse
import urllib.request
import zlib
from pathlib import Path

HERE = Path(__file__).resolve().parent
REAL_PROJECT = HERE.parent
GEN, ASM, MOCK = HERE / "generate_clips.py", HERE / "assemble_clips.py", HERE / "mock_server.py"
SCRATCH = Path("/tmp/claude-0/-home-user-tonno/4a068dc4-eaa2-5f84-917a-5a917d76cf58/scratchpad")
CANARY = "sk-canary-" + secrets.token_hex(12)
WRONG = "sk-wrongkey-" + secrets.token_hex(10)
OUTPUTS: list = []          # every stdout/stderr captured from the tools under test (scanned for the canary)
TESTS: list = []
W: Path                     # work dir
PROJ: Path                  # throw-away project copy
MOCK_URL = ""
_opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def test(fn):
    TESTS.append(fn)
    return fn


def check(cond, msg="assertion failed"):
    if not cond:
        raise AssertionError(msg)


# ----------------------------------------------------------------------------- plumbing
def mock_call(method, path, body=None, headers=None, ua=None):
    req = urllib.request.Request(MOCK_URL + path, method=method, data=None if body is None else json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json", **(headers or {})})
    if ua:
        req.add_header("User-Agent", ua)
    try:
        with _opener.open(req, timeout=30) as r:
            raw = r.read()
            return r.status, raw
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def mjson(method, path, body=None, **kw):
    st, raw = mock_call(method, path, body, **kw)
    return st, json.loads(raw.decode() or "null")


def reqs(kind="api"):
    return [r for r in mjson("GET", "/__mock/requests")[1] if r["kind"] == kind]


def posts():
    return [r for r in reqs() if r["method"] == "POST"]


def stats():
    return mjson("GET", "/__mock/stats")[1]


def reset():
    mjson("POST", "/__mock/reset", {})


def config(**kw):
    mjson("POST", "/__mock/config", kw)


def tool_env(key=CANARY):
    env = {k: v for k, v in os.environ.items()
           if k.upper() not in ("EPHONE_API_KEY", "EPHONE_BASE_URL", "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY")}
    env.update({"PYTHONDONTWRITEBYTECODE": "1", "NO_PROXY": "127.0.0.1,localhost", "EPHONE_BASE_URL": MOCK_URL})
    if key is not None:
        env["EPHONE_API_KEY"] = key
    return env


def run(script, *args, key=CANARY, extra_env=None, timeout=300):
    env = tool_env(key)
    env.update(extra_env or {})
    p = subprocess.run([sys.executable, str(script), *map(str, args)], capture_output=True, text=True, env=env, timeout=timeout)
    OUTPUTS.append(f"$ {script.name} {' '.join(map(str, args))}\n{p.stdout}\n{p.stderr}")
    return p.returncode, p.stdout, p.stderr


def gen(*args, **kw):
    base = ["--project-dir", PROJ, "--poll-interval", "0.15", "--retry-base-delay", "0.05"]
    return run(GEN, *base, *args, **kw)


def asm(*args, **kw):
    return run(ASM, "--project-dir", PROJ, *args, **kw)


def sidecar(clips: Path, shot: str) -> dict:
    return json.loads((clips / f"{shot}.json").read_text())


def ffprobe_json(path: Path, count=False):
    cmd = ["ffprobe", "-v", "error", *(["-count_frames"] if count else []), "-show_streams", "-show_format", "-of", "json", str(path)]
    return json.loads(subprocess.run(cmd, capture_output=True, text=True, check=True).stdout)


def raw_frame(path: Path, n: int) -> bytes:
    return subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-vf", f"select=eq(n\\,{n})", "-fps_mode", "passthrough",
                           "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "gray", "-"], capture_output=True, check=True).stdout


def mad(a: bytes, b: bytes) -> float:
    check(len(a) == len(b) and len(a) > 0, f"frame size mismatch {len(a)} vs {len(b)}")
    return sum(abs(x - y) for x, y in zip(a, b)) / len(a)


def pcm(path: Path) -> array.array:
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-map", "0:a:0", "-ac", "1", "-ar", "48000", "-f", "s16le", "-"],
                         capture_output=True, check=True).stdout
    a = array.array("h")
    a.frombytes(raw)
    return a


def tone_hz(samples, a, b) -> float:
    seg = samples[a:b]
    cross = sum(1 for i in range(1, len(seg)) if (seg[i - 1] < 0) != (seg[i] < 0))
    return cross / 2 / ((b - a) / 48000)


def mean_volume(path: Path) -> float:
    p = subprocess.run(["ffmpeg", "-v", "info", "-i", str(path), "-map", "0:a:0", "-af", "volumedetect", "-f", "null", "-"],
                       capture_output=True, text=True)
    m = re.search(r"mean_volume:\s*(-?[\d.]+|-inf)", p.stderr)
    check(m, "volumedetect printed nothing")
    return float(m.group(1))


def png_file(path: Path):
    def chunk(tag, data):
        c = struct.pack(">I", len(data)) + tag + data
        return c + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
    raw = b"".join(b"\x00" + bytes([200, 60, 20]) * 8 for _ in range(8))
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 8, 8, 8, 2, 0, 0, 0))
                     + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


def assert_final_ok(path: Path, audio_tol=0.001):
    j = ffprobe_json(path, count=True)
    v = next(s for s in j["streams"] if s["codec_type"] == "video")
    a = next(s for s in j["streams"] if s["codec_type"] == "audio")
    check(int(v["nb_read_frames"]) == 360, f"frames {v['nb_read_frames']} != 360")
    check((v["width"], v["height"]) == (1280, 720), f"size {v['width']}x{v['height']}")
    check(v["r_frame_rate"] == "24/1" and v["avg_frame_rate"] == "24/1", f"fps {v['r_frame_rate']}/{v['avg_frame_rate']}")
    check(v["codec_name"] == "h264" and v["pix_fmt"] == "yuv420p", f"{v['codec_name']} {v['pix_fmt']}")
    check(abs(float(j["format"]["duration"]) - 15.0) < 0.001, f"format duration {j['format']['duration']}")
    check(a["codec_name"] == "aac", f"audio codec {a['codec_name']}")
    check(abs(float(a["duration"]) - 15.0) <= audio_tol, f"audio stream duration {a['duration']} != 15.0")
    decoded = len(pcm(path)) / 48000
    check(abs(decoded - 15.0) < 0.025, f"decoded audio {decoded:.4f}s (more than one AAC frame off 15.0)")
    with open(path, "rb") as f:                              # +faststart: moov must precede mdat
        head = f.read(64 * 1024)
    check(0 <= head.find(b"moov") < head.find(b"mdat") if b"mdat" in head else head.find(b"moov") >= 0, "moov not at file start (no +faststart)")
    return j


# ----------------------------------------------------------------------------- tests
@test
def t01_help():
    for s in (GEN, ASM, MOCK):
        rc, out, err = run(s, "--help")
        check(rc == 0 and "usage:" in out, f"{s.name} --help rc={rc}")


@test
def t02_probe_lists_models_and_sends_nothing_paid():
    reset()
    rc, out, err = gen("--probe")
    check(rc == 0, f"rc={rc} {err}")
    check("doubao-seedance-2-5-260628" in out and "doubao-seedream-5-0-pro-260628" in out, out)
    check("gpt-4o" not in out and "claude" not in out, "probe printed non-seedance/seedream models")
    r = reqs()
    check(len(r) == 1 and r[0]["method"] == "GET" and r[0]["path"] == "/v1/models" and r[0]["auth"] == "ok", r)
    check(not posts(), "probe must not POST")


@test
def t03_dry_run_sends_zero_requests():
    reset()
    rc, out, err = gen("--dry-run", "--shots", "S05")
    check(rc == 0, f"rc={rc} {err}")
    check("<REDACTED>" in out and "DRY RUN: nothing was sent" in out, out)
    check("87,300 tokens" in out and "CNY 6.11" in out and "USD 0.87" in out, "estimate missing: " + out)
    check('"duration": 4' in out and '"model": "doubao-seedance-2-5-260628"' in out and '"seed"' not in out, out)
    check("No text, no logos, no watermark" in out, "look.negative not appended")
    rc, out, err = gen("--dry-run", key=None)                     # no key needed, all 12 shots
    check(rc == 0 and out.count("=== S") == 12, f"rc={rc}")
    check("BLOCKED" in out and "A real run would be BLOCKED" in out, "default caps should flag 12 clips")
    check(len(mjson("GET", "/__mock/requests")[1]) == 0, "dry-run touched the network")


@test
def t04_no_yes_means_no_post():
    reset()
    clips = W / "clips_noyes"
    rc, out, err = gen("--shots", "S01", "--clips-dir", clips)
    check(rc == 2 and "--yes" in err, f"rc={rc} {err}")
    check(len(mjson("GET", "/__mock/requests")[1]) == 0, "requests were sent without --yes")
    check(not clips.exists() or not list(clips.iterdir()), "files written without --yes")


@test
def t05_duration_below_4_rejected_client_side_and_by_mock():
    reset()
    for d in ("3", "1", "0", "-1"):
        rc, out, err = gen("--shots", "S01", "--duration", d, "--yes", "--clips-dir", W / "clips_dur")
        check(rc == 2 and "minimum of 4" in err, f"duration {d}: rc={rc} {err}")
    rc, out, err = gen("--shots", "S01", "--duration", "31", "--yes", "--clips-dir", W / "clips_dur")
    check(rc == 2, "duration 31 should be rejected")
    check(len(mjson("GET", "/__mock/requests")[1]) == 0, "short duration reached the network")
    # the mock itself is faithful to the real API: <4 is a 400
    body = {"model": "doubao-seedance-2-5-260628", "content": [{"type": "text", "text": "x"}], "duration": 3}
    st, j = mjson("POST", "/doubao/api/v3/contents/generations/tasks", body, headers={"Authorization": "Bearer " + CANARY})
    check(st == 400 and j["error"]["param"] == "duration", f"{st} {j}")
    body["duration"], body["seed"] = 4, 1
    st, j = mjson("POST", "/doubao/api/v3/contents/generations/tasks", body, headers={"Authorization": "Bearer " + CANARY})
    check(st == 400 and j["error"]["param"] == "seed", f"mock must reject seed: {st} {j}")
    reset()


@test
def t06_budget_caps():
    reset()
    c = W / "clips_budget"
    rc, out, err = gen("--yes", "--clips-dir", c)                                   # 12 clips > default 3
    check(rc == 3 and "budget-max-clips" in err + out, f"rc={rc} {out}{err}")
    rc, out, err = gen("--yes", "--shots", "S01", "--budget-max-cny", "5", "--clips-dir", c)   # 6.11 > 5
    check(rc == 3 and "budget-max-cny" in err + out, f"rc={rc} {out}{err}")
    rc, out, err = gen("--yes", "--shots", "S01", "S02", "--budget-max-clips", "1", "--clips-dir", c)
    check(rc == 3, f"rc={rc}")
    rc, out, err = gen("--yes", "--shots", "S01", "S02", "S03", "S04", "--budget-max-cny", "40", "--clips-dir", c)  # 4 clips > 3 and 24.4 CNY
    check(rc == 3, f"rc={rc}")
    rc, out, err = gen("--dry-run", "--shots", "S01", "--budget-max-cny", "6.2", "--budget-max-clips", "1", "--clips-dir", c)
    check(rc == 0 and "-> OK" in out, "6.11 CNY must fit a 6.2 cap: " + out)
    check(len(mjson("GET", "/__mock/requests")[1]) == 0, "a blocked run sent requests")
    check(not c.exists() or not list(c.iterdir()), "a blocked run wrote files")


@test
def t07_generate_3_shots_ephone_ark():
    reset()
    c = PROJ / "out" / "clips"
    rc, out, err = gen("--shots", "S01", "S02", "S03", "--yes")
    check(rc == 0, f"rc={rc}\n{out}\n{err}")
    for s in ("S01", "S02", "S03"):
        check((c / f"{s}.mp4").stat().st_size > 10_000, f"{s}.mp4 missing")
        sc = sidecar(c, s)
        check(sc["task_id"].startswith("cgt-") and sc["state"] == "downloaded" and sc["profile"] == "ephone-ark", sc)
        check(sc["prompt"].endswith("No text, no logos, no watermark, no subtitles, no brand names."), sc["prompt"][-80:])
        check(sc["request"]["body"]["duration"] == 4 and sc["estimate"]["tokens"] == 87300, sc["estimate"])
    p = posts()
    check(len(p) == 3 and all(r["path"] == "/doubao/api/v3/contents/generations/tasks" and r["auth"] == "ok" for r in p), p)
    for r in p:
        b = r["body"]
        check(b["model"] == "doubao-seedance-2-5-260628" and b["duration"] == 4 and b["resolution"] == "720p" and b["ratio"] == "16:9"
              and b["generate_audio"] is True and b["watermark"] is False and "seed" not in b, b)
        check(b["content"][0]["type"] == "text", b["content"])
    cdn = reqs("cdn")
    check(len(cdn) == 3 and all(r["status"] == 200 and "Python-urllib" not in (r["ua"] or "") and "Mozilla" in r["ua"] for r in cdn),
          [(r["status"], r["ua"]) for r in cdn])
    check(stats()["cdn_rejections"] == 0, "CDN rejected the adapter's user agent")
    # prove the mock's CDN does reject the default urllib UA (what the adapter must work around)
    st, raw = mock_call("GET", "/cdn/whatever.mp4?sig=x", ua="Python-urllib/3.11")
    check(st == 403 and b"bot user agent" in raw, f"{st} {raw[:80]}")
    st, raw = mock_call("GET", "/cdn/whatever.mp4?sig=x", ua="Mozilla/5.0")
    check(st == 404, "browser UA must pass the UA gate")
    j = ffprobe_json(c / "S01.mp4")
    check(any(s["codec_type"] == "audio" for s in j["streams"]), "mock clip has no audio tone")


@test
def t08_generate_3_shots_ephone_task():
    reset()
    c = W / "clips_task"
    rc, out, err = gen("--shots", "S01,S02", "S03", "--yes", "--profile", "ephone-task", "--clips-dir", c)
    check(rc == 0, f"rc={rc}\n{out}\n{err}")
    p = posts()
    check(len(p) == 3 and all(r["path"] == "/v1/task/submit" for r in p), p)
    for r in p:
        inp = r["body"]["input"]
        check(r["body"]["model"] == "doubao-seedance-2-5-260628" and inp["duration"] == 4 and "seed" not in inp, r["body"])
    for s in ("S01", "S02", "S03"):
        sc = sidecar(c, s)
        check(sc["task_id"].startswith("task_") and sc["state"] == "downloaded" and sc["profile"] == "ephone-task", sc)
        check((c / f"{s}.mp4").stat().st_size > 10_000)
    check(all(f"/v1/task/{sidecar(c, s)['task_id']}" in [r["path"] for r in reqs() if r["method"] == "GET"] for s in ("S01", "S02", "S03")))


@test
def t09_resume_task_does_not_resubmit():
    for profile, path, clips, shot in (("ephone-ark", "/doubao/api/v3/contents/generations/tasks", PROJ / "out" / "clips", "S05"),
                                        ("ephone-task", "/v1/task/submit", W / "clips_task", "S06")):
        body = {"model": "doubao-seedance-2-5-260628", "content": [{"type": "text", "text": "x"}], "duration": 4}
        if profile == "ephone-task":
            body = {"model": body["model"], "input": {"content": body["content"], "duration": 4}}
        st, j = mjson("POST", path, body, headers={"Authorization": "Bearer " + CANARY})
        check(st == 200 and j["id"], f"raw submit failed {st} {j}")
        before = stats()["posts"]
        reset_log_before = len(posts())
        rc, out, err = gen("--resume-task", j["id"], "--shot", shot, "--profile", profile, "--clips-dir", clips)
        check(rc == 0, f"{profile} resume rc={rc}\n{out}\n{err}")
        check(stats()["posts"] == before and len(posts()) == reset_log_before, "resume must not POST")
        check((clips / f"{shot}.mp4").stat().st_size > 10_000 and sidecar(clips, shot)["task_id"] == j["id"], "resume result missing")
    rc, out, err = gen("--resume-task", "cgt-abc")
    check(rc == 2 and "--shot" in err, f"resume without --shot: rc={rc} {err}")
    rc, out, err = gen("--resume-task", "cgt-nope", "--shot", "S07", "--clips-dir", W / "clips_resume404", "--max-poll-errors", "2")
    check(rc == 1 and not (W / "clips_resume404" / "S07.mp4").exists(), f"unknown task id: rc={rc}\n{out}\n{err}")
    check(sidecar(W / "clips_resume404", "S07")["task_id"] == "cgt-nope", "task id must be persisted even for a failing resume")


@test
def t10_skip_existing_and_force_keeps_old_task_id():
    reset()
    c = PROJ / "out" / "clips"
    old = sidecar(c, "S01")["task_id"]
    rc, out, err = gen("--shots", "S01", "S02", "S03", "--yes")
    check(rc == 0 and out.count("skip") >= 3 and not posts(), f"rc={rc}\n{out}")
    rc, out, err = gen("--shots", "S01", "--yes", "--force")
    check(rc == 0 and len(posts()) == 1, f"rc={rc}\n{out}")
    sc = sidecar(c, "S01")
    check(sc["task_id"] != old and old in sc["previous_tasks"], sc["previous_tasks"])


@test
def t11_timeout_keeps_task_id_and_rerun_resumes_instead_of_resubmitting():
    reset()
    c = W / "clips_timeout"
    config(polls_to_done=100000)
    rc, out, err = gen("--shots", "S07", "--yes", "--timeout-min", "0.03", "--clips-dir", c)
    check(rc == 1 and "TIMEOUT" in err and "--resume-task" in err, f"rc={rc}\n{out}\n{err}")
    sc = sidecar(c, "S07")
    check(sc["task_id"].startswith("cgt-") and sc["state"] == "timeout", sc)
    check(not (c / "S07.mp4").exists())
    config(polls_to_done=2)
    n_posts = len(posts())
    rc, out, err = gen("--shots", "S07", "--yes", "--clips-dir", c)
    check(rc == 0 and "resuming instead of resubmitting" in out, f"rc={rc}\n{out}\n{err}")
    check(len(posts()) == n_posts == 1, "re-run must not POST a second paid task")
    check((c / "S07.mp4").stat().st_size > 10_000)
    config(polls_to_done=3)


@test
def t12_failed_task_prints_error_then_retry_resubmits():
    reset()
    c = W / "clips_fail"
    config(fail_contains="lateral tracking")                                 # only S02's prompt
    rc, out, err = gen("--shots", "S01", "S02", "S03", "--yes", "--clips-dir", c)
    check(rc == 1 and "OutputVideoSensitiveContentDetected" in out + err, f"rc={rc}\n{out}\n{err}")
    check((c / "S01.mp4").exists() and (c / "S03.mp4").exists() and not (c / "S02.mp4").exists())
    sc = sidecar(c, "S02")
    check(sc["state"] == "failed" and sc["error"]["code"] == "OutputVideoSensitiveContentDetected" and sc["task_id"], sc)
    first_id = sc["task_id"]
    config(fail_contains=None)
    reset()
    rc, out, err = gen("--shots", "S01", "S02", "S03", "--yes", "--clips-dir", c)
    check(rc == 0 and len(posts()) == 1, f"only the failed shot should be resubmitted: rc={rc} posts={len(posts())}\n{out}")
    sc = sidecar(c, "S02")
    check(sc["state"] == "downloaded" and first_id in sc["previous_tasks"], sc)
    # ephone-task failure shape (error is a string)
    config(fail_contains="lateral tracking")
    rc, out, err = gen("--shots", "S02", "--yes", "--profile", "ephone-task", "--clips-dir", W / "clips_fail_task")
    check(rc == 1 and "sensitive information" in out + err, f"rc={rc}\n{out}\n{err}")
    config(fail_contains=None)


@test
def t13_retries_on_poll_429_and_download_503():
    reset()
    c = W / "clips_retry"
    config(poll_429=3, download_503=2)
    rc, out, err = gen("--shots", "S08", "--yes", "--clips-dir", c)
    check(rc == 0, f"rc={rc}\n{out}\n{err}")
    st = stats()
    check(st["poll_429_served"] == 3 and st["download_503_served"] == 2, st)
    check("retry" in out and (c / "S08.mp4").exists(), out)
    check(len(posts()) == 1, "retries must never apply to the POST")


@test
def t14_submit_is_never_retried_and_unknown_outcome_blocks_blind_resubmit():
    reset()
    c = W / "clips_sub500"
    config(submit_errors=5, submit_status=500)
    rc, out, err = gen("--shots", "S09", "--yes", "--clips-dir", c, "--max-retries", "5")
    check(rc == 1, f"rc={rc}")
    r = [x for x in reqs() if x["method"] == "POST"]
    check(len(r) == 1 and r[0]["status"] == 500, f"POST must be attempted exactly once, saw {len(r)}")
    sc = sidecar(c, "S09")
    check(sc["state"] == "submit_unknown" and not sc["task_id"], sc)
    config(submit_errors=0)
    reset()
    rc, out, err = gen("--shots", "S09", "--yes", "--clips-dir", c)
    check(rc == 1 and "REFUSED" in out + err and "UNKNOWN" in out + err and not posts(), f"rc={rc}\n{out}\n{err}")
    rc, out, err = gen("--shots", "S09", "--yes", "--clips-dir", c, "--force")
    check(rc == 0 and len(posts()) == 1 and (c / "S09.mp4").exists(), f"rc={rc}\n{out}\n{err}")
    # a definite client error (400) is safe to retry later without --force
    reset()
    c2 = W / "clips_sub400"
    rc, out, err = gen("--shots", "S09", "--yes", "--clips-dir", c2, "--model", "no-such-model")
    check(rc == 1 and sidecar(c2, "S09")["state"] == "submit_failed", f"rc={rc}\n{out}\n{err}")
    rc, out, err = gen("--shots", "S09", "--yes", "--clips-dir", c2)
    check(rc == 0, f"submit_failed must be retryable: rc={rc}\n{out}\n{err}")


@test
def t15_reference_images_and_first_frame():
    reset()
    img = W / "ref.png"
    png_file(img)
    rc, out, err = gen("--dry-run", "--shots", "S10", "--reference-image", img, "--reference-image", "https://example.com/car.jpg")
    check(rc == 0 and out.count('"role": "reference_image"') == 2 and "data:image/png;base64,iVBOR" in out, out[:1500])
    check(len(out) < 6000, "dry-run must shorten data urls")
    rc, out, err = gen("--dry-run", "--shots", "S10", "--first-frame", img)
    check(rc == 0 and '"role": "first_frame"' in out, out)
    for bad in (["--first-frame", img, "--reference-image", img], ["--last-frame", img], ["--reference-image", str(W / "nope.png")]):
        rc, out, err = gen("--shots", "S10", "--yes", *bad, "--clips-dir", W / "clips_ref_bad")
        check(rc == 2, f"{bad}: rc={rc} {err}")
    check(not posts(), "invalid combinations must fail before any request")
    c = W / "clips_ref"
    rc, out, err = gen("--shots", "S10", "--yes", "--reference-image", img, "--no-audio", "--resolution", "480p", "--clips-dir", c)
    check(rc == 0, f"rc={rc}\n{out}\n{err}")
    b = posts()[0]["body"]
    item = b["content"][1]
    check(item["role"] == "reference_image" and item["image_url"]["url"].startswith("data:image/png;base64,"), item)
    check(b["generate_audio"] is False and b["resolution"] == "480p", b)
    check(len((c / "S10.json").read_text()) < 8000, "sidecar must not embed the base64 image")
    j = ffprobe_json(c / "S10.mp4")
    check(not any(s["codec_type"] == "audio" for s in j["streams"]), "--no-audio clip should have no audio track")
    check(sidecar(c, "S10")["media"][0]["bytes"] == img.stat().st_size)
    # first-frame mode together with --return-last-frame downloads the last frame
    rc, out, err = gen("--shots", "S10", "--yes", "--first-frame", img, "--return-last-frame", "--clips-dir", W / "clips_ff")
    check(rc == 0 and (W / "clips_ff" / "S10.last.png").stat().st_size > 20, f"rc={rc}\n{out}\n{err}")


@test
def t16_key_is_redacted_even_when_the_server_echoes_it():
    reset()
    config(leak_key_in_errors=True)
    rc, out, err = gen("--probe", key=WRONG)
    check(rc == 1 and WRONG not in out + err and "<REDACTED>" in out + err, f"rc={rc}\n{out}\n{err}")
    c = W / "clips_leak"
    rc, out, err = gen("--shots", "S01", "--yes", "--clips-dir", c, key=WRONG)
    check(rc == 1 and "401" in out + err, f"rc={rc}\n{out}\n{err}")
    check(WRONG not in out + err + (c / "S01.json").read_text(), "wrong key leaked")
    rc, out, err = gen("--shots", "S01", "--yes", "--clips-dir", W / "clips_leak2", "--model", "no-such-model")   # good key echoed in a 404
    check(rc == 1 and CANARY not in out + err and "<REDACTED>" in out + err + (W / "clips_leak2" / "S01.json").read_text(), f"{out}\n{err}")
    rc, out, err = gen("--shots", "S01", "--yes", key=None)
    check(rc == 2 and "EPHONE_API_KEY" in err, "missing key must be a usage error")
    config(leak_key_in_errors=False)
    rc, out, err = gen("--probe", "--base-url", "http://example.com")
    check(rc == 2 and "plain http" in err, f"plain-http guard: rc={rc} {err}")


@test
def t17_complete_the_12_clips_then_assemble_exact_360_frames():
    reset()
    c = PROJ / "out" / "clips"
    rc, out, err = gen("--yes", "--budget-max-cny", "100", "--budget-max-clips", "12", "--max-concurrent", "6")
    check(rc == 0, f"rc={rc}\n{out}\n{err}")
    check(len(posts()) == 8, f"S01,S02,S03,S05 already exist -> exactly 8 new submits, saw {len(posts())}")
    check(sorted(p.stem for p in c.glob("S*.mp4")) == [f"S{i:02d}" for i in range(1, 13)], "need 12 clips")
    check("skipped (exists)" in out, "existing clips should be skipped")
    rc, out, err = asm()
    check(rc == 0, f"rc={rc}\n{out}\n{err}")
    for i in range(1, 13):
        check(f"S{i:02d} " in out, f"table lacks S{i:02d}")
    check("total 360 frames = 15.000 s" in out and "[ 1.417,  2.625]" in out, out)
    final = PROJ / "out" / "final_ai.mp4"
    assert_final_ok(final)
    # right audio at the right place: every shot window carries the tone of ITS clip
    tasks = mjson("GET", "/__mock/tasks")[1]
    samples = pcm(final)
    bounds = [0, 29, 58, 86, 120, 144, 168, 197, 226, 254, 288, 317, 360]
    for i, s in enumerate(f"S{k:02d}" for k in range(1, 13)):
        want = tasks[sidecar(c, s)["task_id"]]["tone"]
        a, b = bounds[i] * 2000, bounds[i + 1] * 2000
        got = tone_hz(samples, a + (b - a) // 4, b - (b - a) // 4)
        check(abs(got - want) / want < 0.04, f"{s}: tone {got:.0f} Hz != {want} Hz (wrong clip or offset)")
    # no pops: the signal is ~0 on both sides of every cut (40 ms fades)
    for bnd in bounds[1:-1]:
        i = bnd * 2000
        check(max(abs(x) for x in samples[i - 20:i + 20]) < 600, f"audible discontinuity at cut {bnd}")
    check(mean_volume(final) > -45, "keep mode produced a silent track")


@test
def t18_trim_modes_and_use_from_pick_the_right_window():
    c = PROJ / "out" / "clips"
    src = c / "S01.mp4"
    cases = {"start": 0, "center": 34, "end": 67}
    for mode, idx in cases.items():
        out_mp4 = W / "outs" / f"trim_{mode}.mp4"
        rc, out, err = asm("--trim-mode", mode, "--output", out_mp4, "--audio", "silence")
        check(rc == 0, f"{mode}: rc={rc}\n{out}\n{err}")
        got = raw_frame(out_mp4, 0)
        d_ok = mad(got, raw_frame(src, idx))
        d_other = mad(got, raw_frame(src, 0 if idx else 60))
        check(d_ok < d_other and d_ok < 3.0, f"trim {mode}: frame 0 matches src frame {idx} with MAD {d_ok:.2f} (other {d_other:.2f})")
        assert_final_ok(out_mp4)
    # silence/drop: silent AAC track of exactly 15.0 s
    check(mean_volume(W / "outs" / "trim_start.mp4") < -80, "silence mode is not silent")
    rc, out, err = asm("--audio", "drop", "--output", W / "outs" / "drop.mp4")
    check(rc == 0 and mean_volume(W / "outs" / "drop.mp4") < -80, f"drop rc={rc}")
    assert_final_ok(W / "outs" / "drop.mp4")
    # per-shot use_from (honoured), clamped when out of range
    uf = W / "proj_uf"
    (uf).mkdir(exist_ok=True)
    data = json.loads((PROJ / "shotlist.json").read_text())
    data["shots"][0]["use_from"] = 0.25
    data["shots"][1]["use_from"] = 3.9
    (uf / "shotlist.json").write_text(json.dumps(data))
    out_mp4 = W / "outs" / "use_from.mp4"
    rc, out, err = run(ASM, "--project-dir", uf, "--clips-dir", c, "--output", out_mp4, "--audio", "silence")
    check(rc == 0, f"rc={rc}\n{out}\n{err}")
    s1 = next(l for l in out.splitlines() if l.startswith("S01 "))
    s2 = next(l for l in out.splitlines() if l.startswith("S02 "))
    check("[ 0.250,  1.458]" in s1 and "use_from" in s1, s1)
    check("clamped" in s2 and "[ 2.792,  4.000]" in s2, s2)
    got = raw_frame(out_mp4, 0)
    check(mad(got, raw_frame(src, 6)) < mad(got, raw_frame(src, 30)), "use_from=0.25 should start at source frame 6")
    rc, out, err = asm("--dry-run", "--output", W / "outs" / "dry.mp4")
    check(rc == 0 and "filter_complex" in out and not (W / "outs" / "dry.mp4").exists(), "assemble --dry-run must render nothing")


@test
def t19_assemble_missing_clip_error_allow_missing_and_odd_sources():
    c = PROJ / "out" / "clips"
    part = W / "clips_part"
    shutil.rmtree(part, ignore_errors=True)
    part.mkdir()
    for p in c.glob("S*.mp4"):
        if p.stem != "S03":
            shutil.copy(p, part / p.name)
    rc, out, err = asm("--clips-dir", part, "--output", W / "outs" / "missing.mp4")
    check(rc == 2 and "S03" in err and "--allow-missing" in err and not (W / "outs" / "missing.mp4").exists(), f"rc={rc}\n{err}")
    rc, out, err = asm("--clips-dir", part, "--output", W / "outs" / "missing.mp4", "--allow-missing")
    check(rc == 0 and "MISSING -> black card" in out, f"rc={rc}\n{out}\n{err}")
    assert_final_ok(W / "outs" / "missing.mp4")
    y = raw_frame(W / "outs" / "missing.mp4", 58 + 10)                       # inside the black S03 card
    check(sum(y) / len(y) < 20, "black card is not black")
    # odd sources: 960x540 @25 fps video-only (S04) and a 0.5 s clip (S12) must still give exactly 360 frames / 15.0 s
    odd = W / "clips_odd"
    shutil.rmtree(odd, ignore_errors=True)
    shutil.copytree(c, odd, ignore=shutil.ignore_patterns("*.json"))
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=size=960x540:rate=25:duration=3", "-c:v", "libx264",
                    "-preset", "ultrafast", "-pix_fmt", "yuv420p", str(odd / "S04.mp4")], check=True)
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=size=1280x720:rate=24:duration=0.5", "-f", "lavfi",
                    "-i", "sine=frequency=500:duration=0.5", "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac",
                    str(odd / "S12.mp4")], check=True)
    rc, out, err = asm("--clips-dir", odd, "--output", W / "outs" / "odd.mp4")
    check(rc == 0, f"rc={rc}\n{out}\n{err}")
    s4 = next(l for l in out.splitlines() if l.startswith("S04 "))
    s12 = next(l for l in out.splitlines() if l.startswith("S12 "))
    check("no audio stream" in s4 and "rescaled 960x540" in s4, s4)
    check("held" in s12, s12)
    assert_final_ok(W / "outs" / "odd.mp4")
    # corrupt clip -> clear error, no output
    bad = W / "clips_bad"
    shutil.rmtree(bad, ignore_errors=True)
    shutil.copytree(part, bad)
    (bad / "S01.mp4").write_bytes(b"not a video")
    rc, out, err = asm("--clips-dir", bad, "--output", W / "outs" / "bad.mp4", "--allow-missing")
    check(rc == 2 and "S01.mp4" in err and not (W / "outs" / "bad.mp4").exists(), f"rc={rc}\n{err}")


def find_secret(roots, needles, skip=("test_adapter.py",)):
    """-> (hits, files_scanned) scanning every file below roots as bytes."""
    hits, scanned = [], 0
    for root in roots:
        for p in Path(root).rglob("*"):
            if p.is_file() and p.name not in skip and "__pycache__" not in p.parts:
                data = p.read_bytes()
                scanned += 1
                hits += [str(p) for n in needles if n.encode() in data]
    return hits, scanned


@test
def t20_canary_key_never_leaks_and_real_project_is_clean():
    needles = [CANARY, WRONG]
    for k in (CANARY, WRONG):
        needles += [urllib.parse.quote(k, safe=""), base64.b64encode(k.encode()).decode().rstrip("=")]
    # the scanner itself must be able to see a planted secret (guards against a vacuous pass)
    plant = W / "plant"
    plant.mkdir(exist_ok=True)
    (plant / "x.json").write_text(json.dumps({"auth": "Bearer " + CANARY}))
    hits, _ = find_secret([plant], needles)
    check(hits, "scanner failed to detect a planted canary")
    shutil.rmtree(plant)
    for blob in OUTPUTS:
        for n in needles:
            check(n not in blob, f"secret found in captured output of: {blob.splitlines()[0]}")
    hits, scanned = find_secret([W, HERE], needles)
    check(not hits, f"secret found in files: {hits}")
    check(scanned > 100, f"expected to scan many files, got {scanned}")
    check(len(OUTPUTS) > 60, f"expected many captured runs, got {len(OUTPUTS)}")
    # nothing may have been left in the real project
    real_clips = REAL_PROJECT / "out" / "clips"
    left = list(real_clips.iterdir()) if real_clips.exists() else []
    check(not left, f"real out/clips is not empty: {left}")
    check(not (REAL_PROJECT / "out" / "final_ai.mp4").exists(), "real out/final_ai.mp4 exists")
    check(not list(HERE.glob("__pycache__")), "__pycache__ left in seedance/")


# ----------------------------------------------------------------------------- main
def main() -> int:
    global W, PROJ, MOCK_URL
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--keep", action="store_true", help="keep the work dir even when everything passes")
    ap.add_argument("--workdir", type=Path, help="default: scratchpad/test_adapter_work (or a temp dir)")
    args = ap.parse_args()
    base = args.workdir or (SCRATCH / "test_adapter_work" if SCRATCH.is_dir() else Path(tempfile.mkdtemp(prefix="seedance_test_")))
    shutil.rmtree(base, ignore_errors=True)
    W, PROJ = base.resolve(), base.resolve() / "proj"
    (PROJ / "out").mkdir(parents=True)
    shutil.copy(REAL_PROJECT / "shotlist.json", PROJ / "shotlist.json")
    (W / "outs").mkdir()
    for tool in ("ffmpeg", "ffprobe"):
        if not shutil.which(tool):
            print(f"{tool} not found"); return 2

    mock_out = open(W / "mock.stdout", "w")
    mock = subprocess.Popen([sys.executable, str(MOCK), "--key", CANARY, "--port-file", str(W / "mock.url")],
                            stdout=mock_out, stderr=subprocess.STDOUT, env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})
    failures = []
    try:
        for _ in range(100):
            if (W / "mock.url").exists() and (W / "mock.url").read_text().startswith("http"):
                break
            time.sleep(0.1)
        else:
            print("mock server did not start"); return 2
        MOCK_URL = (W / "mock.url").read_text().strip()
        print(f"mock server at {MOCK_URL}; work dir {W}\n")
        t_all = time.time()
        for fn in TESTS:
            t0 = time.time()
            try:
                fn()
                print(f"PASS  {fn.__name__}  ({time.time() - t0:.1f}s)")
            except Exception as e:
                failures.append(fn.__name__)
                tb = traceback.format_exc().strip().splitlines()
                print(f"FAIL  {fn.__name__}  ({time.time() - t0:.1f}s)\n      {type(e).__name__}: {e}\n      {tb[-3].strip() if len(tb) >= 3 else ''}")
        print(f"\n{len(TESTS) - len(failures)}/{len(TESTS)} passed in {time.time() - t_all:.0f}s")
    finally:
        mock.terminate()
        try:
            mock.wait(timeout=5)
        except subprocess.TimeoutExpired:
            mock.kill()
        mock_out.close()
    if failures:
        print(f"FAILED: {', '.join(failures)}\nwork dir kept: {W}")
        return 1
    if args.keep:
        print(f"work dir kept: {W}")
    else:
        shutil.rmtree(W, ignore_errors=True)
    print("ALL GREEN")
    return 0


if __name__ == "__main__":
    sys.exit(main())
