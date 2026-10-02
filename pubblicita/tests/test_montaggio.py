"""Test del montaggio: matematica dei battiti, validazione EDL, render con clip sintetiche."""
import json
import shutil
import subprocess
from fractions import Fraction
from pathlib import Path

import pytest

from pubblicita.montaggio import EDLError, load, resolve
from pubblicita.montaggio.ritmo import (beats_table, boundaries, frames_per_beat, parse_pattern,
                                        round_half_up)

ROOT = Path(__file__).resolve().parents[1]
needs_ffmpeg = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg non disponibile")


# ---------------------------------------------------------------- battiti

def test_frames_per_beat_115():
    assert frames_per_beat(115, 24) == Fraction(60 * 24, 115)
    assert float(frames_per_beat(115)) == pytest.approx(12.5217, abs=1e-4)


def test_boundaries_no_drift():
    # 115 battiti a 115 bpm = 60 s esatti = 1440 frame: nessun accumulo di errore
    cuts = boundaries([("beats", 1)] * 115, 115, 24)
    assert cuts[-1].end_frame == 1440
    for k, c in enumerate(cuts, start=1):
        assert c.end_frame == round_half_up(Fraction(k * 1440, 115))
    assert {c.frames for c in cuts} == {12, 13}


def test_boundaries_mixed_frames_beats():
    cuts = boundaries([("beats", 0.5), ("frames", 7), ("beats", 0.5)], 115, 24)
    # 0.5 battiti = 6.26 → 6 ; +7 → 13.26 → 13 ; +6.26 → 19.52 → 20
    assert [c.end_frame for c in cuts] == [6, 13, 20]
    assert cuts[1].frames == 7 and cuts[1].beats is None


def test_round_half_up_and_pattern():
    assert round_half_up(Fraction(5, 2)) == 3
    assert round_half_up(Fraction(-1, 2)) == 0
    assert parse_pattern("1, 1/2,0.25") == [Fraction(1), Fraction(1, 2), Fraction(1, 4)]
    rows = beats_table("1,0.5,0.5", 115)
    assert [r["end_frame"] for r in rows] == [13, 19, 25]
    assert rows[0]["start_s"] == 0 and rows[-1]["end_s"] == pytest.approx(25 / 24, abs=1e-4)


def test_reference_rhythm_file():
    d = json.loads((ROOT / "montaggio" / "ritmo_riferimento.json").read_text(encoding="utf-8"))
    assert len(d["frames"]) == 26
    assert sum(d["frames"]) == 336 == d["total_frames"]
    assert d["duration_s"] == 14.0


# ---------------------------------------------------------------- validazione

def _edl(shots, **kw):
    d = {"fps": 24, "bpm": 115, "size": [64, 36], "shots": shots}
    d.update(kw)
    return d


COLOR = {"color": "#336699"}


def test_validation_messages():
    with pytest.raises(EDLError, match="manca la sorgente 'top'"):
        resolve(_edl([{"id": "s01", "frames": 4, "bottom": COLOR}]))
    with pytest.raises(EDLError, match="esattamente uno tra 'frames' e 'beats'"):
        resolve(_edl([{"id": "s01", "frames": 4, "beats": 1, "top": COLOR, "bottom": COLOR}]))
    with pytest.raises(EDLError, match="solo a 24 fps"):
        resolve(_edl([{"frames": 4, "top": COLOR, "bottom": COLOR}], fps=30))
    with pytest.raises(EDLError, match=r"shot s07 \(bottom\): sorgente mancante: non_esiste\.mp4"):
        resolve(_edl([{"id": "s07", "frames": 4, "top": COLOR, "bottom": {"src": "non_esiste.mp4"}}]))
    with pytest.raises(EDLError, match="'speed' fuori intervallo"):
        resolve(_edl([{"frames": 4, "top": {"color": "red", "speed": 0}, "bottom": COLOR}]))
    with pytest.raises(EDLError, match="id duplicato"):
        resolve(_edl([{"id": "a", "frames": 2, "top": COLOR, "bottom": COLOR},
                      {"id": "a", "frames": 2, "top": COLOR, "bottom": COLOR}]))


