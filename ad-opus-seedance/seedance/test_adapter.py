#!/usr/bin/env python3
"""End-to-end tests for generate_clips.py / assemble_clips.py against mock_server.py (no real API, no network).

Run:   python test_adapter.py [--keep] [--workdir DIR]
Uses a fake random canary API key and a throw-away project copy. Work dir: --workdir DIR, else the env var
SEEDANCE_TEST_WORKDIR, else a fresh tempfile.mkdtemp() (honours TMPDIR). The real project's out/clips and
out/final_ai.mp4 are never touched (checked at the end).
"""
from __future__ import annotations

import sys
sys.dont_write_bytecode = True       # in-process imports of generate_clips must not leave a __pycache__ in seedance/

import argparse
import array
import base64
import json
import os
import re
import secrets
import shutil
import signal
import struct
import subprocess
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
WORKDIR_MARKER = ".seedance_test_workdir"
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


# mock fault-injection settings restored before every test, so one failing test cannot cascade into the next ones
CONFIG_DEFAULTS = {"polls_to_done": 3, "fail_contains": None, "fail_status": "failed", "poll_429": 0, "download_503": 0,
                   "submit_errors": 0, "drop_poll": 0, "cdn_only_curl": False, "truncate_download": 0, "omit_video_url": 0,
                   "reject_expires": False, "leak_key_in_errors": False}


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


@test
def t20_network_errors_on_polls_are_tolerated_then_resumable():
    reset()
    c = W / "clips_netdrop"
    config(drop_poll=4)                              # the server closes the connection without answering
    rc, out, err = gen("--shots", "S11", "--yes", "--clips-dir", c, "--poll-retries", "1")
    check(rc == 0, f"rc={rc}\n{out}\n{err}")
    check(stats()["polls_dropped"] == 4 and "poll error #1" in out and "poll error #2" in out, out)
    check(len(posts()) == 1 and (c / "S11.mp4").exists(), "tolerated errors must not resubmit")
    # a long outage: the adapter gives up on THIS task but keeps the id, and a re-run resumes it
    reset()
    c2 = W / "clips_netdrop2"
    config(drop_poll=1000)
    rc, out, err = gen("--shots", "S11", "--yes", "--clips-dir", c2, "--poll-retries", "0", "--max-poll-errors", "3")
    check(rc == 1 and "gave up after 3 consecutive poll errors" in out + err, f"rc={rc}\n{out}\n{err}")
    sc = sidecar(c2, "S11")
    check(sc["state"] == "poll_error" and sc["task_id"].startswith("cgt-"), sc)
    config(drop_poll=0)
    rc, out, err = gen("--shots", "S11", "--yes", "--clips-dir", c2)
    check(rc == 0 and "resuming instead of resubmitting" in out and len(posts()) == 1, f"rc={rc}\n{out}\n{err}")


@test
def t21_cancelled_and_expired_tasks_are_reported_and_retryable():
    reset()
    c = W / "clips_cancel"
    for status in ("cancelled", "expired"):
        config(fail_contains="lateral tracking", fail_status=status)
        rc, out, err = gen("--shots", "S02", "--yes", "--clips-dir", c)
        check(rc == 1 and f"ended '{status}'" in out + err and "no error object returned" in out + err, f"{status}: rc={rc}\n{out}\n{err}")
        sc = sidecar(c, "S02")
        check(sc["state"] == status and sc["task_id"], sc)
    config(fail_contains=None, fail_status="failed")
    rc, out, err = gen("--shots", "S02", "--yes", "--clips-dir", c)
    check(rc == 0 and len(sidecar(c, "S02")["previous_tasks"]) == 2 and (c / "S02.mp4").exists(), f"rc={rc}\n{out}\n{err}")


