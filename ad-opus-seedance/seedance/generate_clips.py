#!/usr/bin/env python3
"""Seedance 2.5 clip generator for the Ephone gateway (stdlib only).

Reads ../shotlist.json, submits one video task per shot, persists the task id to
out/clips/<shot>.json IMMEDIATELY after the submit, polls until a terminal state and
downloads out/clips/<shot>.mp4.

Safety rules baked in:
  * nothing is ever submitted without --yes (--probe / --dry-run / --resume-task send nothing paid)
  * a POST submit is NEVER retried (a retried submit double-bills); GETs/downloads are
  * budget caps (--budget-max-cny, --budget-max-clips) are checked BEFORE the first submit, against the estimate of the
    FINAL request body (an --extra-json resolution/ratio/duration override is priced; NaN/inf caps are rejected)
  * a task that already has an id is never resubmitted unless --force: that includes a task that succeeded without a
    video url (state no_video_url) and a sidecar that exists but cannot be parsed (the shot is REFUSED)
  * a download is kept only if it is a complete, decodable mp4 of about the task duration (else download_failed, task id kept)
  * the API key comes from the EPHONE_API_KEY env var only; it is never printed, never
    written to disk and is redacted from every message, sidecar and exception
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import math
import os
import random
import re
import shutil
import subprocess
import sys
import time
import traceback
import urllib.error
import urllib.parse
import urllib.request
from collections import deque
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_BASE_URL = "https://api.ephone.ai"
DEFAULT_MODEL = "doubao-seedance-2-5-260628"
BROWSER_UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")
MIN_DURATION, MAX_DURATION = 4, 30
MAX_REFERENCE_IMAGES = 9
MAX_LOCAL_IMAGE_BYTES = 30 * 1024 * 1024
FAIL_STATES = {"failed", "cancelled", "canceled", "expired"}
# only these sidecar states may lead to a NEW (paid) submit on a re-run. Everything else that carries a task id
# (including "no_video_url": the task succeeded and was billed, only the url is missing) is resumed, never resubmitted.
RETRYABLE_SUBMIT_STATES = {"failed", "cancelled", "canceled", "expired", "submit_failed"}
UNKNOWN_SUBMIT_STATES = {"submitting", "submit_unknown"}
ID_RE = re.compile(r"^[A-Za-z0-9_-]+$")              # shot ids become file names
LAST_FRAME_EXTS = (".png", ".jpg", ".jpeg", ".webp")
MIN_DOWNLOAD_RATIO = 0.95                            # a download shorter than this x the task duration is truncated
EXPIRES_AFTER_S = 172800                             # execution_expires_after sent on the ark profile (drop: --no-expires)

EXIT_OK, EXIT_FAIL, EXIT_USAGE, EXIT_BUDGET = 0, 1, 2, 3

# Output frame size used ONLY for the cost estimate (provider-side sizes are approximate).
RATIOS = ("16:9", "9:16", "1:1", "4:3", "3:4", "21:9", "adaptive")
DIMS = {
    "480p": {"16:9": (864, 480), "9:16": (480, 864), "1:1": (640, 640), "4:3": (736, 544),
             "3:4": (544, 736), "21:9": (960, 416)},
    "720p": {"16:9": (1280, 720), "9:16": (720, 1280), "1:1": (960, 960), "4:3": (1112, 834),
             "3:4": (834, 1112), "21:9": (1470, 630)},
    "1080p": {"16:9": (1920, 1080), "9:16": (1080, 1920), "1:1": (1440, 1440), "4:3": (1664, 1248),
              "3:4": (1248, 1664), "21:9": (2206, 946)},
}
PRICE_CNY_PER_MTOK = {"480p": 70.0, "720p": 70.0, "1080p": 77.0}
CNY_PER_USD = 7.0
# Calibrated on one measured clip: 4 s, 720p, 16:9 = 87,300 tokens (raw formula gives 86,400).
TOKEN_CALIBRATION = 87300 / (4 * 1280 * 720 * 24 / 1024)

PROFILES = {
    "ephone-ark": {"submit": "/doubao/api/v3/contents/generations/tasks",
                   "poll": "/doubao/api/v3/contents/generations/tasks/{id}"},
    "ephone-task": {"submit": "/v1/task/submit", "poll": "/v1/task/{id}"},
}

# ----------------------------------------------------------------------------- redaction
_SECRETS: set = set()


def register_secret(s: str) -> None:
    if s and len(s) >= 4:
        _SECRETS.add(s)
        _SECRETS.add(urllib.parse.quote(s, safe=""))
        _SECRETS.add(base64.b64encode(s.encode()).decode().rstrip("="))


def redact(text) -> str:
    text = str(text)
    for s in sorted(_SECRETS, key=len, reverse=True):
        text = text.replace(s, "<REDACTED>")
    return re.sub(r"(?i)(bearer\s+)[A-Za-z0-9._~+/=\-]{8,}", r"\1<REDACTED>", text)


def say(*parts, err: bool = False) -> None:
    print(redact(" ".join(str(p) for p in parts)), file=sys.stderr if err else sys.stdout, flush=True)


def _excepthook(tp, val, tb):
    say("ERROR (unhandled):", "".join(traceback.format_exception(tp, val, tb)), err=True)


sys.excepthook = _excepthook


class UsageError(Exception):
    pass


class SidecarError(Exception):
    """A sidecar file exists but cannot be parsed: a paid task id may be inside it."""
    def __init__(self, path: Path, why: str, salvaged: str | None = None):
        super().__init__(f"{path.name} exists but cannot be parsed ({why})")
        self.path, self.salvaged = path, salvaged


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def safe_url(u: str) -> str:
    """scheme://host/path without the (signed) query string."""
    try:
        p = urllib.parse.urlsplit(u)
        return f"{p.scheme}://{p.netloc}{p.path}"
    except Exception:
        return "<url>"


def is_loopback_url(u: str) -> bool:
    try:
        host = urllib.parse.urlsplit(u).hostname or ""
    except Exception:
        return False
    return host in ("127.0.0.1", "localhost", "::1")


