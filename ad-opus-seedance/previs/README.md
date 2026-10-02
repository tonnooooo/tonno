# previs - procedural Blender grey-box of the 12 shots

1. Run (needs the bpy venv + ffmpeg): `PY=<scratchpad>/venv/bin/python; cd ad-opus-seedance; $PY previs/build_previs.py --frames-dir <scratch>/previs_frames` -> `out/previs.mp4` (1280x720, 24 fps, 15.0 s, H.264 yuv420p, no audio, ~3 min).
2. Quick tests: `--scale 25` (320x180, ~25 s), `--shots S04,S05` (subset, writes `<frames-dir>/../previs_partial.mp4` unless `--out`), `--frames-only`, `--list` (frame ranges), `--save-blend x.blend --no-render` (open the built scene in Blender), `--help`.
3. Everything is data-driven from `../shotlist.json`: per shot `previs.cam_from -> cam_to` (linear over the shot, last frame = cam_to), `look_at` (Track-To empty), optional `figure_path`, `car_path`.
4. Shot timing: frame range = `round(start*24) .. round((start+dur)*24)-1` (S01 = 0-28 ... S12 = 317-359); PNGs are `f_<global frame>.png`.
5. Re-fit cameras to real Seedance clips: edit only `cam_from / cam_to / look_at` (metres, relative to the shot's own world origin; +Y = car forward; z up), re-run the one shot, compare with `contact_sheet.py` (`--frames-dir ... --out sheet.png [--shots S02]`).
6. Optional per-shot keys in `previs{}`: `lens_mm`, `lens_to_mm`, `look_at_to`, `speed` (convoy m/s for S07-S09: car+camera+target move along +Y), `handheld` (m), `car_pos`, `car_yaw`, `car_ease`, `figure_action` (walk|flick|poses|lean|stand), `figure_yaw`. Defaults (lenses, car placement, poses) live in `RECIPES` at the top of `build_previs.py`.
7. Each shot is built in its own world (garage/highway/tunnel/booth offset 1000 m in X, repeated envs 1000 m in Y) so shots never see each other; the coupe is rebuilt per shot, wheels roll with the motion.
8. Look: Workbench, STUDIO light, object colour `--grey 0.66` (renders as the ~0.42 mid-grey of a viewport), darker floor, dark-grey world, no outlines, no UI.
9. Car placement is automatic from `look_at` (S06 macro and S08 wheel close-up place the taillight / wheel exactly on `look_at`); override with `car_pos`/`car_yaw` if you re-fit the numbers.
10. `contact_sheet.py` builds first/middle/last rows per shot from the PNG sequence (Pillow only).
