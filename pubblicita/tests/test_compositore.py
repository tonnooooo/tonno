"""Test del compositore: layout, animazioni, onde, output 1080x1920 a 24 fps con audio."""
import json
import shutil
import subprocess
from pathlib import Path

import numpy as np
import pytest

from pubblicita.compositore import Compositor, compose, load_layout
from pubblicita.compositore import grafica
from pubblicita.compositore.header import cubic_bezier, ease, tween_state
from pubblicita.compositore.sfondo import Waves, catmull_rom_basis

needs_ffmpeg = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg non disponibile")


@pytest.fixture(scope="module")
def cfg():
    return load_layout()


# ---------------------------------------------------------------- config

def test_default_layout_geometry(cfg):
    assert cfg["canvas"] == {"width": 1080, "height": 1920, "fps": 24}
    assert cfg["panels"]["top"]["box"] == [12, 336, 1056, 594]
    assert cfg["panels"]["bottom"]["box"] == [12, 1070, 1056, 594]
    assert cfg["header"]["title"]["text"] == "Opus 5.5"
    texts = [it.get("text") for it in cfg["panels"]["bottom"]["label"]["items"]]
    assert "Seedance 2.5" in texts
    assert len(cfg["background"]["waves"]["lines"]) == 15


def test_user_config_is_merged(tmp_path):
    user = {"panels": {"top": {"label": {"items": [{"icon": "dot"}, {"text": "Blockout"}]}}},
            "header": {"title": {"text": "Prova"}}}
    p = tmp_path / "mio.json"
    p.write_text(json.dumps(user))
    c = load_layout(p)
    assert c["panels"]["top"]["label"]["items"][1]["text"] == "Blockout"
    assert c["panels"]["top"]["box"] == [12, 336, 1056, 594]      # il resto resta di default
    assert c["header"]["title"]["font"].endswith("HankenGrotesk-Bold.ttf")


# ---------------------------------------------------------------- animazioni

def test_easing():
    for name in ("linear", "easeOutCubic", "easeOutBack", [0.2, 0.86, 0.49, 0.94]):
        assert ease(name, 0.0) == pytest.approx(0.0, abs=1e-6)
        assert ease(name, 1.0) == pytest.approx(1.0, abs=1e-6)
    ys = [cubic_bezier(0.33, 1, 0.68, 1, x) for x in np.linspace(0, 1, 21)]
    assert all(b >= a - 1e-9 for a, b in zip(ys, ys[1:]))
    assert max(cubic_bezier(0.34, 1.56, 0.64, 1, x) for x in np.linspace(0, 1, 50)) > 1.0  # overshoot


def test_tween_state(cfg):
    anim = cfg["header"]["animation"]
    st0 = tween_state(anim["mark"], 0.0)
    assert st0["opacity"] == pytest.approx(0.0, abs=1e-6)
    assert st0["rotate_deg"] < -10
    st_end = tween_state(anim["mark"], 2.0)
    assert st_end == {"opacity": 1.0, "scale": 1.0, "rotate_deg": 0.0, "dx": 0.0, "dy": 0.0, "blur": 0.0}
    # la seconda parola parte dopo lo stagger
    t = anim["title"]["start_s"] + 0.01
    assert tween_state(anim["title"], t)["opacity"] > 0
    assert tween_state(anim["title"], t, delay=anim["title"]["stagger_s"])["opacity"] == pytest.approx(0, abs=1e-6)


# ---------------------------------------------------------------- grafica e onde

def test_round_rect_mask():
    m = grafica.round_rect_mask(200, 100, 27)
    assert m.shape == (100, 200)
    assert m[0, 0] == pytest.approx(0, abs=1e-6) and m[50, 100] == 1.0 and m[0, 100] == 1.0
    assert m[5, 5] == 0.0 and 0.0 < m[7, 8] < 1.0             # arco dell'angolo (r = 27)


def test_label_width_follows_text(cfg):
    style = cfg["panels"]["label_style"]
    short = grafica.label_layer([{"icon": "cubo"}, {"text": "Blender"}], style)
    long = grafica.label_layer([{"icon": "spark"}, {"text": "Seedance 2.5"}], style)
    assert short.shape[0] == long.shape[0] == style["height"] + 2 * style["margin"]
    assert long.shape[1] > short.shape[1]
    assert short.shape[1] - 2 * style["margin"] == 171   # misura dell'etichetta «Blender» del riferimento
    with pytest.raises(ValueError, match="icona sconosciuta"):
        grafica.icon_layer("non-esiste", 38)


def test_catmull_rom_interpolates_points():
    pts = np.array([0.0, 10.0, -5.0, 3.0, 8.0])
    M = catmull_rom_basis(np.array([0.0, 100.0, 200.0]), 100.0, -100.0, len(pts))
    assert np.allclose(M @ pts, pts[1:4])


def test_waves_deterministic(cfg):
    w = Waves(cfg["background"]["waves"], 1080, 1920)
    a, b = w.curves(3.7), w.curves(3.7)
    assert len(a) == 15 and all(np.array_equal(x, y) for x, y in zip(a, b))
    assert not np.allclose(w.curves(0.0)[0], w.curves(5.0)[0])
    f1 = np.full((1920, 1080, 3), 240, np.uint8)
    f2 = f1.copy()
    w.draw(f1, 1.0)
    w.draw(f2, 1.0)
    assert np.array_equal(f1, f2) and (f1 != 240).any()