def write_json_atomic(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = redact(json.dumps(obj, indent=2, ensure_ascii=False))
    tmp = path.with_name(path.name + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(text + "\n")
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


# ----------------------------------------------------------------------------- cost
def frame_dims(resolution: str, ratio: str):
    table = DIMS[resolution]
    return table.get(ratio, table["16:9"])  # "adaptive" -> assume 16:9


def estimate_cost(duration: int, resolution: str, ratio: str) -> dict:
    w, h = frame_dims(resolution, ratio)
    tokens = round(duration * w * h * 24 / 1024 * TOKEN_CALIBRATION)
    cny = tokens * PRICE_CNY_PER_MTOK[resolution] / 1e6
    return {"tokens": tokens, "cny": round(cny, 4), "usd": round(cny / CNY_PER_USD, 4), "width": w, "height": h,
            "resolution": resolution, "ratio": ratio, "duration": duration}


# ----------------------------------------------------------------------------- HTTP
class NetError(Exception):
    pass


class Resp:
    def __init__(self, status: int, headers, body: bytes):
        self.status, self.headers, self.body = status, headers, body

    def text(self, limit: int = 600) -> str:
        return redact(self.body.decode("utf-8", "replace")[:limit]).replace("\n", " ")

    def json(self):
        return json.loads(self.body.decode("utf-8"))


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):  # never forward the Authorization header to another host
        return None


def _opener(url: str, follow_redirects: bool):
    handlers = []
    if is_loopback_url(url):
        handlers.append(urllib.request.ProxyHandler({}))
    if not follow_redirects:
        handlers.append(_NoRedirect())
    return urllib.request.build_opener(*handlers)


def http_request(method: str, url: str, headers: dict, data: bytes | None = None,
                 timeout: float = 60, follow_redirects: bool = False) -> Resp:
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with _opener(url, follow_redirects).open(req, timeout=timeout) as r:
            return Resp(r.status, r.headers, r.read())
    except urllib.error.HTTPError as e:
        try:
            body = e.read()
        except Exception:
            body = b""
        return Resp(e.code, e.headers, body)
    except Exception as e:  # URLError, timeouts, resets, http.client errors
        raise NetError(redact(f"{type(e).__name__}: {e}")) from None


def _retry_after(resp: Resp | None) -> float | None:
    if resp is None:
        return None
    try:
        return float(resp.headers.get("Retry-After"))
    except (TypeError, ValueError):
        return None


def with_retries(fn, *, retries: int, base: float, what: str):
    """Retry fn() on network errors, 429 and 5xx with exponential backoff. fn returns a Resp."""
    last_resp, last_exc = None, None
    for attempt in range(retries + 1):
        try:
            resp = fn()
        except NetError as e:
            last_exc, last_resp, why = e, None, str(e)
        else:
            if resp.status != 429 and not (500 <= resp.status < 600):
                return resp
            last_resp, last_exc, why = resp, None, f"HTTP {resp.status}"
        if attempt == retries:
            break
        delay = min(60.0, base * (2 ** attempt)) * (0.75 + random.random() * 0.5)
        ra = _retry_after(last_resp)
        if ra is not None:
            delay = max(delay, min(ra, 60.0))
        say(f"    retry {attempt + 1}/{retries} for {what} ({why}); sleeping {delay:.1f}s")
        time.sleep(delay)
    if last_exc is not None:
        raise last_exc
    return last_resp


class Client:
    def __init__(self, base_url: str, key: str | None, retries: int, retry_base: float):
        self.base_url, self.key, self.retries, self.retry_base = base_url, key, retries, retry_base

    def _headers(self) -> dict:
        h = {"Content-Type": "application/json", "Accept": "application/json", "User-Agent": BROWSER_UA}
        if self.key:
            h["Authorization"] = "Bearer " + self.key
        return h

    def api(self, method: str, path: str, body: dict | None = None, retries: int = 0, timeout: float = 60) -> Resp:
        url = self.base_url + path
        data = None if body is None else json.dumps(body).encode()
        return with_retries(lambda: http_request(method, url, self._headers(), data, timeout),
                            retries=retries, base=self.retry_base, what=f"{method} {path.split('/')[-1][:24]}")

    def download(self, url: str, dest: Path, expect_s: float | None = None) -> int:
        """Download a CDN url to dest (atomic). Browser-like UA, NO Authorization header.
        The file is checked (mp4 header, decodable, long enough for expect_s) BEFORE it is moved into place; a truncated
        or corrupt body is retried like a network error."""
        part = dest.with_name(dest.name + ".part")

        def once() -> Resp:
            req = urllib.request.Request(url, headers={"User-Agent": BROWSER_UA, "Accept": "*/*"})
            try:
                with _opener(url, True).open(req, timeout=120) as r, open(part, "wb") as f:
                    shutil.copyfileobj(r, f, 1024 * 1024)
                    status, headers = r.status, r.headers
            except urllib.error.HTTPError as e:
                return Resp(e.code, e.headers, e.read()[:2000])
            except Exception as e:
                raise NetError(redact(f"{type(e).__name__}: {e}")) from None
            if status == 200:
                _check_mp4(part, expect_s)                       # raises NetError -> retried by with_retries
            return Resp(status, headers, b"")

        resp = with_retries(once, retries=self.retries, base=self.retry_base, what="download " + safe_url(url)[-40:])
        if resp.status != 200:
            part.unlink(missing_ok=True)
            raise DownloadHttpError(resp.status, resp.text())
        os.replace(part, dest)
        return dest.stat().st_size

    def download_curl(self, url: str, dest: Path, expect_s: float | None = None) -> int:
        """Last-resort fallback: the CDN is known to accept curl's user agent. No Authorization header."""
        curl = shutil.which("curl")
        if not curl:
            raise NetError("curl is not installed, cannot use the curl fallback")
        part = dest.with_name(dest.name + ".part")
        proc = subprocess.run([curl, "-sS", "-L", "--fail", "--retry", str(self.retries), "--retry-delay", "1",
                               "-A", "curl/8.5.0", "-o", str(part), url], capture_output=True, text=True, timeout=600)
        if proc.returncode != 0:
            part.unlink(missing_ok=True)
            raise NetError(redact(f"curl exit {proc.returncode}: {proc.stderr.strip()[:200]}"))
        _check_mp4(part, expect_s)
        os.replace(part, dest)
        return dest.stat().st_size

    def download_any(self, url: str, dest: Path) -> int:
        """Download a small non-mp4 asset (last frame png/jpg). No Authorization header either."""
        resp = with_retries(lambda: http_request("GET", url, {"User-Agent": BROWSER_UA, "Accept": "*/*"}, None, 120, True),
                            retries=self.retries, base=self.retry_base, what="last frame")
        if resp.status != 200:
            raise DownloadHttpError(resp.status, resp.text())
        dest.write_bytes(resp.body)
        return len(resp.body)


def _check_mp4(part: Path, expect_s: float | None) -> None:
    """Reject (and delete) a downloaded body that is not a complete, decodable mp4."""
    with open(part, "rb") as f:
        head = f.read(16)
    if head[4:8] != b"ftyp":
        part.unlink(missing_ok=True)
        raise NetError(f"downloaded file is not an mp4 (first bytes: {head[:12]!r})")
    ok, why = verify_mp4(part, expect_s)
    if not ok:
        part.unlink(missing_ok=True)
        raise NetError(f"downloaded mp4 is truncated or corrupt: {why}")


def _parse_rate(r) -> float:
    try:
        a, _, b = str(r).partition("/")
        v = float(a) / float(b or 1)
        return v if v > 0 else 24.0
    except (ValueError, ZeroDivisionError):
        return 24.0


def verify_mp4(path: Path, expect_s: float | None) -> tuple[bool, str]:
    """(ok, reason). Needs ffprobe + ffmpeg: container must be readable, the whole stream must decode without errors
    and the video must last at least MIN_DOWNLOAD_RATIO x expect_s (both by container duration and by decoded frames).
    Without ffmpeg/ffprobe the check is skipped (with a warning) instead of blocking the download."""
    if not (shutil.which("ffprobe") and shutil.which("ffmpeg")):
        say("    WARNING: ffprobe/ffmpeg not found, the truncated-download check is skipped")
        return True, "check skipped"
    try:
        pr = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_type,r_frame_rate",
                             "-show_entries", "format=duration", "-of", "json", str(path)],
                            capture_output=True, text=True, timeout=60)
        j = json.loads(pr.stdout or "{}")
        vs = next((x for x in j.get("streams", []) if x.get("codec_type") == "video"), None)
        if pr.returncode != 0 or vs is None:
            return False, f"ffprobe cannot read it ({(pr.stderr or 'no video stream').strip()[:160]})"
        dur = float((j.get("format") or {}).get("duration") or 0)
        fps = _parse_rate(vs.get("r_frame_rate"))
        dc = subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-i", str(path), "-map", "0:v:0", "-map", "0:a?",
                             "-f", "null", "-progress", "pipe:1", "-"], capture_output=True, text=True, timeout=300)
    except (subprocess.TimeoutExpired, ValueError, OSError) as e:
        return False, f"could not be verified ({type(e).__name__}: {e})"
    errs = (dc.stderr or "").strip()
    if dc.returncode != 0 or errs:
        return False, f"decode errors ({errs.splitlines()[0][:160] if errs else 'rc ' + str(dc.returncode)})"
    frames = 0
    for line in dc.stdout.splitlines():
        if line.startswith("frame="):
            try:
                frames = int(line.split("=", 1)[1])
            except ValueError:
                pass
    if expect_s:
        need_s = MIN_DOWNLOAD_RATIO * expect_s
        if dur < need_s or frames < need_s * fps - 1e-6:
            return False, (f"only {dur:.2f} s / {frames} frames, expected about {expect_s:g} s "
                           f"(>= {need_s:.2f} s / {math.ceil(need_s * fps)} frames)")
    elif frames < 1:
        return False, "no decodable video frames"
    return True, f"{dur:.2f} s / {frames} frames"