@test
def t22_download_falls_back_to_curl_when_the_cdn_refuses_urllib():
    if not shutil.which("curl"):
        return
    reset()
    c = W / "clips_curl"
    config(cdn_only_curl=True)                       # a CDN that rejects even a browser-like urllib request
    rc, out, err = gen("--shots", "S12", "--yes", "--clips-dir", c)
    config(cdn_only_curl=False)
    check(rc == 0 and "trying curl" in out and (c / "S12.mp4").stat().st_size > 10_000, f"rc={rc}\n{out}\n{err}")
    cdn = reqs("cdn")
    check(any(r["status"] == 403 and "Mozilla" in r["ua"] for r in cdn) and cdn[-1]["status"] == 200 and cdn[-1]["ua"].startswith("curl/"),
          [(r["status"], r["ua"]) for r in cdn])
    check(all(r["auth"] == "none" for r in cdn), "the API key must never be sent to the CDN")
    check(len(posts()) == 1)


# ----------------------------------------------------------------------------- regression tests for the verifier findings
def inproc(args, patch=None):
    """Run generate_clips.main() inside this process (so a function can be monkeypatched). -> (rc, stdout, stderr)."""
    import contextlib
    import io
    if str(HERE) not in sys.path:
        sys.path.insert(0, str(HERE))
    import generate_clips as gc
    old_hook, old_env = sys.excepthook, {k: os.environ.get(k) for k in ("EPHONE_API_KEY", "EPHONE_BASE_URL")}
    os.environ.update({"EPHONE_API_KEY": CANARY, "EPHONE_BASE_URL": MOCK_URL})
    orig = gc.write_json_atomic
    if patch:
        gc.write_json_atomic = patch(orig)
    out, err = io.StringIO(), io.StringIO()
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = gc.main(["--project-dir", str(PROJ), "--poll-interval", "0.15", "--retry-base-delay", "0.05", *map(str, args)])
    finally:
        gc.write_json_atomic = orig
        sys.excepthook = old_hook
        for k, v in old_env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
    OUTPUTS.append(f"$ <in-process> generate_clips {' '.join(map(str, args))}\n{out.getvalue()}\n{err.getvalue()}")
    return rc, out.getvalue(), err.getvalue()


@test
def t23_extra_json_cannot_bypass_the_budget_guard():
    reset()
    c = W / "clips_xjson"
    big = '{"resolution":"1080p"}'
    rc, out, err = gen("--yes", "--shots", "S01", "--extra-json", big, "--budget-max-cny", "7", "--clips-dir", c)
    check(rc == 3 and "budget-max-cny" in out + err, f"extra-json 1080p must hit the 7 CNY cap: rc={rc}\n{out}\n{err}")
    check("196,425 tokens" in out and "CNY 15.12" in out, "estimate must be the 1080p one:\n" + out)
    check(not posts() and not c.exists(), "a blocked run must send nothing and write nothing")
    # same price as the explicit flag
    rc, out2, err = gen("--dry-run", "--shots", "S01", "--resolution", "1080p", "--clips-dir", c)
    check(rc == 0 and "196,425 tokens" in out2, out2)
    # ratio via extra-json is priced too (1:1 720p = 960x960 -> different from 16:9)
    rc, out3, err = gen("--dry-run", "--shots", "S01", "--extra-json", '{"ratio":"21:9"}', "--clips-dir", c)     # 1470x630 px
    check(rc == 0 and "87,300 tokens" not in out3 and "720p 21:9 4s" in out3, out3)
    # the ephone-task profile reads the same keys from its 'input' object
    rc, out4, err = gen("--yes", "--shots", "S01", "--profile", "ephone-task", "--extra-json", big, "--budget-max-cny", "7", "--clips-dir", c)
    check(rc == 3 and "CNY 15.12" in out4, f"task profile: rc={rc}\n{out4}\n{err}")
    # duration via extra-json is priced as well and still bounded
    rc, out5, err = gen("--dry-run", "--shots", "S01", "--extra-json", '{"duration":8}', "--clips-dir", c)
    check(rc == 0 and "174,600 tokens" in out5, out5)
    rc, out5, err = gen("--yes", "--shots", "S01", "--extra-json", '{"duration":99}', "--clips-dir", c)
    check(rc == 2 and "maximum" in err, f"rc={rc} {err}")
    # unknown resolution/ratio in extra-json cannot be priced -> refused
    for bad in ('{"resolution":"4k"}', '{"ratio":"2:1"}', '{"resolution":null}'):
        rc, out5, err = gen("--yes", "--shots", "S01", "--extra-json", bad, "--clips-dir", c)
        check(rc == 2 and "cannot estimate the cost" in err, f"{bad}: rc={rc} {err}")
    # a within-budget override still goes through, and the request really carries it
    rc, out6, err = gen("--yes", "--shots", "S01", "--extra-json", '{"resolution":"480p"}', "--budget-max-cny", "7", "--clips-dir", c)
    check(rc == 0 and posts()[-1]["body"]["resolution"] == "480p", f"rc={rc}\n{out6}\n{err}")
    check(sidecar(c, "S01")["params"]["resolution"] == "480p" and sidecar(c, "S01")["estimate"]["resolution"] == "480p", sidecar(c, "S01")["estimate"])
    # a NaN / inf / negative cap would silently disable (or break) the CNY guard -> refused
    for bad in ("nan", "NaN", "inf", "-inf", "-1"):
        rc, out7, err = gen("--yes", "--shots", "S02", "--budget-max-cny", bad, "--clips-dir", W / "clips_nan")
        check(rc == 2 and "--budget-max-cny" in err, f"cap {bad}: rc={rc}\n{out7}\n{err}")
    check(len(posts()) == 1, "refused caps must not submit")
    rc, out7, err = gen("--dry-run", "--timeout-min", "nan")
    check(rc == 2 and "--timeout-min" in err, f"rc={rc} {err}")


