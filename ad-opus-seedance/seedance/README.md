# seedance/ : Seedance 2.5 clips via the Ephone gateway (stdlib Python, tested on 3.11; needs ffmpeg + curl)
Run from this folder. The key only comes from the environment (never an argument, never printed or stored):
`export EPHONE_API_KEY=...`   (base URL: `EPHONE_BASE_URL` or `--base-url`, default https://api.ephone.ai)

1. Probe, free: `python generate_clips.py --probe`
2. Dry run, sends nothing: `python generate_clips.py --dry-run --shots S05` (exact body, token/CNY/USD estimate, budget check)
3. One-shot test of S05 (~CNY 6.1 = USD 0.87): `python generate_clips.py --shots S05 --yes`
   writes `out/clips/S05.json` (task id saved right after the submit) and `out/clips/S05.mp4`
4. Full 12-shot run (~CNY 73 = USD 10.5):
   `python generate_clips.py --yes --budget-max-cny 80 --budget-max-clips 12 --max-concurrent 6`
5. Assemble: `python assemble_clips.py` -> `out/final_ai.mp4` (360 frames, 1280x720, 24 fps, H.264 + AAC 15.0 s);
   `--trim-mode start|center|end`, `--audio keep|drop|silence`, `--allow-missing`, per-shot `"use_from"` (s into the 4 s clip)
6. Interrupted or timed out? `python generate_clips.py --resume-task <task id> --shot S05` (re-running step 3 or 4 also
   resumes tasks found in the sidecars instead of resubmitting; `--force` is the only way to pay for a new one)

Cost: billed per token, ~ duration x W x H x 24 / 1024 tokens x CNY 70 per million (77 at 1080p); a 4 s 720p 16:9 clip is
~87,300 tokens = CNY 6.1. Only successful clips are billed. Caps default to 3 clips / CNY 40 and `--yes` is always required.
4-second minimum: the model rejects `duration` < 4 (the CLI refuses it too) but shots last 1.0-1.8 s, so every clip is
generated at 4 s and `assemble_clips.py` cuts the window it needs (centre by default).
User-Agent: the video CDN (storage.fonedis.cc) answers 403 to the default `Python-urllib` agent; downloads use a
browser-like agent, never send the API key, refresh the signed URL (valid 24 h) once and fall back to curl.
A POST submit is never auto-retried (a retry would double-bill); GETs and downloads retry on 429/5xx with backoff.
Tests: `python test_adapter.py` (starts `mock_server.py`, no network, ~1 min); `ephone-task` profile is `--profile ephone-task`.