class DownloadHttpError(Exception):
    def __init__(self, status: int, text: str):
        super().__init__(f"HTTP {status}: {text}")
        self.status = status


# ----------------------------------------------------------------------------- request building
def parse_duration(v: str) -> int:
    try:
        d = int(v)
    except ValueError:
        raise argparse.ArgumentTypeError(f"duration must be an integer, got {v!r}")
    if d < MIN_DURATION:
        raise argparse.ArgumentTypeError(
            f"duration {d} s is below the model minimum of {MIN_DURATION} s (Seedance 2.5 rejects shorter clips; "
            f"generate 4 s and let assemble_clips.py trim the window)")
    if d > MAX_DURATION:
        raise argparse.ArgumentTypeError(f"duration {d} s is above the model maximum of {MAX_DURATION} s")
    return d


def build_prompt(shot: dict, negative: str) -> str:
    p = shot["seedance_prompt"].strip()
    neg = (negative or "").strip()
    if neg:
        if p[-1] not in ".!?":
            p += "."
        neg = neg[0].upper() + neg[1:]
        if neg[-1] not in ".!?":
            neg += "."
        p += " " + neg
    return p


_IMG_MIME = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp",
             ".bmp": "image/bmp", ".tif": "image/tiff", ".tiff": "image/tiff", ".gif": "image/gif"}
_media_cache: dict = {}


def resolve_media(ref: str, project_dir: Path):
    """-> (url_for_request, summary_for_sidecar). Local files become base64 data URLs."""
    if ref.startswith(("http://", "https://", "asset://")):
        return ref, {"type": "url", "url": safe_url(ref) if ref.startswith("http") else ref}
    if ref.startswith("data:"):
        return ref, {"type": "data_url", "sha256": hashlib.sha256(ref.encode()).hexdigest()[:16]}
    if ref in _media_cache:
        return _media_cache[ref]
    p = Path(ref).expanduser()
    if not p.is_absolute() and not p.exists() and (project_dir / p).exists():
        p = project_dir / p
    if not p.is_file():
        raise UsageError(f"reference image not found: {ref}")
    mime = _IMG_MIME.get(p.suffix.lower())
    if not mime:
        raise UsageError(f"unsupported image type {p.suffix!r} for {ref} (use png/jpg/webp/bmp/tiff/gif)")
    raw = p.read_bytes()
    if len(raw) > MAX_LOCAL_IMAGE_BYTES:
        raise UsageError(f"{ref} is {len(raw) / 1e6:.1f} MB, above the 30 MB image limit")
    url = f"data:{mime};base64,{base64.b64encode(raw).decode()}"
    out = (url, {"type": "local_file", "path": str(ref), "bytes": len(raw),
                 "sha256": hashlib.sha256(raw).hexdigest()[:16]})
    _media_cache[ref] = out
    return out