@test
def t24_no_expires_flag_and_hint_when_the_gateway_rejects_the_field():
    reset()
    c = W / "clips_expires"
    rc, out, err = gen("--dry-run", "--shots", "S01", "--clips-dir", c)
    check(rc == 0 and '"execution_expires_after": 172800' in out, out)
    rc, out, err = gen("--dry-run", "--shots", "S01", "--no-expires", "--clips-dir", c)
    check(rc == 0 and "execution_expires_after" not in out, out)
    reset()
    rc, out, err = gen("--show-provider")                          # stands in for the missing provider.json; offline, no secrets
    prov = json.loads(out)
    check(rc == 0 and prov["model"] == "doubao-seedance-2-5-260628" and "ephone-ark" in prov["profiles"] and prov["execution_expires_after_s"] == 172800
          and CANARY not in out and not reqs(), out)
    rc, out, err = gen("--show-provider", "--no-expires")
    check(rc == 0 and json.loads(out)["execution_expires_after_s"] is None, out)
    config(reject_expires=True)
    rc, out, err = gen("--yes", "--shots", "S01", "--clips-dir", c)
    check(rc == 1 and "--no-expires" in out + err and sidecar(c, "S01")["state"] == "submit_failed", f"rc={rc}\n{out}\n{err}")
    check(not sidecar(c, "S01").get("task_id"), "a rejected submit has no task id")
    rc, out, err = gen("--yes", "--shots", "S01", "--no-expires", "--clips-dir", c)         # submit_failed is retryable
    config(reject_expires=False)
    check(rc == 0 and "execution_expires_after" not in posts()[-1]["body"] and (c / "S01.mp4").exists(), f"rc={rc}\n{out}\n{err}")
    rc, out, err = gen("--yes", "--shots", "S02", "--profile", "ephone-task", "--clips-dir", W / "clips_expires_task")
    check(rc == 0 and "execution_expires_after" not in json.dumps(posts()[-1]["body"]), "task profile never sent the field")