def test_frame_layout_pixels(cfg):
    comp = Compositor(cfg)
    content = {"top": np.zeros((594, 1056, 3), np.uint8), "bottom": np.full((594, 1056, 3), 200, np.uint8)}
    last = comp.frame(9, 10, content)
    assert last.shape == (1920, 1080, 3)
    # barra piena all'ultimo frame: colore di riempimento al centro della riga della barra
    assert np.abs(last[927, 540].astype(int) - cfg["panels"]["top"]["progress"]["color"]).max() <= 2
    assert np.abs(last[1661, 540].astype(int) - cfg["panels"]["bottom"]["progress"]["color"]).max() <= 2
    first = comp.frame(0, 10, content)
    assert tuple(first[927, 540]) != tuple(last[927, 540])        # al primo frame la barra è vuota
    assert tuple(first[600, 540]) == (0, 0, 0)                     # contenuto del pannello
    assert first[336, 12].mean() > 150                             # angolo arrotondato: sfondo
    assert last[155, 520].tolist() != first[155, 520].tolist()     # marchio comparso


# ---------------------------------------------------------------- render completo

def _clip(path: Path, seconds: float, size="320x180", audio=False):
    cmd = ["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"testsrc2=s={size}:r=30:d={seconds}"]
    if audio:
        cmd += ["-f", "lavfi", "-i", f"sine=f=330:d={seconds}", "-c:a", "aac", "-shortest"]
    cmd += ["-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", str(path)]
    subprocess.run(cmd, check=True)
    return path


def _streams(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries",
                          "stream=codec_type,codec_name,width,height,r_frame_rate,nb_frames,pix_fmt",
                          "-of", "json", str(path)], capture_output=True, check=True)
    return json.loads(out.stdout)["streams"]


@needs_ffmpeg
def test_compose_video_with_audio(tmp_path, cfg):
    top = _clip(tmp_path / "top.mp4", 0.6)
    bottom = _clip(tmp_path / "bottom.mp4", 0.5, "200x200", audio=True)
    wav = tmp_path / "musica.wav"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "sine=f=220:d=2", str(wav)], check=True)
    out = tmp_path / "spot.mp4"
    res = compose(top, bottom, out, cfg, audio=wav, duration=0.5)
    assert res["frames"] == 12
    st = _streams(out)
    v = next(s for s in st if s["codec_type"] == "video")
    a = [s for s in st if s["codec_type"] == "audio"]
    assert (v["width"], v["height"], v["r_frame_rate"], v["pix_fmt"]) == (1080, 1920, "24/1", "yuv420p")
    assert v["codec_name"] == "h264" and int(v["nb_frames"]) == 12
    assert a and a[0]["codec_name"] == "aac"


@needs_ffmpeg
def test_compose_cli_mute_track_and_still(tmp_path):
    top = _clip(tmp_path / "t.mp4", 0.3)
    bottom = _clip(tmp_path / "b.mp4", 0.3)
    out = tmp_path / "muto.mp4"
    r = subprocess.run(["python3", "-m", "pubblicita.compositore", "--top", str(top), "--bottom", str(bottom),
                        "--out", str(out), "--quiet"], capture_output=True, text=True,
                       cwd=Path(__file__).resolve().parents[2])
    assert r.returncode == 0, r.stderr
    st = _streams(out)
    assert any(s["codec_type"] == "audio" for s in st)              # traccia muta presente
    assert int(next(s for s in st if s["codec_type"] == "video")["nb_frames"]) == 7  # 0.3 s → 7 frame
    png = tmp_path / "anteprima.png"
    r = subprocess.run(["python3", "-m", "pubblicita.compositore", "--top", str(top), "--bottom", str(bottom),
                        "--out", str(png), "--still", "0.2", "--quiet"], capture_output=True, text=True,
                       cwd=Path(__file__).resolve().parents[2])
    assert r.returncode == 0, r.stderr
    from PIL import Image
    assert Image.open(png).size == (1080, 1920)


@needs_ffmpeg
def test_spot_command_end_to_end(tmp_path):
    """EDL → montaggio → impaginazione in un solo comando."""
    _clip(tmp_path / "a.mp4", 0.5)
    _clip(tmp_path / "b.mp4", 0.5, "256x144")
    edl = {"fps": 24, "bpm": 115, "size": [320, 180], "audio": {"src": None},
           "shots": [{"id": "s01", "frames": 4, "top": {"src": "a.mp4"}, "bottom": {"src": "b.mp4"}},
                     {"id": "s02", "beats": 0.5, "top": {"src": "b.mp4", "in": 2}, "bottom": {"src": "a.mp4", "in": 2}}]}
    (tmp_path / "edl.json").write_text(json.dumps(edl))
    out = tmp_path / "spot.mp4"
    r = subprocess.run(["python3", "-m", "pubblicita.compositore", "spot", "--edl", str(tmp_path / "edl.json"),
                        "--out", str(out), "--quiet"], capture_output=True, text=True,
                       cwd=Path(__file__).resolve().parents[2])
    assert r.returncode == 0, r.stderr
    v = next(s for s in _streams(out) if s["codec_type"] == "video")
    assert int(v["nb_frames"]) == 10 and (v["width"], v["height"]) == (1080, 1920)
    assert (tmp_path / "spot_montaggio" / "timeline.json").exists()