def display_body(obj):
    """Deep copy with long data: URLs shortened (for dry-run output and sidecars)."""
    if isinstance(obj, dict):
        return {k: display_body(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [display_body(v) for v in obj]
    if isinstance(obj, str) and obj.startswith("data:") and len(obj) > 80:
        return f"{obj[:48]}...<+{len(obj) - 48} chars>"
    return obj


def deep_merge(dst: dict, src: dict) -> dict:
    for k, v in src.items():
        if isinstance(v, dict) and isinstance(dst.get(k), dict):
            deep_merge(dst[k], v)
        else:
            dst[k] = v
    return dst


def build_shot_request(shot: dict, args, negative: str, project_dir: Path) -> dict:
    over = shot.get("seedance") or {}
    refs = list(over.get("reference_images", args.reference_image or []))
    first = over.get("first_frame", args.first_frame)
    last = over.get("last_frame", args.last_frame)
    if (first or last) and refs:
        raise UsageError(f"{shot['id']}: first/last-frame mode cannot be mixed with reference images")
    if last and not first:
        raise UsageError(f"{shot['id']}: --last-frame needs --first-frame as well")
    if len(refs) > MAX_REFERENCE_IMAGES:
        raise UsageError(f"{shot['id']}: at most {MAX_REFERENCE_IMAGES} reference images ({len(refs)} given)")

    prompt = build_prompt(shot, negative)
    content = [{"type": "text", "text": prompt}]
    media = []
    for ref, role in [(first, "first_frame"), (last, "last_frame")] + [(r, "reference_image") for r in refs]:
        if not ref:
            continue
        url, summary = resolve_media(ref, project_dir)
        content.append({"type": "image_url", "image_url": {"url": url}, "role": role})
        media.append({"role": role, **summary})

    params = {"resolution": args.resolution, "ratio": args.ratio, "duration": args.duration,
              "generate_audio": bool(args.audio), "watermark": False,
              "return_last_frame": bool(args.return_last_frame)}
    if args.profile == "ephone-ark":
        body = {"model": args.model, "content": content, **params}
        if not getattr(args, "no_expires", False):
            body["execution_expires_after"] = EXPIRES_AFTER_S
        if args.extra_json:
            deep_merge(body, args.extra_json)
        final = body                                     # where resolution/ratio/duration/model really end up
    else:
        inp = {"content": content, **params}
        if args.extra_json:
            deep_merge(inp, args.extra_json)
        body = {"model": args.model, "input": inp}
        final = inp
    # Everything that drives the price is read from the FINAL body (after --extra-json), never from the CLI flags,
    # so the estimate and the budget check always describe what is really sent.
    dur, res, ratio = final.get("duration"), final.get("resolution"), final.get("ratio")
    model = body.get("model")
    if not isinstance(dur, int) or isinstance(dur, bool) or dur < MIN_DURATION:
        raise UsageError(f"{shot['id']}: duration {dur!r} is below the {MIN_DURATION} s model minimum")
    if dur > MAX_DURATION:
        raise UsageError(f"{shot['id']}: duration {dur!r} is above the {MAX_DURATION} s model maximum")
    if res not in DIMS:
        raise UsageError(f"{shot['id']}: resolution {res!r} is not one of {list(DIMS)} (cannot estimate the cost)")
    if ratio not in RATIOS:
        raise UsageError(f"{shot['id']}: ratio {ratio!r} is not one of {list(RATIOS)} (cannot estimate the cost)")
    if not isinstance(model, str) or not model:
        raise UsageError(f"{shot['id']}: model must be a non-empty string, got {model!r}")
    if "seed" in final and "seedance-2-5" in model:
        raise UsageError("Seedance 2.5 does not accept a 'seed' parameter")
    est = estimate_cost(dur, res, ratio)
    return {"shot": shot["id"], "prompt": prompt, "body": body, "estimate": est, "media": media,
            "params": {**params, "resolution": res, "ratio": ratio, "duration": dur, "model": model, "profile": args.profile}}


# ----------------------------------------------------------------------------- state normalisation
def normalize_status(profile: str, raw: dict) -> dict:
    """-> {"state": pending|succeeded|failed|no_video_url, "status": str, "video_url", "last_frame_url", "error"}
    'no_video_url' = the provider says the task finished OK (billed) but returned no url: never retryable as a new submit."""
    status = str(raw.get("status", "")).lower()
    out = {"status": status, "video_url": None, "last_frame_url": None, "error": None}
    if profile == "ephone-ark":
        content = raw.get("content") or {}
        out["video_url"] = content.get("video_url")
        out["last_frame_url"] = content.get("last_frame_url")
        out["error"] = raw.get("error")
        done = status == "succeeded"
    else:
        outputs = raw.get("outputs") or []
        urls = [o if isinstance(o, str) else (o.get("url") if isinstance(o, dict) else None) for o in outputs]
        urls = [u for u in urls if u]
        vids = [u for u in urls if safe_url(u).lower().endswith((".mp4", ".mov", ".webm"))]
        out["video_url"] = (vids or urls or [None])[0]
        out["error"] = raw.get("error")
        done = status == "completed"
    if done:
        out["state"] = "succeeded" if out["video_url"] else "no_video_url"
        if not out["video_url"]:
            out["error"] = {"code": "NoVideoUrl", "message": "task finished but the response has no video url "
                                                              "(the task is NOT resubmitted; re-run to poll the same task again)"}
    elif status in FAIL_STATES:
        out["state"] = "failed"
    else:
        out["state"] = "pending"
    return out


def provider_info(args) -> dict:
    """The provider settings that live as constants in this file (what a provider.json would have held). No secrets."""
    return {"source": "constants at the top of generate_clips.py; no provider.json exists",
            "base_url": args.base_url, "base_url_env": "EPHONE_BASE_URL", "api_key_env": "EPHONE_API_KEY (never printed or stored)",
            "default_profile": "ephone-ark", "profiles": PROFILES, "model": args.model, "default_model": DEFAULT_MODEL,
            "duration_s": {"min": MIN_DURATION, "max": MAX_DURATION},
            "execution_expires_after_s": None if args.no_expires else EXPIRES_AFTER_S,
            "pricing": {"cny_per_million_tokens": PRICE_CNY_PER_MTOK, "cny_per_usd": CNY_PER_USD,
                        "token_calibration": round(TOKEN_CALIBRATION, 6)},
            "cdn_user_agent": BROWSER_UA}


def fmt_error(err) -> str:
    if isinstance(err, dict):
        return f"{err.get('code', '?')}: {err.get('message', '')}".strip()
    return str(err) if err else "(no error object returned)"


# ----------------------------------------------------------------------------- job handling
class Job:
    def __init__(self, req: dict, clips_dir: Path, action: str):
        self.req, self.shot = req, req["shot"]
        self.action = action                       # submit | resume
        self.sidecar_path = clips_dir / f"{self.shot}.json"
        self.mp4 = clips_dir / f"{self.shot}.mp4"
        self.sc: dict = {}
        self.task_id: str | None = None
        self.t0 = time.monotonic()
        self.errors = 0
        self.last_status = None
        self.last_beat = time.monotonic()
        self.save_failed = False
        self.outcome = "pending"                   # downloaded | failed | timeout | poll_error | submit_failed ...
        self.detail = ""

    def save(self) -> bool:
        """Write the sidecar. Never raises: on a disk error it says so loudly (with the task id) and returns False."""
        self.sc["updated_at"] = now_iso()
        try:
            write_json_atomic(self.sidecar_path, self.sc)
            return True
        except OSError as e:
            if not self.save_failed:                   # say it once per job, loudly, with the id
                tid = self.task_id or self.sc.get("task_id")
                say(f"[{self.shot}] ERROR: cannot write {self.sidecar_path}: {e} (further sidecar updates of this shot are not saved)"
                    + (f"\n[{self.shot}] THE PAID TASK ID IS {tid} -- keep it. Resume with: generate_clips.py "
                       f"--resume-task {tid} --shot {self.shot}" if tid else ""), err=True)
            self.save_failed = True
            return False


def load_sidecar(path: Path) -> dict | None:
    """None when there is no sidecar. A sidecar that exists but is unreadable/invalid raises SidecarError (it may hold the
    id of a paid task, so it must never be silently treated as 'no previous task')."""
    if not path.exists():
        return None
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as e:
        raise SidecarError(path, f"{type(e).__name__}: {e}")
    try:
        data = json.loads(text)
        if not isinstance(data, dict):
            raise ValueError("not a JSON object")
    except ValueError as e:
        m = re.search(r'"task_id"\s*:\s*"([^"\s]+)"', text)
        raise SidecarError(path, str(e)[:80], m.group(1) if m else None)
    return data


def backup_corrupt_sidecar(path: Path) -> None:
    """Keep an unreadable sidecar as <name>.corrupt before a forced resubmit overwrites it."""
    if not path.exists():
        return
    try:
        load_sidecar(path)
    except SidecarError:
        try:
            shutil.copy2(path, path.with_name(path.name + ".corrupt"))
            say(f"[{path.stem}] unreadable sidecar kept as {path.name}.corrupt")
        except OSError as e:
            say(f"[{path.stem}] WARNING: could not back up the unreadable sidecar: {e}", err=True)


def new_sidecar(req: dict, args, previous: list) -> dict:
    return {"shot": req["shot"], "profile": args.profile, "model": args.model, "base_url": args.base_url,
            "state": "submitting", "task_id": None, "created_at": now_iso(), "updated_at": now_iso(),
            "prompt": req["prompt"], "params": req["params"], "media": req["media"],
            "request": {"endpoint": PROFILES[args.profile]["submit"], "body": display_body(req["body"])},
            "estimate": req["estimate"], "previous_tasks": previous}


def submit_job(client: Client, job: Job, args, previous: list) -> bool:
    """One POST, never retried. The sidecar is written before AND right after the POST."""
    backup_corrupt_sidecar(job.sidecar_path)
    job.sc = new_sidecar(job.req, args, previous)
    if not job.save():                             # a crash mid-POST leaves state=submitting (outcome unknown)
        job.outcome, job.detail = "sidecar_unwritable", "cannot write the sidecar, so nothing was submitted (no task id could be kept)"
        return False
    try:
        resp = client.api("POST", PROFILES[args.profile]["submit"], job.req["body"], retries=0, timeout=90)
    except NetError as e:
        job.sc.update(state="submit_unknown", error=str(e))
        job.save()
        job.outcome, job.detail = "submit_unknown", f"network error during submit, outcome UNKNOWN (not retried): {e}"
        return False
    if resp.status in (200, 201, 202):
        try:
            tid = resp.json().get("id")
        except ValueError:
            tid = None
        if tid:
            job.task_id = str(tid)
            say(f"[{job.shot}] submitted, task id {job.task_id}")   # printed BEFORE the write: it survives a disk error
            job.sc.update(task_id=job.task_id, state="submitted", submitted_at=now_iso())
            if job.save():                         # <- the paid task id is on disk before anything else happens
                say(f"[{job.shot}] task id saved to {job.sidecar_path.name}")
            return True
        job.sc.update(state="submit_unknown", error=f"HTTP {resp.status} without task id: {resp.text(300)}")
        job.save()
        job.outcome, job.detail = "submit_unknown", f"HTTP {resp.status} but no task id in response: {resp.text(300)}"
        return False
    state = "submit_failed" if resp.status < 500 else "submit_unknown"
    hint = ""
    if state == "submit_failed" and "execution_expires" in resp.text(2000).lower():
        hint = "  (the gateway rejected execution_expires_after: nothing was billed, retry with --no-expires)"
    job.sc.update(state=state, error=f"HTTP {resp.status}: {resp.text(400)}{hint}")
    job.save()
    job.outcome, job.detail = state, f"HTTP {resp.status}: {resp.text(400)}{hint}"
    return False


def poll_tick(client: Client, job: Job, args) -> dict | None:
    """One status query. Returns the normalized status or None on a tolerated transient error."""
    path = PROFILES[args.profile]["poll"].format(id=urllib.parse.quote(job.task_id, safe=""))
    try:
        resp = client.api("GET", path, retries=args.poll_retries)
    except NetError as e:
        return _tick_error(job, args, str(e))
    if resp.status == 200:
        try:
            raw = resp.json()
        except ValueError:
            return _tick_error(job, args, f"invalid JSON: {resp.text(120)}")
        job.errors = 0
        norm = normalize_status(args.profile, raw)
        norm["raw"] = raw
        return norm
    if resp.status == 404 or resp.status == 429 or resp.status >= 500:
        return _tick_error(job, args, f"HTTP {resp.status} {resp.text(160)}")
    job.outcome, job.detail = "poll_error", f"HTTP {resp.status} while polling: {resp.text(300)}"
    return {"state": "fatal"}


def _tick_error(job: Job, args, why: str):
    job.errors += 1
    say(f"[{job.shot}] poll error #{job.errors}/{args.max_poll_errors}: {why}")
    if job.errors >= args.max_poll_errors:
        job.outcome, job.detail = "poll_error", f"gave up after {job.errors} consecutive poll errors: {why}"
        return {"state": "fatal"}
    return None


def probe_file(path: Path) -> str:
    if not shutil.which("ffprobe"):
        return ""
    try:
        out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_type,width,height,r_frame_rate",
                              "-show_entries", "format=duration", "-of", "json", str(path)],
                             capture_output=True, text=True, timeout=30).stdout
        j = json.loads(out)
        v = next((s for s in j["streams"] if s["codec_type"] == "video"), {})
        has_a = any(s["codec_type"] == "audio" for s in j["streams"])
        return (f"{float(j['format']['duration']):.2f}s {v.get('width')}x{v.get('height')} "
                f"{v.get('r_frame_rate')} audio={'yes' if has_a else 'no'}")
    except Exception:
        return ""