@test
def t25_truncated_download_is_rejected_retried_and_resumable():
    reset()
    c = W / "clips_trunc"
    config(truncate_download=100)                    # every mp4 body stops after 1/3 and has no Content-Length
    rc, out, err = gen("--shots", "S01", "--yes", "--max-retries", "2", "--clips-dir", c)
    config(truncate_download=0)
    check(rc == 1 and "truncated or corrupt" in out + err, f"rc={rc}\n{out}\n{err}")
    sc = sidecar(c, "S01")
    check(sc["state"] == "download_failed" and sc["task_id"].startswith("cgt-"), sc)
    check(not (c / "S01.mp4").exists() and not (c / "S01.mp4.part").exists(), "a truncated file must not be kept")
    check(stats()["downloads_truncated"] == 3, f"expected 1 try + 2 retries, saw {stats()}")
    rc, out, err = gen("--shots", "S01", "--yes", "--clips-dir", c)            # same task id, no second paid submit
    check(rc == 0 and "resuming instead of resubmitting" in out and len(posts()) == 1, f"rc={rc}\n{out}\n{err}")
    check(sidecar(c, "S01")["state"] == "downloaded" and (c / "S01.mp4").stat().st_size > 10_000)
    # a transient truncation is retried and succeeds on its own
    reset()
    c2 = W / "clips_trunc2"
    config(truncate_download=1)
    rc, out, err = gen("--shots", "S02", "--yes", "--clips-dir", c2)
    check(rc == 0 and "retry" in out and stats()["downloads_truncated"] == 1 and (c2 / "S02.mp4").exists(), f"rc={rc}\n{out}\n{err}")
    j = ffprobe_json(c2 / "S02.mp4", count=True)
    check(int(next(s for s in j["streams"] if s["codec_type"] == "video")["nb_read_frames"]) == 96, "retried file is not complete")


@test
def t26_succeeded_without_video_url_is_resumed_never_resubmitted():
    for profile, shot in (("ephone-ark", "S03"), ("ephone-task", "S04")):
        reset()
        c = W / f"clips_nourl_{profile}"
        config(omit_video_url=1)
        rc, out, err = gen("--shots", shot, "--yes", "--profile", profile, "--clips-dir", c)
        config(omit_video_url=0)
        check(rc == 1 and "no video url" in out + err, f"{profile}: rc={rc}\n{out}\n{err}")
        sc = sidecar(c, shot)
        check(sc["state"] == "no_video_url" and sc["task_id"] and sc["error"]["code"] == "NoVideoUrl", sc)
        check(len(posts()) == 1)
        rc, out, err = gen("--shots", shot, "--yes", "--profile", profile, "--clips-dir", c)
        check(rc == 0 and "resuming instead of resubmitting" in out and len(posts()) == 1, f"{profile} rerun: rc={rc}\n{out}\n{err}")
        check(sidecar(c, shot)["state"] == "downloaded" and (c / f"{shot}.mp4").exists())


@test
def t27_unreadable_sidecar_blocks_a_blind_resubmit_and_the_task_id_is_printed_first():
    reset()
    c = W / "clips_corrupt"
    c.mkdir()
    (c / "S04.json").write_text('{"shot": "S04", "task_id": "cgt-precious123", "state": "submitt')       # truncated by a crash
    (c / "S05.json").write_text("")                                                                       # empty file
    rc, out, err = gen("--shots", "S04", "S05", "--yes", "--clips-dir", c)
    check(rc == 1 and not posts(), f"nothing may be submitted: rc={rc}\n{out}\n{err}")
    check(out.count("REFUSED") + err.count("REFUSED") >= 2 and "cannot be parsed" in out + err, out + err)
    check("cgt-precious123" in out + err and "--resume-task cgt-precious123" in out + err, "the salvaged task id must be shown")
    check((c / "S04.json").read_text().startswith('{"shot"'), "the unreadable sidecar must not be overwritten")
    rc, out, err = gen("--dry-run", "--shots", "S04", "--clips-dir", c)
    check(rc == 0 and "REFUSE" in out, out)
    rc, out, err = gen("--shots", "S04", "--yes", "--force", "--clips-dir", c)                          # explicit override
    check(rc == 0 and len(posts()) == 1, f"rc={rc}\n{out}\n{err}")
    check((c / "S04.json.corrupt").read_text().find("cgt-precious123") > 0, "the old file must be kept as .corrupt")
    check("cgt-precious123" in sidecar(c, "S04")["previous_tasks"], sidecar(c, "S04"))
    # --resume-task with an explicit id works even when the sidecar is garbage
    (c / "S06.json").write_text("{{{{ not json")
    st, j = mjson("POST", "/doubao/api/v3/contents/generations/tasks", {"model": "doubao-seedance-2-5-260628", "duration": 4,
                                                                        "content": [{"type": "text", "text": "x"}]},
                  headers={"Authorization": "Bearer " + CANARY})
    rc, out, err = gen("--resume-task", j["id"], "--shot", "S06", "--clips-dir", c)
    check(rc == 0 and sidecar(c, "S06")["task_id"] == j["id"], f"rc={rc}\n{out}\n{err}")
    # the id is printed BEFORE it is persisted, and a failing disk write after the POST is loud and does not lose it
    reset()

    def fail_after_post(orig):
        n = {"i": 0}

        def w(path, obj):
            n["i"] += 1
            if n["i"] >= 2:                                    # 1st write = state 'submitting' (before the POST)
                raise OSError(28, "No space left on device")
            return orig(path, obj)
        return w
    rc, out, err = inproc(["--shots", "S07", "--yes", "--clips-dir", W / "clips_disk"], patch=fail_after_post)
    m = re.search(r"\[S07\] submitted, task id (\S+)", out)
    check(len(posts()) == 1 and m and m.group(1) in mjson("GET", "/__mock/tasks")[1], out + err)
    tid = m.group(1)
    check(f"THE PAID TASK ID IS {tid}" in err and f"--resume-task {tid}" in err, "disk error must show the paid task id:\n" + err)
    check(err.count("cannot write") == 1, "the disk error should be reported once per shot:\n" + err)
    check((W / "clips_disk" / "S07.mp4").exists(), "the download should still complete")
    # if the very first write fails nothing is submitted at all
    reset()
    rc, out, err = inproc(["--shots", "S08", "--yes", "--clips-dir", W / "clips_disk2"],
                          patch=lambda orig: (lambda path, obj: (_ for _ in ()).throw(OSError(28, "No space left on device"))))
    check(rc == 1 and not posts() and "nothing was submitted" in out + err, f"rc={rc}\n{out}\n{err}")


