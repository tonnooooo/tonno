# seedance/ : Seedance 2.5 clips via the Ephone gateway (stdlib Python, tested on 3.11; needs ffmpeg + ffprobe + curl)
Run from this folder. The key only comes from the environment (never an argument, never printed or stored):
`export EPHONE_API_KEY=...`   (base URL: `EPHONE_BASE_URL` or `--base-url`, default https://api.ephone.ai)
There is no `provider.json`: base URL, model, the two API profiles (`ephone-ark` default, `ephone-task`), prices and the
expiry default are constants at the top of `generate_clips.py`; `python generate_clips.py --show-provider` prints them as JSON.

1. Probe, free: `python generate_clips.py --probe`
2. Dry run, sends nothing: `python generate_clips.py --dry-run --shots S05` (exact body, token/CNY/USD estimate, budget check)
3. One-shot test of S05 (~CNY 6.1 = USD 0.87): `python generate_clips.py --shots S05 --yes`
   writes `out/clips/S05.json` (task id printed, then saved right after the submit) and `out/clips/S05.mp4`
4. Full 12-shot run (~CNY 73 = USD 10.5):
   `python generate_clips.py --yes --budget-max-cny 80 --budget-max-clips 12 --max-concurrent 6`
5. Assemble: `python assemble_clips.py` -> `out/final_ai.mp4` (360 frames, 1280x720, 24 fps, H.264 + AAC 15.0 s);
   `--trim-mode start|center|end`, `--audio keep|drop|silence`, `--allow-missing`, per-shot `"use_from"` (s into the 4 s clip).
   Then compose the ad, from the project dir: `python compose/compose_ad.py --top out/previs.mp4 --bottom out/final_ai.mp4 --out out/ad.mp4`
   (the assembler writes `out/final_ai.mp4`, not `seedance/final.mp4`).
6. Interrupted or timed out? `python generate_clips.py --resume-task <task id> --shot S05` (re-running step 3 or 4 also
   resumes tasks found in the sidecars instead of resubmitting; `--force` is the only way to pay for a new one)

Cost: billed per token, ~ duration x W x H x 24 / 1024 tokens x CNY 70 per million (77 at 1080p); a 4 s 720p 16:9 clip is
~87,300 tokens = CNY 6.1. Only successful clips are billed. Caps default to 3 clips / CNY 40 and `--yes` is always required.
The estimate and the budget check read resolution, ratio and duration from the FINAL request body, so an `--extra-json`
override (e.g. `{"resolution":"1080p"}`) is priced too; unknown values are refused. `--budget-max-cny` must be finite (NaN/inf are rejected).
4-second minimum: the model rejects `duration` < 4 (the CLI refuses it too) but shots last 1.0-1.8 s, so every clip is
generated at 4 s and `assemble_clips.py` cuts the window it needs (centre by default).
Request body: `execution_expires_after: 172800` is sent on the ark profile; if the gateway rejects it (HTTP 400, nothing billed)
the error says so, re-run with `--no-expires`.
User-Agent: the video CDN (storage.fonedis.cc) answers 403 to the default `Python-urllib` agent; downloads use a
browser-like agent, never send the API key, refresh the signed URL (valid 24 h) once and fall back to curl.
Every download is checked before it is kept (mp4 header, full decode without errors, >= 95 % of the task duration); a
truncated or corrupt body is retried, then reported as `download_failed` with the task id kept (re-run to resume it).
A POST submit is never auto-retried (a retry would double-bill); GETs and downloads retry on 429/5xx with backoff.
Safety on re-runs: a sidecar that cannot be parsed makes the shot REFUSED (it may hold a paid task id; the id is salvaged
and shown; `--force` keeps the old file as `<shot>.json.corrupt`); a task that succeeded but returned no video url is state
`no_video_url` and is resumed, never resubmitted; the task id is printed before it is written to disk.
Shot ids in `shotlist.json` become file names and must match `^[A-Za-z0-9_-]+$` and be unique (both scripts check it).
Assembler warnings (stderr): a clip shorter than its shot holds its last frame (frame-exact, audio goes silent) and a clip
that is not 16:9 is centre-cropped (`cropped (aspect X -> 16:9)` in the table).
Tests: `python test_adapter.py` (starts `mock_server.py`, no network, ~2 min, 33 tests). Work dir: `--workdir DIR` or env
`SEEDANCE_TEST_WORKDIR`, else a fresh `tempfile.mkdtemp()` (honours `TMPDIR`); the mock removes its scratch dir on exit.
`ephone-task` profile is `--profile ephone-task`.