def last_frame_ext(url: str) -> str:
    """File extension for the last-frame image: taken from a server-supplied url, so only png/jpg/jpeg/webp are allowed."""
    ext = Path(urllib.parse.urlsplit(url).path).suffix.lower()
    return ext if ext in LAST_FRAME_EXTS else ".png"


def expected_seconds(job: Job, norm: dict) -> float | None:
    """Duration the finished task should have: what the provider reports, else what was requested."""
    for v in ((norm.get("raw") or {}).get("duration"), job.req["params"].get("duration")):
        if isinstance(v, (int, float)) and not isinstance(v, bool) and v > 0:
            return float(v)
    return None


def fetch_video(client: Client, job: Job, args, url: str, expect_s: float | None = None) -> int:
    """urllib with a browser UA -> on 403/404/410 refresh the signed url once -> if still 403, fall back to curl."""
    try:
        return client.download(url, job.mp4, expect_s)
    except DownloadHttpError as e:
        err = e
    if err.status in (403, 404, 410):
        say(f"[{job.shot}] download refused ({err}); refreshing the signed url once")
        path = PROFILES[args.profile]["poll"].format(id=urllib.parse.quote(job.task_id, safe=""))
        try:
            r = client.api("GET", path, retries=args.poll_retries)
            fresh = normalize_status(args.profile, r.json()).get("video_url") if r.status == 200 else None
        except (NetError, ValueError):
            fresh = None
        if fresh:
            url = fresh
            try:
                return client.download(url, job.mp4, expect_s)
            except DownloadHttpError as e2:
                err = e2
        if err.status == 403 and shutil.which("curl"):
            say(f"[{job.shot}] urllib is still refused by the CDN; trying curl")
            return client.download_curl(url, job.mp4, expect_s)
    raise err


def finish_download(client: Client, job: Job, args, norm: dict) -> None:
    say(f"[{job.shot}] downloading {safe_url(norm['video_url'])}")
    try:
        nbytes = fetch_video(client, job, args, norm["video_url"], expected_seconds(job, norm))
    except (DownloadHttpError, NetError) as e:
        job.outcome, job.detail = "download_failed", f"{e} (the task is still queryable: --resume-task {job.task_id} --shot {job.shot})"
        job.sc.update(state="download_failed", error=job.detail)
        job.save()
        return
    info = probe_file(job.mp4)
    job.sc.update(state="downloaded", downloaded={"path": job.mp4.name, "bytes": nbytes, "at": now_iso(), "probe": info})
    lf = norm.get("last_frame_url")
    if args.return_last_frame and lf:
        ext = last_frame_ext(lf)
        try:
            client.download_any(lf, job.mp4.with_name(f"{job.shot}.last{ext}"))
            job.sc["downloaded"]["last_frame"] = f"{job.shot}.last{ext}"
        except Exception as e:  # best effort only
            say(f"[{job.shot}] last-frame download failed (ignored): {e}")
    job.save()
    job.outcome = "downloaded"
    usage = job.sc.get("result", {}).get("usage") or {}
    say(f"[{job.shot}] saved {job.mp4} ({nbytes / 1e6:.2f} MB) {info}"
        + (f" | usage {usage.get('total_tokens')} tokens" if usage.get("total_tokens") else ""))


def handle_poll_result(client: Client, job: Job, args, norm: dict) -> bool:
    """Update the sidecar from a status poll. Returns True when the job is finished (successfully or not)."""
    if norm["state"] == "fatal":
        job.sc.update(state=job.outcome, error=job.detail)
        job.save()
        return True
    status = norm["status"]
    if status != job.last_status:
        job.last_status = status
        job.sc.update(state=status or "unknown")
        job.save()
        say(f"[{job.shot}] {job.task_id}: {status or '(no status)'} ({time.monotonic() - job.t0:.0f}s)")
    elif time.monotonic() - job.last_beat > 30:
        say(f"[{job.shot}] still {status} ({time.monotonic() - job.t0:.0f}s)")
    if time.monotonic() - job.last_beat > 30:
        job.last_beat = time.monotonic()
    if norm["state"] == "pending":
        return False
    raw = norm["raw"]
    job.sc["result"] = {"status": status, "usage": raw.get("usage"), "duration": raw.get("duration"),
                        "framespersecond": raw.get("framespersecond"), "resolution": raw.get("resolution"),
                        "ratio": raw.get("ratio"), "generate_audio": raw.get("generate_audio"),
                        "video_url": safe_url(norm["video_url"]) if norm["video_url"] else None,
                        "error": norm["error"]}
    if norm["state"] == "no_video_url":
        job.outcome, job.detail = "no_video_url", fmt_error(norm["error"])
        job.sc.update(state="no_video_url", error=norm["error"])
        job.save()
        say(f"[{job.shot}] task {job.task_id} ended '{status}' but returned no video url; it stays resumable "
            f"(re-run, or --resume-task {job.task_id} --shot {job.shot})", err=True)
        return True
    if norm["state"] == "failed":
        job.outcome, job.detail = status if status in FAIL_STATES else "failed", fmt_error(norm["error"])
        job.sc.update(state=job.outcome, error=norm["error"])
        job.save()
        say(f"[{job.shot}] task {job.task_id} ended '{status}': {job.detail}")
        return True
    job.save()
    finish_download(client, job, args, norm)
    return True