def test_example_edl_is_valid_without_media():
    p = ROOT / "montaggio" / "edl.example.json"
    tl = resolve(load(p), base_dir=p.parent, check_media=False)
    assert len(tl.shots) == 26 and tl.total_frames == 336


# ---------------------------------------------------------------- render con clip sintetiche

def _clip(path: Path, seconds: float, fps: int, size="80x48", src="testsrc2"):
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"{src}=s={size}:r={fps}:d={seconds}",
                    "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", str(path)], check=True)
    return path


@pytest.fixture(scope="module")
def clips(tmp_path_factory):
    d = tmp_path_factory.mktemp("clip")
    _clip(d / "a30.mp4", 2.0, 30)            # 30 fps → conformato a 24 (48 frame)
    _clip(d / "b24.mp4", 1.0, 24, "64x64")  # quadrato → ritaglio «cover»
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "sine=f=440:d=0.6",
                    str(d / "tono.wav")], check=True)
    return d


@needs_ffmpeg
def test_overrun_is_reported_with_shot(clips):
    edl = _edl([{"id": "s03", "frames": 20, "top": {"src": "b24.mp4", "in": 10},
                 "bottom": {"src": "b24.mp4"}}])
    with pytest.raises(EDLError, match=r"shot s03 \(top\): in=10 \+ 20 frame .*oltre la fine della sorgente \(24 frame"):
        resolve(edl, base_dir=clips)
    edl = _edl([{"id": "s04", "frames": 13, "top": {"src": "b24.mp4", "speed": 2.0},
                 "bottom": {"src": "b24.mp4"}}])
    with pytest.raises(EDLError, match="s04"):
        resolve(edl, base_dir=clips)


@needs_ffmpeg
def test_render_tracks(clips, tmp_path):
    from pubblicita.montaggio.media import count_frames, duration, probe
    from pubblicita.montaggio.render import render

    edl = _edl([
        {"id": "s01", "frames": 5, "top": {"src": "a30.mp4", "in": 0}, "bottom": {"src": "b24.mp4", "in": 3}},
        {"id": "s02", "beats": 0.5, "top": {"src": "a30.mp4", "in": 10, "speed": 2.0},
         "bottom": {"color": "#202428"}},
        {"id": "s03", "frames": 4, "top": {"src": "b24.mp4", "speed": 0.5}, "bottom": {"src": "a30.mp4", "in": 40}},
    ], audio={"src": "tono.wav", "offset_s": 0.1})
    (clips / "edl.json").write_text(json.dumps(edl))
    tl = resolve(load(clips / "edl.json"), base_dir=clips)
    assert [s.frames for s in tl.shots] == [5, 6, 4]
    res = render(tl, tmp_path, preset="ultrafast")
    for track in ("top", "bottom"):
        info = probe(res[track])
        assert (info.width, info.height) == (64, 36)
        assert info.fps == pytest.approx(24.0)
        assert count_frames(res[track]) == 15
    tj = json.loads((tmp_path / "timeline.json").read_text())
    assert tj["total_frames"] == 15 and tj["cuts_frames"] == [5, 11]
    assert tj["shots"][1]["top"]["speed"] == 2.0
    # audio: 0.6 s di tono dal secondo 0.1 → 0.5 s, allungato con silenzio a 15/24 s
    assert duration(res["audio"]) == pytest.approx(15 / 24, abs=0.01)


@needs_ffmpeg
def test_analyze_detects_hard_cuts(tmp_path):
    from pubblicita.montaggio.analisi import detect_cuts

    out = tmp_path / "tagli.mp4"
    graph = ("color=c=red:s=64x36:r=24:d=0.5[a];color=c=blue:s=64x36:r=24:d=0.25[b];"
             "color=c=white:s=64x36:r=24:d=0.5[c];[a][b][c]concat=n=3:v=1:a=0[v]")
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-filter_complex", graph, "-map", "[v]",
                    "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", str(out)], check=True)
    res = detect_cuts(str(out))
    assert [c["frame"] for c in res["cuts"]] == [12, 18]
    assert res["durations_frames"] == [12, 6, 12]