@test
def t28_shot_ids_are_validated_and_last_frame_extension_is_whitelisted():
    bad = W / "proj_badid"
    bad.mkdir(exist_ok=True)
    data = json.loads((PROJ / "shotlist.json").read_text())
    for evil in ("../../evil", "a/b", "S 01", "S01.mp4", ""):
        data["shots"][0]["id"] = evil
        (bad / "shotlist.json").write_text(json.dumps(data))
        for script, extra in ((GEN, ["--dry-run", "--poll-interval", "0.1"]), (ASM, ["--dry-run"])):
            rc, out, err = run(script, "--project-dir", bad, "--clips-dir", W / "clips_badid", *extra)
            check(rc == 2 and "invalid id" in err, f"{script.name} id {evil!r}: rc={rc}\n{out}\n{err}")
    data["shots"][0]["id"] = data["shots"][1]["id"]
    (bad / "shotlist.json").write_text(json.dumps(data))
    for script in (GEN, ASM):
        rc, out, err = run(script, "--project-dir", bad, "--dry-run")
        check(rc == 2 and "duplicate shot id" in err, f"{script.name}: rc={rc} {err}")
    check(not (W / "evil.json").exists() and not (W / "clips_badid").exists() and not (W.parent / "evil.json").exists())
    sys.path.insert(0, str(HERE))
    import generate_clips as gc
    sys.excepthook = sys.__excepthook__
    for url, want in (("https://cdn/x/a_last.png?sig=1", ".png"), ("https://cdn/a.JPG", ".jpg"), ("https://cdn/a.webp", ".webp"),
                      ("https://cdn/a.jpeg?x=.sh", ".jpeg"), ("https://cdn/a.sh", ".png"), ("https://cdn/a.php", ".png"),
                      ("https://cdn/a", ".png"), ("https://cdn/a.mp4/../../x.py", ".png")):
        check(gc.last_frame_ext(url) == want, f"{url} -> {gc.last_frame_ext(url)} (want {want})")