# ----------------------------------------------------------------------------- planning / printing
def fmt_est(est: dict) -> str:
    return (f"{est['tokens']:,} tokens ~ CNY {est['cny']:.2f} ~ USD {est['usd']:.2f}"
            f"  [{est['resolution']} {est['ratio']} {est['duration']}s]")


def check_budget(n_clips: int, total_cny: float, args) -> list:
    problems = []
    if n_clips > args.budget_max_clips:
        problems.append(f"{n_clips} clips to submit > --budget-max-clips {args.budget_max_clips}")
    if not (total_cny <= args.budget_max_cny + 1e-9):   # also blocks when either side is NaN
        problems.append(f"estimated CNY {total_cny:.2f} > --budget-max-cny {args.budget_max_cny:g}")
    return problems


def decide_action(shot_id: str, clips_dir: Path, args) -> tuple[str, str, dict | None]:
    """-> (action, why, sidecar). action: skip | submit | resume | refuse"""
    mp4 = clips_dir / f"{shot_id}.mp4"
    bad = None
    try:
        sc = load_sidecar(clips_dir / f"{shot_id}.json")
    except SidecarError as e:
        sc, bad = None, e
    if mp4.exists() and mp4.stat().st_size > 0 and not args.force:
        return "skip", f"{mp4.name} already exists (use --force to regenerate)", sc
    if bad is not None:
        if args.force:
            return ("submit", f"forced new submit; the unreadable {bad.path.name} is kept as {bad.path.name}.corrupt"
                    + (f" (task id found inside: {bad.salvaged})" if bad.salvaged else ""),
                    {"task_id": bad.salvaged} if bad.salvaged else None)
        return "refuse", (f"{bad}; a paid task may exist at the provider and resubmitting could double-bill. "
                          f"Repair or delete {bad.path.name}"
                          + (f" (it seems to contain task id {bad.salvaged}: --resume-task {bad.salvaged} --shot {shot_id})"
                             if bad.salvaged else f", then re-run; or use --force to submit anyway")), None
    if args.force or not sc:
        return "submit", "forced new submit" if args.force and sc else "no previous task", sc
    state = sc.get("state")
    if state in UNKNOWN_SUBMIT_STATES:
        return "refuse", (f"previous submit outcome is UNKNOWN (state={state}); a task may exist at the provider and "
                          f"resubmitting could double-bill. Check it, then use --resume-task <id> --shot {shot_id}, "
                          f"or --force to submit anyway"), sc
    if sc.get("task_id") and state not in RETRYABLE_SUBMIT_STATES:
        return "resume", f"found task {sc['task_id']} in sidecar (state={state}); resuming instead of resubmitting", sc
    return "submit", f"previous attempt ended '{state}'", sc


def print_request_plan(req: dict, args, action: str, why: str) -> None:
    say(f"=== {req['shot']}: {action.upper()} ({why})")
    if action == "submit":
        pf = PROFILES[args.profile]
        say(f"POST {args.base_url}{pf['submit']}")
        say("Authorization: Bearer <REDACTED>   Content-Type: application/json")
        say(json.dumps(display_body(req["body"]), indent=2, ensure_ascii=False))
        say(f"estimate: {fmt_est(req['estimate'])}")


def load_shotlist(path: Path):
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise UsageError(f"cannot read shotlist {path}: {e}")
    shots = data.get("shots", []) if isinstance(data, dict) else None
    if not isinstance(shots, list):
        raise UsageError(f"{path} has no 'shots' list")
    seen = set()
    for i, s in enumerate(shots):
        sid = s.get("id") if isinstance(s, dict) else None
        if not isinstance(sid, str) or not ID_RE.fullmatch(sid):
            raise UsageError(f"shot #{i + 1}: invalid id {sid!r} (allowed: letters, digits, '_' and '-'; ids become file names)")
        if sid in seen:
            raise UsageError(f"duplicate shot id {sid!r} in {path}")
        seen.add(sid)
        if not isinstance(s.get("seedance_prompt"), str) or not s["seedance_prompt"].strip():
            raise UsageError(f"shot {sid}: 'seedance_prompt' must be a non-empty string")
    return shots, (data.get("look") or {}).get("negative", "")


def select_shots(shots: list, wanted: list | None) -> list:
    if not wanted:
        return shots
    ids = [w.strip().upper() for item in wanted for w in item.split(",") if w.strip()]
    by_id = {s["id"].upper(): s for s in shots}
    unknown = [i for i in ids if i not in by_id]
    if unknown:
        raise UsageError(f"unknown shot id(s) {unknown}; shotlist has {[s['id'] for s in shots]}")
    seen, out = set(), []
    for i in ids:
        if i not in seen:
            seen.add(i)
            out.append(by_id[i])
    return out


# ----------------------------------------------------------------------------- commands
def cmd_probe(client: Client, args) -> int:
    try:
        resp = client.api("GET", "/v1/models", retries=args.max_retries)
    except NetError as e:
        say(f"probe failed: {e}", err=True)
        return EXIT_FAIL
    if resp.status != 200:
        say(f"probe failed: HTTP {resp.status} {resp.text(300)}", err=True)
        return EXIT_FAIL
    try:
        ids = sorted({m.get("id", "") for m in resp.json().get("data", [])})
    except (ValueError, AttributeError):
        say("probe failed: unexpected response (not a model list)", err=True)
        return EXIT_FAIL
    hits = [i for i in ids if "seedance" in i.lower() or "seedream" in i.lower()]
    say(f"{len(ids)} models on {args.base_url}; {len(hits)} match 'seedance'/'seedream':")
    for i in hits:
        say("  " + i + ("   <- default model" if i == DEFAULT_MODEL else ""))
    if args.model not in ids:
        say(f"WARNING: requested model {args.model!r} is not in the model list")
    return EXIT_OK


