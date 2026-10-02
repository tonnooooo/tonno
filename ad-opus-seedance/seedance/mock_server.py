#!/usr/bin/env python3
"""Localhost-only mock of the Ephone gateway for testing generate_clips.py (stdlib + ffmpeg).

Implements BOTH real profiles:
  ephone-ark   POST /doubao/api/v3/contents/generations/tasks      -> {"id": "cgt-..."}
               GET  /doubao/api/v3/contents/generations/tasks/{id} -> queued|running|succeeded|failed
  ephone-task  POST /v1/task/submit                                -> {"id","status":"queued","created_at"}
               GET  /v1/task/{id}                                  -> queued|in_progress|completed|failed + outputs[]
  GET /v1/models                                                   -> a few fake model ids
  GET /cdn/<id>.mp4?sig=...  signed "CDN" download; answers 403 to the default Python-urllib User-Agent
Like the real API it rejects duration < 4 (HTTP 400) and a 'seed' parameter on Seedance 2.5.
The clip served is generated with ffmpeg (lavfi testsrc + sine tone) with the requested duration/size.

Fault injection (CLI flags or POST /__mock/config with a JSON object):
  --fail-nth N (repeatable)   the Nth submitted task ends 'failed'
  --fail-contains TEXT        tasks whose prompt contains TEXT end 'failed'
  --poll-429 N                the next N status polls answer 429
  --download-503 N            the next N CDN downloads answer 503
  --submit-status CODE --submit-errors N   the next N submits answer CODE (e.g. 500) WITHOUT creating a task
  --polls-to-done N           polls needed before the terminal state (default 3; huge = never finishes)
  config only (POST /__mock/config): drop_poll N (close the connection on the next N polls), fail_status
                              ('failed'|'cancelled'|'expired' for failing tasks), cdn_only_curl (403 unless UA starts with curl/),
                              truncate_download N (the next N mp4 downloads send only truncate_frac (default 0.33) of the bytes,
                              with NO Content-Length, then close), omit_video_url N (the next N terminal polls say 'succeeded'/
                              'completed' but carry no video url), reject_expires (400 when the ark body carries
                              execution_expires_after)
  --leak-key-in-errors        error bodies echo the received Authorization header (tests redaction)
  --tmp-dir DIR               where the generated clips are cached (default: a fresh system temp dir); the directory the mock
                              creates is always removed when the server exits (SIGTERM/SIGINT/normal exit)
Control: GET /__mock/requests, /__mock/stats, /__mock/tasks, POST /__mock/reset, POST /__mock/config.
The Authorization header value is never stored in the request log (only ok/bad/none).
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import re
import shutil
import signal
import struct
import subprocess
import sys
import tempfile
import threading
import time
import uuid
import zlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

SEEDANCE_MODELS = ["doubao-seedance-2-5-260628", "doubao-seedance-2.5", "doubao-seedance-2-0-260128",
                   "doubao-seedance-2-0-fast-260128", "doubao-seedance-2-0-mini-260615"]
FAKE_MODELS = SEEDANCE_MODELS + ["doubao-seedream-5-0-pro-260628", "gpt-4o", "claude-sonnet-4-5", "kling-v2-1",
                                 "sora-2", "text-embedding-3-small"]
DIMS = {"480p": {"16:9": (864, 480), "9:16": (480, 864), "1:1": (640, 640), "4:3": (736, 544), "3:4": (544, 736), "21:9": (960, 416)},
        "720p": {"16:9": (1280, 720), "9:16": (720, 1280), "1:1": (960, 960), "4:3": (1112, 834), "3:4": (834, 1112), "21:9": (1470, 630)},
        "1080p": {"16:9": (1920, 1080), "9:16": (1080, 1920), "1:1": (1440, 1440), "4:3": (1664, 1248), "3:4": (1248, 1664), "21:9": (2206, 946)}}
RATIOS = {"16:9", "9:16", "1:1", "4:3", "3:4", "21:9", "adaptive"}
ROLES = {"first_frame", "last_frame", "reference_image"}
ARK_SUBMIT = "/doubao/api/v3/contents/generations/tasks"


def tiny_png() -> bytes:
    def chunk(tag, data):
        c = struct.pack(">I", len(data)) + tag + data
        return c + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
    raw = b"".join(b"\x00" + b"\x20\x80\xc0" * 4 for _ in range(4))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 4, 4, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


class State:
    def __init__(self, args):
        self.lock = threading.Lock()
        self.tasks: dict = {}
        self.log: list = []
        self.n_submitted = 0
        self.stats = {"posts": 0, "polls": 0, "downloads_ok": 0, "cdn_rejections": 0, "rejected_short": 0,
                      "poll_429_served": 0, "download_503_served": 0, "submit_errors_served": 0}
        self.cfg = {"key": args.key, "polls_to_done": args.polls_to_done, "fail_nth": list(args.fail_nth or []),
                    "fail_contains": args.fail_contains, "poll_429": args.poll_429, "download_503": args.download_503,
                    "submit_status": args.submit_status, "submit_errors": args.submit_errors,
                    "leak_key_in_errors": args.leak_key_in_errors, "drop_poll": 0, "fail_status": "failed",
                    "cdn_only_curl": False, "truncate_download": 0, "truncate_frac": 0.33, "omit_video_url": 0, "reject_expires": False}
        self.tmp = Path(tempfile.mkdtemp(prefix="mock_ephone_", dir=getattr(args, "tmp_dir", None)))
        self.clip_cache: dict = {}
        self.base = ""

    def make_clip(self, w: int, h: int, dur: int, audio: bool, tone: int) -> bytes:
        key = (w, h, dur, audio, tone)
        with self.lock:
            if key in self.clip_cache:
                return self.clip_cache[key]
        out = self.tmp / f"clip_{w}x{h}_{dur}_{int(audio)}_{tone}.mp4"
        cmd = ["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"testsrc=size={w}x{h}:rate=24:duration={dur},hue=h={(tone * 37) % 360}"]
        if audio:
            cmd += ["-f", "lavfi", "-i", f"sine=frequency={tone}:sample_rate=48000:duration={dur}"]
        cmd += ["-c:v", "libx264", "-preset", "ultrafast", "-crf", "30", "-pix_fmt", "yuv420p", "-r", "24"]
        if audio:
            cmd += ["-c:a", "aac", "-b:a", "96k", "-ac", "2"]
        cmd += ["-t", str(dur), "-movflags", "+faststart", str(out)]
        subprocess.run(cmd, check=True, capture_output=True, timeout=120)
        data = out.read_bytes()
        with self.lock:
            self.clip_cache[key] = data
        return data


def trunc(obj):
    if isinstance(obj, dict):
        return {k: trunc(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [trunc(v) for v in obj]
    if isinstance(obj, str) and obj.startswith("data:") and len(obj) > 60:
        return obj[:40] + f"...<+{len(obj) - 40}>"
    return obj


class Handler(BaseHTTPRequestHandler):
    server_version = "MockEphone/1.0"
    state: State

    def log_message(self, *a):  # silence default access log (it would be harmless, but keep stderr clean)
        pass

    # ---- helpers
    def _auth_state(self) -> str:
        want = self.state.cfg.get("key")
        got = self.headers.get("Authorization")
        if not got:
            return "none"
        if want and got != "Bearer " + want:
            return "bad"
        return "ok"

    def _send(self, status: int, payload, ctype="application/json", headers=None):
        body = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)
        self._last_status = status

    def _err(self, status: int, code: str, message: str, param: str | None = None, headers=None):
        if self.state.cfg.get("leak_key_in_errors"):
            message += f" (received credentials: {self.headers.get('Authorization')})"
        err = {"code": code, "message": message, "type": "BadRequest" if status < 500 else "ServerError"}
        if param:
            err["param"] = param
        self._send(status, {"error": err}, headers=headers)

    def _record(self, kind: str, body=None):
        with self.state.lock:
            self.state.log.append({"t": round(time.time(), 3), "kind": kind, "method": self.command, "path": self.path.split("?")[0],
                                   "ua": self.headers.get("User-Agent"), "auth": self._auth_state(),
                                   "status": getattr(self, "_last_status", None), "body": trunc(body)})

    def _read_json(self):
        n = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(n) if n else b""
        try:
            return json.loads(raw.decode() or "null"), None
        except ValueError as e:
            return None, f"invalid JSON body: {e}"

    # ---- routing
    def do_GET(self):
        self._last_status = None
        path = urlsplit(self.path).path
        if path.startswith("/__mock/"):
            return self._control_get(path)
        if path.startswith("/cdn/"):
            return self._cdn(path)
        if self._auth_state() == "bad" or (self.state.cfg.get("key") and self._auth_state() == "none"):
            self._err(401, "Unauthorized", "invalid api key")
            return self._record("api")
        if path == "/v1/models":
            self._send(200, {"object": "list", "data": [{"id": m, "object": "model", "owned_by": "mock"} for m in FAKE_MODELS]})
            return self._record("api")
        m = re.fullmatch(r"/doubao/api/v3/contents/generations/tasks/([\w-]+)", path)
        if m:
            self._poll(m.group(1), "ark")
            return self._record("api")
        m = re.fullmatch(r"/v1/task/([\w-]+)", path)
        if m:
            self._poll(m.group(1), "task")
            return self._record("api")
        self._err(404, "NotFound", f"no route {path}")
        self._record("api")

    def do_POST(self):
        self._last_status = None
        path = urlsplit(self.path).path
        body, jerr = self._read_json()
        if path.startswith("/__mock/"):
            return self._control_post(path, body)
        if self._auth_state() == "bad" or (self.state.cfg.get("key") and self._auth_state() == "none"):
            self._err(401, "Unauthorized", "invalid api key")
            return self._record("api", body)
        if path == ARK_SUBMIT:
            self._submit(body, jerr, "ark")
        elif path == "/v1/task/submit":
            self._submit(body, jerr, "task")
        else:
            self._err(404, "NotFound", f"no route {path}")
        self._record("api", body)

    # ---- control plane
    def _control_get(self, path):
        if path == "/__mock/requests":
            with self.state.lock:
                return self._send(200, list(self.state.log))
        if path == "/__mock/tasks":
            with self.state.lock:
                return self._send(200, {tid: {"n": t["n"], "tone": 220 + 60 * (t["n"] % 8), "profile": t["profile"], "polls": t["polls"],
                                              "fail": t["fail"], "duration": t["duration"], "prompt": t["prompt"]}
                                        for tid, t in self.state.tasks.items()})
        if path == "/__mock/stats":
            with self.state.lock:
                return self._send(200, {**self.state.stats, "tasks": len(self.state.tasks)})
        self._send(404, {"error": "unknown control path"})

    def _control_post(self, path, body):
        if path == "/__mock/reset":
            with self.state.lock:
                self.state.log.clear()
                for k in self.state.stats:
                    self.state.stats[k] = 0
            return self._send(200, {"ok": True})
        if path == "/__mock/config":
            with self.state.lock:
                self.state.cfg.update(body or {})
            return self._send(200, {"ok": True, "config": {k: v for k, v in self.state.cfg.items() if k != "key"}})
        self._send(404, {"error": "unknown control path"})

    # ---- submit
    def _submit(self, body, jerr, profile):
        st = self.state
        if jerr:
            return self._err(400, "InvalidParameter", jerr)
        if not isinstance(body, dict):
            return self._err(400, "InvalidParameter", "body must be a JSON object")
        model = body.get("model")
        if model not in SEEDANCE_MODELS:
            return self._err(404, "ModelNotFound", f"model {model!r} does not exist or you have no access")
        p = body if profile == "ark" else body.get("input")
        if not isinstance(p, dict):
            return self._err(400, "InvalidParameter", "missing 'input' object", "input")
        if "execution_expires_after" in p and st.cfg.get("reject_expires"):
            return self._err(400, "InvalidParameter", "parameter 'execution_expires_after' is not supported by this gateway",
                             "execution_expires_after")
        if "seed" in p and "2-5" in model:
            return self._err(400, "InvalidParameter", "parameter 'seed' is not supported by this model", "seed")
        dur = p.get("duration", 5)
        if not (isinstance(dur, int) and not isinstance(dur, bool) and (4 <= dur <= 30 or dur == -1)):
            with st.lock:
                st.stats["rejected_short"] += 1
            return self._err(400, "InvalidParameter", f"duration {dur!r} is invalid: must be an integer in [4, 30] or -1", "duration")
        res = p.get("resolution", "720p")
        ratio = p.get("ratio", "16:9")
        if res not in DIMS or ratio not in RATIOS:
            return self._err(400, "InvalidParameter", f"unsupported resolution/ratio {res!r}/{ratio!r}", "resolution")
        content = p.get("content")
        prompt = None
        roles = []
        if isinstance(content, list):
            for item in content:
                if not isinstance(item, dict):
                    return self._err(400, "InvalidParameter", "content items must be objects", "content")
                if item.get("type") == "text":
                    prompt = item.get("text")
                elif item.get("type") in ("image_url", "video_url", "audio_url"):
                    url = (item.get(item["type"]) or {}).get("url", "")
                    if not url.startswith(("http://", "https://", "data:", "asset://")):
                        return self._err(400, "InvalidParameter", "media url must be http(s), data: or asset://", "content")
                    if url.startswith("data:"):
                        try:
                            base64.b64decode(url.split(",", 1)[1], validate=True)
                        except Exception:
                            return self._err(400, "InvalidParameter", "invalid base64 data url", "content")
                    role = item.get("role")
                    if item["type"] == "image_url" and role not in ROLES:
                        return self._err(400, "InvalidParameter", f"invalid image role {role!r}", "content")
                    roles.append(role)
        elif profile == "task" and isinstance(p.get("prompt"), str):
            prompt = p["prompt"]
        if not isinstance(prompt, str) or not prompt.strip():
            return self._err(400, "InvalidParameter", "a non-empty text prompt is required", "content")
        if ("reference_image" in roles) and ({"first_frame", "last_frame"} & set(roles)):
            return self._err(400, "InvalidParameter", "first/last-frame mode cannot be mixed with reference images", "content")
        if "last_frame" in roles and "first_frame" not in roles:
            return self._err(400, "InvalidParameter", "last_frame requires first_frame", "content")
        if len([r for r in roles if r == "reference_image"]) > 9:
            return self._err(400, "InvalidParameter", "at most 9 reference images", "content")

        with st.lock:
            if st.cfg.get("submit_errors", 0) > 0:
                st.cfg["submit_errors"] -= 1
                st.stats["submit_errors_served"] += 1
                code = int(st.cfg.get("submit_status") or 500)
                inject = True
            else:
                inject = False
        if inject:
            return self._err(code, "InternalError", "injected submit failure (no task created)")
        with st.lock:
            st.n_submitted += 1
            n = st.n_submitted
            st.stats["posts"] += 1
            tid = ("cgt-" if profile == "ark" else "task_") + uuid.uuid4().hex[:20]
            fail = n in st.cfg.get("fail_nth", []) or (st.cfg.get("fail_contains") and st.cfg["fail_contains"] in prompt)
            st.tasks[tid] = {"id": tid, "profile": profile, "model": model, "prompt": prompt, "n": n, "polls": 0,
                             "created_at": int(time.time()), "fail": bool(fail), "duration": 4 if dur == -1 else dur,
                             "resolution": res, "ratio": ratio, "audio": bool(p.get("generate_audio", True)),
                             "last_frame": bool(p.get("return_last_frame"))}
        if profile == "ark":
            self._send(200, {"id": tid})
        else:
            self._send(200, {"id": tid, "status": "queued", "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())})

    # ---- poll
    def _poll(self, tid, profile):
        st = self.state
        with st.lock:
            drop = False
            if st.cfg.get("drop_poll", 0) > 0:
                st.cfg["drop_poll"] -= 1
                st.stats["polls_dropped"] = st.stats.get("polls_dropped", 0) + 1
                drop = True
            if st.cfg.get("poll_429", 0) > 0 and not drop:
                st.cfg["poll_429"] -= 1
                st.stats["poll_429_served"] += 1
                inject = True
            else:
                inject = False
            t = st.tasks.get(tid)
            if t and not inject and not drop:
                t["polls"] += 1
                st.stats["polls"] += 1
        if drop:                                   # connection closed without any response (network error)
            self.close_connection = True
            return
        if inject:
            return self._err(429, "TooManyRequests", "rate limit exceeded", headers={"Retry-After": "0"})
        if not t or t["profile"] != profile:
            return self._err(404, "NotFound", f"task {tid} not found")
        done_at = int(st.cfg.get("polls_to_done", 3))
        k = t["polls"]
        status = "queued" if k <= 1 else ("running" if k < done_at else "terminal")
        w, h = DIMS[t["resolution"]].get(t["ratio"], DIMS[t["resolution"]]["16:9"])
        tokens = round(t["duration"] * w * h * 24 / 1024 * 1.0104)
        omit = False
        if status == "terminal" and not t["fail"]:
            with st.lock:
                if st.cfg.get("omit_video_url", 0) > 0:
                    st.cfg["omit_video_url"] -= 1
                    omit = True
        if profile == "ark":
            out = {"id": tid, "model": t["model"], "status": "queued", "content": None, "error": None,
                   "created_at": t["created_at"], "updated_at": int(time.time())}
            if status == "running":
                out["status"] = "running"
            elif status == "terminal":
                if t["fail"]:
                    fs = st.cfg.get("fail_status", "failed")
                    out.update(status=fs, error={"code": "OutputVideoSensitiveContentDetected",
                                                 "message": "The request failed because the output video may contain sensitive information."}
                               if fs == "failed" else None)
                else:
                    sig = hashlib.sha1((tid + "mock").encode()).hexdigest()[:16]
                    content = {} if omit else {"video_url": f"{st.base}/cdn/{tid}.mp4?sig={sig}&expires={int(time.time()) + 86400}"}
                    if t["last_frame"] and not omit:
                        content["last_frame_url"] = f"{st.base}/cdn/{tid}_last.png?sig={sig}"
                    out.update(status="succeeded", content=content, usage={"completion_tokens": tokens, "total_tokens": tokens},
                               seed=123456, resolution=t["resolution"], ratio=t["ratio"], duration=t["duration"],
                               framespersecond=24, generate_audio=t["audio"], service_tier="default")
            return self._send(200, out)
        out = {"id": tid, "status": "queued", "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(t["created_at"])),
               "completed_at": None, "outputs": [], "error": None}
        if status == "running":
            out["status"] = "in_progress"
        elif status == "terminal":
            out["completed_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            if t["fail"]:
                out.update(status="failed", error="generation failed: output video may contain sensitive information")
            else:
                sig = hashlib.sha1((tid + "mock").encode()).hexdigest()[:16]
                out.update(status="completed", outputs=[] if omit else [f"{st.base}/cdn/{tid}.mp4?sig={sig}"])
        self._send(200, out)

    # ---- CDN
    def _cdn(self, path):
        st = self.state
        ua = self.headers.get("User-Agent", "")
        name = path.rsplit("/", 1)[-1]
        if self.headers.get("Authorization"):
            # the real CDN is a different host: an API key must never be sent there
            self._send(400, {"error": "Authorization header must not be sent to the CDN"})
            return self._record("cdn")
        if ua.startswith("Python-urllib") or not ua:
            with st.lock:
                st.stats["cdn_rejections"] += 1
            self._send(403, b"<html><body>403 Forbidden (bot user agent)</body></html>", "text/html")
            return self._record("cdn")
        if st.cfg.get("cdn_only_curl") and not ua.startswith("curl/"):
            with st.lock:
                st.stats["cdn_rejections"] += 1
            self._send(403, b"<html><body>403 Forbidden (this CDN only talks to curl)</body></html>", "text/html")
            return self._record("cdn")
        with st.lock:
            if st.cfg.get("download_503", 0) > 0:
                st.cfg["download_503"] -= 1
                st.stats["download_503_served"] += 1
                inject = True
            else:
                inject = False
        if inject:
            self._send(503, b"service unavailable", "text/plain", headers={"Retry-After": "0"})
            return self._record("cdn")
        m = re.fullmatch(r"([\w-]+?)(_last\.png|\.mp4)", name)
        t = st.tasks.get(m.group(1)) if m else None
        if not t:
            self._send(404, b"not found", "text/plain")
            return self._record("cdn")
        sig = hashlib.sha1((t["id"] + "mock").encode()).hexdigest()[:16]
        if parse_qs(urlsplit(self.path).query).get("sig", [""])[0] != sig:
            self._send(403, b"bad signature", "text/plain")
            return self._record("cdn")
        if m.group(2) == "_last.png":
            data, ctype = tiny_png(), "image/png"
        else:
            w, h = DIMS[t["resolution"]].get(t["ratio"], DIMS[t["resolution"]]["16:9"])
            try:
                data = st.make_clip(w, h, t["duration"], t["audio"], 220 + 60 * (t["n"] % 8))
            except Exception as e:
                self._send(500, f"ffmpeg failed: {e}".encode(), "text/plain")
                return self._record("cdn")
            ctype = "video/mp4"
        with st.lock:
            cut = m.group(2) == ".mp4" and st.cfg.get("truncate_download", 0) > 0
            if cut:
                st.cfg["truncate_download"] -= 1
                st.stats["downloads_truncated"] = st.stats.get("downloads_truncated", 0) + 1
            else:
                st.stats["downloads_ok"] += 1
        if cut:                                    # no Content-Length: the body just ends early when the connection closes
            frac = float(st.cfg.get("truncate_frac", 0.33))
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.end_headers()
            self.wfile.write(data[:max(32, int(len(data) * frac))])
            self.wfile.flush()
            self.close_connection = True
            self._last_status = 200
            return self._record("cdn")
        self._send(200, data, ctype)
        self._record("cdn")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--host", default="127.0.0.1", help="loopback only (default 127.0.0.1)")
    ap.add_argument("--port", type=int, default=0, help="0 = pick a free port")
    ap.add_argument("--key", help="expected API key (Authorization: Bearer <key>); default: accept any")
    ap.add_argument("--polls-to-done", type=int, default=3)
    ap.add_argument("--fail-nth", type=int, action="append")
    ap.add_argument("--fail-contains")
    ap.add_argument("--poll-429", type=int, default=0)
    ap.add_argument("--download-503", type=int, default=0)
    ap.add_argument("--submit-status", type=int, default=500)
    ap.add_argument("--submit-errors", type=int, default=0)
    ap.add_argument("--leak-key-in-errors", action="store_true")
    ap.add_argument("--port-file", help="write the base URL here once listening")
    ap.add_argument("--tmp-dir", help="parent directory for the mock's scratch dir (default: the system temp dir)")
    args = ap.parse_args(argv)
    if args.host not in ("127.0.0.1", "localhost", "::1"):
        print("mock_server.py only binds to loopback", file=sys.stderr)
        return 2
    st = State(args)
    Handler.state = st
    try:
        srv = ThreadingHTTPServer((args.host, args.port), Handler)
        srv.daemon_threads = True
        st.base = f"http://{args.host}:{srv.server_address[1]}"

        def _stop(signum, frame):                  # SIGTERM/SIGHUP would otherwise skip the cleanup below
            raise SystemExit(0)
        for sig in (signal.SIGTERM, signal.SIGHUP):
            signal.signal(sig, _stop)
        print(f"MOCK_LISTENING {st.base}", flush=True)
        if args.port_file:
            Path(args.port_file).write_text(st.base)
        try:
            srv.serve_forever()
        except (KeyboardInterrupt, SystemExit):
            pass
        finally:
            srv.server_close()
    finally:
        shutil.rmtree(st.tmp, ignore_errors=True)  # never leave mock_ephone_* behind
    return 0


if __name__ == "__main__":
    sys.exit(main())