def make_clip(path: Path, size="1280x720", rate=24, frames=None, seconds=4, audio=None):
    """Synthetic test clip. audio = seconds of sine audio (None = no audio stream)."""
    cmd = ["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"testsrc2=size={size}:rate={rate}" + ("" if frames else f":duration={seconds}")]
    if audio:
        cmd += ["-f", "lavfi", "-i", f"sine=frequency=440:sample_rate=48000:duration={audio}", "-c:a", "aac"]
    cmd += ["-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p"]
    if frames:
        cmd += ["-frames:v", str(frames)]
    subprocess.run(cmd + [str(path)], check=True)


def clips_copy(name: str) -> Path:
    d = W / name
    shutil.rmtree(d, ignore_errors=True)
    shutil.copytree(PROJ / "out" / "clips", d, ignore=shutil.ignore_patterns("*.json"))
    return d


FAST = ("--preset", "ultrafast", "--crf", "30")


@test
def t29_assemble_survives_audio_shorter_than_the_window_in_every_trim_mode():
    d = clips_copy("clips_shortaudio")
    make_clip(d / "S02.mp4", seconds=4, audio=2)                 # 4 s of video but only 2 s of audio
    for mode in ("end", "center", "start"):
        out_mp4 = W / "outs" / f"shortaudio_{mode}.mp4"
        rc, out, err = asm("--clips-dir", d, "--output", out_mp4, "--trim-mode", mode, *FAST)
        check(rc == 0 and out_mp4.exists(), f"trim-mode {mode}: rc={rc}\n{out}\n{err[-600:]}")
        assert_final_ok(out_mp4)
    # in 'end' mode the S02 window (2.6 s..4 s of its clip) lies after the audio: it must be silent, the others not
    pcm_all = pcm(W / "outs" / "shortaudio_end.mp4")
    a, b = 29 * 2000, 58 * 2000
    check(max(abs(x) for x in pcm_all[a + 2000:b - 2000]) < 50, "audio past the end of the short track must be silence")
    check(max(abs(x) for x in pcm_all[2000:20000]) > 1000, "neighbouring shots must keep their audio")
    # ffmpeg failures are readable: no wall of -stats lines
    rc, out, err = asm("--clips-dir", d, "--output", W / "outs" / "x.mp4", "--crf", "abc")
    check(rc != 0 and "frame=" not in err, f"rc={rc} {err[-300:]}")


@test
def t30_short_clip_hold_is_frame_exact_and_warned():
    d = clips_copy("clips_hold")
    make_clip(d / "S05.mp4", frames=5)                           # 5 frames = 0.208333 s (ffprobe prints 6 decimals)
    out_mp4 = W / "outs" / "hold.mp4"
    rc, out, err = asm("--clips-dir", d, "--output", out_mp4, *FAST)
    check(rc == 0, f"rc={rc}\n{out}\n{err[-600:]}")
    assert_final_ok(out_mp4)
    s5 = next(l for l in out.splitlines() if l.startswith("S05 "))
    check("last frame held for 19 frames" in s5, s5)                  # 24 - 5, not 20
    check("WARNING" in err and "S05" in err and "held" in err, "a short clip must warn on stderr:\n" + err)
    # S05 owns output frames 120..143: the hold is flat, the first jump is the cut to S06 at frame 144
    prev = raw_frame(out_mp4, 124)
    first_cut = None
    for k in range(125, 150):
        cur = raw_frame(out_mp4, k)
        if mad(prev, cur) > 1.0:
            first_cut = k
            break
        prev = cur
    check(first_cut == 144, f"S06 must start at output frame 144, first visible cut at {first_cut}")
    # audio stays in step: S06's tone starts at sample 144*2000
    tasks = mjson("GET", "/__mock/tasks")[1]
    samples = pcm(out_mp4)
    want = tasks[sidecar(PROJ / "out" / "clips", "S06")["task_id"]]["tone"]
    got = tone_hz(samples, 144 * 2000 + 10000, 168 * 2000 - 10000)
    check(abs(got - want) / want < 0.04, f"S06 tone {got:.0f} != {want}")
    # a bad use_from is a clear error, not a traceback
    uf = W / "proj_badusefrom"
    uf.mkdir(exist_ok=True)
    data = json.loads((PROJ / "shotlist.json").read_text())
    for bad in ("abc", True, [1], "nan"):
        data["shots"][0]["use_from"] = bad
        (uf / "shotlist.json").write_text(json.dumps(data))
        rc, out, err = run(ASM, "--project-dir", uf, "--clips-dir", PROJ / "out" / "clips", "--output", W / "outs" / "uf.mp4")
        check(rc == 2 and "S01: use_from must be" in err and "Traceback" not in err, f"use_from={bad!r}: rc={rc}\n{err}")
    check(not (W / "outs" / "uf.mp4").exists())


@test
def t31_non_16x9_clip_is_flagged_as_cropped():
    d = clips_copy("clips_portrait")
    make_clip(d / "S03.mp4", size="720x1280", audio=4)
    out_mp4 = W / "outs" / "portrait.mp4"
    rc, out, err = asm("--clips-dir", d, "--output", out_mp4, *FAST)
    check(rc == 0, f"rc={rc}\n{out}\n{err[-400:]}")
    s3 = next(l for l in out.splitlines() if l.startswith("S03 "))
    check("cropped (aspect 0.56 -> 16:9)" in s3 and "rescaled 720x1280" in s3, s3)
    check("WARNING" in err and "S03" in err and "CENTRE-CROPPED" in err, err)
    assert_final_ok(out_mp4)
    rc, out, err = asm("--clips-dir", PROJ / "out" / "clips", "--output", W / "outs" / "plain.mp4", "--dry-run")
    check(rc == 0 and "WARNING" not in err and "cropped" not in out, "16:9 clips must not warn")


@test
def t32_mock_removes_its_scratch_dir_on_sigterm():
    tmp = W / "mock_tmp_probe"
    tmp.mkdir(exist_ok=True)
    p = subprocess.Popen([sys.executable, str(MOCK), "--tmp-dir", str(tmp), "--port-file", str(W / "probe.url")],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})
    try:
        for _ in range(100):
            if (W / "probe.url").exists() and (W / "probe.url").read_text().startswith("http"):
                break
            time.sleep(0.1)
        check(len(list(tmp.glob("mock_ephone_*"))) == 1, "the mock should create exactly one scratch dir")
        p.send_signal(signal.SIGTERM)
        check(p.wait(timeout=10) == 0, "SIGTERM should be a clean exit")
    finally:
        if p.poll() is None:
            p.kill()
    check(not list(tmp.glob("mock_ephone_*")), "scratch dir left behind after SIGTERM")


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
def t33_canary_key_never_leaks_and_real_project_is_clean():
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
    check(len(OUTPUTS) > 40, f"expected many captured runs, got {len(OUTPUTS)}")
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
    ap.add_argument("--workdir", type=Path, help="work dir (default: $SEEDANCE_TEST_WORKDIR, else a fresh tempfile.mkdtemp dir); "
                                                 "it is wiped first, so it must be new, empty or a previous test work dir")
    args = ap.parse_args()
    chosen = args.workdir or (Path(os.environ["SEEDANCE_TEST_WORKDIR"]) if os.environ.get("SEEDANCE_TEST_WORKDIR") else None)
    if chosen is None:
        base = Path(tempfile.mkdtemp(prefix="seedance_test_"))
    else:
        base = chosen.expanduser()
        if base.exists() and any(base.iterdir()) and not (base / WORKDIR_MARKER).exists():
            print(f"refusing to wipe {base}: it is not empty and not a previous test work dir"); return 2
        shutil.rmtree(base, ignore_errors=True)
        base.mkdir(parents=True)
    W, PROJ = base.resolve(), base.resolve() / "proj"
    (W / WORKDIR_MARKER).write_text("seedance test work dir\n")
    (W / "mock_tmp").mkdir()
    (PROJ / "out").mkdir(parents=True)
    shutil.copy(REAL_PROJECT / "shotlist.json", PROJ / "shotlist.json")
    (W / "outs").mkdir()
    for tool in ("ffmpeg", "ffprobe"):
        if not shutil.which(tool):
            print(f"{tool} not found"); return 2

    mock_out = open(W / "mock.stdout", "w")
    mock = subprocess.Popen([sys.executable, str(MOCK), "--key", CANARY, "--port-file", str(W / "mock.url"),
                             "--tmp-dir", str(W / "mock_tmp")],
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
            mjson("POST", "/__mock/config", CONFIG_DEFAULTS)
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
    left = list((W / "mock_tmp").glob("mock_ephone_*"))
    if left:                                       # the mock must remove its scratch dir when it is terminated
        failures.append("mock_cleanup")
        print(f"FAIL  mock did not remove its scratch dir on SIGTERM: {left}")
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