def cmd_generate(client: Client, args, shots: list, negative: str, project_dir: Path, clips_dir: Path) -> int:
    reqs = {s["id"]: build_shot_request(s, args, negative, project_dir) for s in shots}
    plan = []
    for s in shots:
        action, why, sc = decide_action(s["id"], clips_dir, args)
        plan.append((s["id"], action, why, sc))
    to_submit = [sid for sid, a, _, _ in plan if a == "submit"]
    total_cny = sum(reqs[sid]["estimate"]["cny"] for sid in to_submit)
    total_tok = sum(reqs[sid]["estimate"]["tokens"] for sid in to_submit)
    problems = check_budget(len(to_submit), total_cny, args)

    if args.dry_run:
        for sid, action, why, _ in plan:
            print_request_plan(reqs[sid], args, action, why)
        say("")
    else:
        for sid, action, why, _ in plan:
            say(f"[{sid}] {action}: {why}")
    res_used = sorted({reqs[sid]["estimate"]["resolution"] for sid in to_submit} or {args.resolution})
    price_note = ", ".join(f"{r} CNY {PRICE_CNY_PER_MTOK[r]:g}/M tokens" for r in res_used)
    say(f"estimate (new submits only): {len(to_submit)} clip(s), {total_tok:,} tokens ~ CNY {total_cny:.2f} "
        f"~ USD {total_cny / CNY_PER_USD:.2f}  [formula: duration x W x H x 24 / 1024 tokens, "
        f"{price_note}, CNY 7 = USD 1; resolution/ratio/duration are read from the final request body; "
        f"only successful clips are billed]")
    say(f"budget: max {args.budget_max_clips} clips / CNY {args.budget_max_cny:g} -> "
        + ("OK" if not problems else "BLOCKED: " + "; ".join(problems)))
    refused = [sid for sid, a, _, _ in plan if a == "refuse"]
    if args.dry_run:
        say("DRY RUN: nothing was sent." + ("  A real run would be BLOCKED by the budget caps." if problems else ""))
        return EXIT_OK
    if problems:
        say("Refusing to start: raise --budget-max-cny / --budget-max-clips if this spend is intended.", err=True)
        return EXIT_BUDGET
    if not args.yes:
        say("Refusing to submit without --yes (nothing was sent). Re-run with --yes to spend the estimated amount.", err=True)
        return EXIT_USAGE

    jobs = deque()
    results = []
    for sid, action, why, sc in plan:
        if action == "skip":
            results.append((sid, "skipped (exists)", ""))
            continue
        if action == "refuse":
            results.append((sid, "refused", why))
            say(f"[{sid}] REFUSED: {why}", err=True)
            continue
        job = Job(reqs[sid], clips_dir, action)
        if action == "resume":
            job.sc, job.task_id = sc, sc["task_id"]
            job.sc["state"] = sc.get("state", "submitted")
        jobs.append(job)

    active: list = []
    done: list = []
    previous_of = {sid: ([sc.get("task_id")] + list(sc.get("previous_tasks", []))) if sc and sc.get("task_id")
                   else list((sc or {}).get("previous_tasks", [])) for sid, _, _, sc in plan}
    while jobs or active:
        while jobs and len(active) < args.max_concurrent:
            job = jobs.popleft()
            job.t0 = job.last_beat = time.monotonic()
            if job.action == "submit":
                if not submit_job(client, job, args, [p for p in previous_of[job.shot] if p]):
                    say(f"[{job.shot}] SUBMIT FAILED: {job.detail}", err=True)
                    done.append(job)
                    continue
            else:
                say(f"[{job.shot}] resuming task {job.task_id}")
            active.append(job)
        for job in list(active):
            if time.monotonic() - job.t0 > args.timeout_min * 60:
                job.outcome = "timeout"
                job.detail = (f"no terminal state after {args.timeout_min:g} min; the task may still finish. "
                              f"Resume: generate_clips.py --resume-task {job.task_id} --shot {job.shot}")
                job.sc.update(state="timeout", error=job.detail)
                job.save()
                say(f"[{job.shot}] TIMEOUT: {job.detail}", err=True)
                active.remove(job)
                done.append(job)
                continue
            norm = poll_tick(client, job, args)
            if norm is not None and handle_poll_result(client, job, args, norm):
                active.remove(job)
                done.append(job)
        if active:
            time.sleep(args.poll_interval)
    return summarize(results, done)


def summarize(results: list, done: list) -> int:
    for job in done:
        results.append((job.shot, job.outcome, job.detail if job.outcome != "downloaded" else job.mp4.name))
    results.sort()
    say("\nshot  result              detail")
    spent, spent_cny = 0, 0.0
    bad = 0
    for sid, outcome, detail in results:
        say(f"{sid:<5} {outcome:<19} {detail}"[:200])
        if outcome not in ("downloaded", "skipped (exists)"):
            bad += 1
    for job in done:
        tok = (job.sc.get("result", {}).get("usage") or {}).get("total_tokens")
        if job.outcome == "downloaded" and tok:
            spent += tok
            spent_cny += tok * PRICE_CNY_PER_MTOK[job.req["params"]["resolution"]] / 1e6
    if spent:
        say(f"billed this run (provider usage): {spent:,} tokens ~ CNY {spent_cny:.2f} ~ USD {spent_cny / CNY_PER_USD:.2f}")
    return EXIT_FAIL if bad else EXIT_OK


def cmd_resume(client: Client, args, shots: list, negative: str, project_dir: Path, clips_dir: Path) -> int:
    if not args.shot:
        raise UsageError("--resume-task needs --shot <ID> (the clip it belongs to)")
    shot = select_shots(shots, [args.shot])[0]
    req = build_shot_request(shot, args, negative, project_dir)
    mp4 = clips_dir / f"{shot['id']}.mp4"
    if mp4.exists() and mp4.stat().st_size > 0 and not args.force:
        raise UsageError(f"{mp4} already exists; use --force to overwrite it")
    job = Job(req, clips_dir, "resume")
    job.task_id = args.resume_task
    try:
        old = load_sidecar(job.sidecar_path) or {}
    except SidecarError as e:
        say(f"[{job.shot}] note: {e}; continuing with the task id you gave ({job.task_id})")
        backup_corrupt_sidecar(job.sidecar_path)
        old = {"previous_tasks": [e.salvaged] if e.salvaged and e.salvaged != job.task_id else []}
    prev = list(old.get("previous_tasks", []))
    if old.get("task_id") and old["task_id"] != job.task_id:
        prev.insert(0, old["task_id"])
    job.sc = old if old.get("task_id") == job.task_id else new_sidecar(req, args, prev)
    job.sc.update(task_id=job.task_id, state="resuming", resumed_at=now_iso())
    job.save()
    say(f"[{job.shot}] resuming task {job.task_id} (no new submit, nothing billed beyond the original task)")
    t0 = time.monotonic()
    while True:
        norm = poll_tick(client, job, args)
        if norm is not None and handle_poll_result(client, job, args, norm):
            break
        if time.monotonic() - t0 > args.timeout_min * 60:
            job.outcome, job.detail = "timeout", f"no terminal state after {args.timeout_min:g} min"
            job.sc.update(state="timeout", error=job.detail)
            job.save()
            break
        time.sleep(args.poll_interval)
    if job.outcome != "downloaded":
        say(f"[{job.shot}] {job.outcome}: {job.detail}", err=True)
    return EXIT_OK if job.outcome == "downloaded" else EXIT_FAIL


# ----------------------------------------------------------------------------- CLI
def build_parser() -> argparse.ArgumentParser:
    here = Path(__file__).resolve().parent
    p = argparse.ArgumentParser(
        prog="generate_clips.py", formatter_class=argparse.RawDescriptionHelpFormatter,
        description="Generate one Seedance 2.5 clip per shot through the Ephone gateway (stdlib only).\n"
                    "API key: environment variable EPHONE_API_KEY only (never a CLI argument, never printed or stored).",
        epilog=("examples:\n"
                "  python generate_clips.py --probe\n"
                "  python generate_clips.py --dry-run --shots S05\n"
                "  python generate_clips.py --shots S05 --yes\n"
                "  python generate_clips.py --yes --budget-max-cny 80 --budget-max-clips 12 --max-concurrent 6\n"
                "  python generate_clips.py --resume-task cgt-2026... --shot S05\n\n"
                "notes:\n"
                "  * the model minimum is 4 s: every shot is generated at --duration 4; assemble_clips.py picks the window\n"
                "    (optional per-shot 'use_from' in shotlist.json, seconds into the clip).\n"
                "  * per-shot overrides in shotlist.json: \"seedance\": {\"reference_images\": [...], \"first_frame\": ..., \"last_frame\": ...}\n"
                "  * the ephone-task profile's 'input' layout is Ark-shaped and unverified live; adjust with --extra-json.\n"
                "  * the cost estimate and the budget check use the resolution/ratio/duration of the FINAL request body, so an\n"
                "    --extra-json override is priced too; execution_expires_after is sent unless --no-expires.\n"
                "  * exit codes: 0 ok, 1 some shot failed/timed out, 2 usage error or --yes missing, 3 budget cap hit."))
    m = p.add_argument_group("mode (default: generate; requires --yes)")
    m.add_argument("--probe", action="store_true", help="GET /v1/models and list seedance/seedream ids (free)")
    m.add_argument("--show-provider", action="store_true",
                   help="print the effective provider settings (base URL, model, endpoints, prices) as JSON and exit; "
                        "there is no provider.json, these are constants at the top of this script")
    m.add_argument("--dry-run", action="store_true", help="print exact request bodies (key redacted) + cost estimate; send nothing")
    m.add_argument("--resume-task", metavar="TASK_ID", help="poll+download an already submitted task (needs --shot); no new submit")
    m.add_argument("--yes", action="store_true", help="REQUIRED to actually submit (and spend) anything")
    s = p.add_argument_group("selection")
    s.add_argument("--shots", nargs="+", metavar="ID", help="shot ids (space or comma separated); default: all")
    s.add_argument("--shot", metavar="ID", help="single shot id (required with --resume-task; alias of --shots otherwise)")
    s.add_argument("--force", action="store_true", help="resubmit even if the mp4/sidecar exists (old task id kept in previous_tasks)")
    g = p.add_argument_group("generation parameters")
    g.add_argument("--profile", choices=list(PROFILES), default="ephone-ark", help="API flavour (default ephone-ark)")
    g.add_argument("--model", default=DEFAULT_MODEL, help=f"default {DEFAULT_MODEL}")
    g.add_argument("--resolution", choices=list(DIMS), default="720p")
    g.add_argument("--ratio", choices=["16:9", "9:16", "1:1", "4:3", "3:4", "21:9", "adaptive"], default="16:9")
    g.add_argument("--duration", type=parse_duration, default=4, help="seconds, 4..30 (default 4; below 4 is rejected)")
    g.add_argument("--audio", action=argparse.BooleanOptionalAction, default=True, help="generate_audio (default on)")
    g.add_argument("--reference-image", action="append", metavar="PATH_OR_URL",
                   help="repeatable, role reference_image (local files are sent as base64 data URLs; max 9)")
    g.add_argument("--first-frame", metavar="PATH_OR_URL", help="image-to-video first frame (cannot be mixed with --reference-image)")
    g.add_argument("--last-frame", metavar="PATH_OR_URL", help="last frame (needs --first-frame)")
    g.add_argument("--return-last-frame", action="store_true", help="ask for and download the last frame as <shot>.last.<ext>")
    g.add_argument("--extra-json", type=json.loads, metavar="JSON",
                   help="object deep-merged into the request body (ark) or 'input' (task); resolution/ratio/duration set "
                        "here are validated and used for the cost estimate and the budget check")
    g.add_argument("--no-expires", action="store_true",
                   help="do not send execution_expires_after (ark profile; use it if the gateway rejects that field)")
    b = p.add_argument_group("budget")
    b.add_argument("--budget-max-cny", type=float, default=40.0, help="abort before submitting if the estimate exceeds this (default 40)")
    b.add_argument("--budget-max-clips", type=int, default=3, help="abort before submitting if more clips would be submitted (default 3)")
    r = p.add_argument_group("run control")
    r.add_argument("--max-concurrent", type=int, default=4, help="tasks in flight at once (default 4)")
    r.add_argument("--poll-interval", type=float, default=6.0, help="seconds between polls (default 6)")
    r.add_argument("--timeout-min", type=float, default=20.0, help="hard timeout per task in minutes (default 20)")
    r.add_argument("--max-retries", type=int, default=4, help="retries for GET/download on 429/5xx/network errors (default 4)")
    r.add_argument("--poll-retries", type=int, default=2, help="retries inside one poll tick (default 2)")
    r.add_argument("--max-poll-errors", type=int, default=20, help="consecutive tolerated poll errors before giving up on a task")
    r.add_argument("--retry-base-delay", type=float, default=2.0, help="backoff base seconds (default 2)")
    f = p.add_argument_group("paths")
    f.add_argument("--base-url", help=f"default env EPHONE_BASE_URL or {DEFAULT_BASE_URL}")
    f.add_argument("--project-dir", type=Path, default=here.parent, help="default: parent of this script's directory")
    f.add_argument("--shotlist", type=Path, help="default <project-dir>/shotlist.json")
    f.add_argument("--clips-dir", type=Path, help="default <project-dir>/out/clips")
    p.add_argument("--debug", action="store_true", help="print a redacted traceback on unexpected errors")
    return p


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    key = os.environ.get("EPHONE_API_KEY", "").strip().strip("'\"")
    register_secret(key)
    try:
        modes = [bool(args.probe), bool(args.dry_run), bool(args.resume_task), bool(args.show_provider)]
        if sum(modes) > 1:
            raise UsageError("--probe, --dry-run, --resume-task and --show-provider are mutually exclusive")
        args.base_url = (args.base_url or os.environ.get("EPHONE_BASE_URL") or DEFAULT_BASE_URL).rstrip("/")
        pu = urllib.parse.urlsplit(args.base_url)
        if pu.scheme not in ("http", "https") or not pu.hostname:
            raise UsageError(f"invalid base URL {args.base_url!r}")
        if pu.scheme == "http" and not is_loopback_url(args.base_url):
            raise UsageError("refusing plain http for a non-local host (the API key would travel unencrypted)")
        if args.max_concurrent < 1 or args.budget_max_clips < 0:
            raise UsageError("--max-concurrent must be >= 1 and --budget-max-clips >= 0")
        if not math.isfinite(args.budget_max_cny) or args.budget_max_cny < 0:
            raise UsageError(f"--budget-max-cny must be a finite number >= 0 (got {args.budget_max_cny!r}); "
                             f"a NaN/inf cap would silently disable the spending limit, use a large number instead")
        for name in ("timeout_min", "poll_interval", "retry_base_delay"):
            v = getattr(args, name)
            if not math.isfinite(v) or v < 0 or (name == "timeout_min" and v == 0):
                raise UsageError(f"--{name.replace('_', '-')} must be a finite number " + ("> 0" if name == "timeout_min" else ">= 0"))
        if args.max_retries < 0 or args.poll_retries < 0 or args.max_poll_errors < 1:
            raise UsageError("--max-retries/--poll-retries must be >= 0 and --max-poll-errors >= 1")
        if args.extra_json is not None and not isinstance(args.extra_json, dict):
            raise UsageError("--extra-json must be a JSON object")
        if args.shot and not args.resume_task:
            args.shots = (args.shots or []) + [args.shot]
        project_dir = args.project_dir.resolve()
        shotlist = (args.shotlist or project_dir / "shotlist.json")
        clips_dir = (args.clips_dir or project_dir / "out" / "clips")
        client = Client(args.base_url, key or None, args.max_retries, args.retry_base_delay)

        if args.show_provider:
            print(json.dumps(provider_info(args), indent=2))
            return EXIT_OK

        if args.probe:
            return cmd_probe(client, args)
        shots, negative = load_shotlist(shotlist)
        if args.resume_task:
            if not key:
                raise UsageError("EPHONE_API_KEY is not set")
            return cmd_resume(client, args, shots, negative, project_dir, clips_dir)
        shots = select_shots(shots, args.shots)
        if not args.dry_run and not key:
            raise UsageError("EPHONE_API_KEY is not set (not needed for --dry-run)")
        return cmd_generate(client, args, shots, negative, project_dir, clips_dir)
    except UsageError as e:
        say(f"error: {e}", err=True)
        return EXIT_USAGE
    except KeyboardInterrupt:
        say("interrupted; task ids already submitted are saved in out/clips/<shot>.json, resume with --resume-task", err=True)
        return 130
    except Exception as e:  # last resort, always redacted
        say(f"unexpected error: {type(e).__name__}: {e}", err=True)
        if args.debug:
            say(traceback.format_exc(), err=True)
        return EXIT_FAIL


if __name__ == "__main__":
    sys.exit(main())
