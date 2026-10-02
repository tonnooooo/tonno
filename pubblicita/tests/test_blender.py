"""Test del kit blockout: spec e matematica in puro Python, confronto e smoke render.

Lo smoke render usa Blender solo se presente (160x90, 2 frame, 4 campioni).
"""
from __future__ import annotations

import copy
import json
import math
import shutil
import subprocess
from pathlib import Path

import numpy as np
import pytest

from pubblicita.blender import confronta, moto
from pubblicita.blender import spec as S

CARTELLA = Path(__file__).resolve().parents[1] / "blender"
ESEMPI = sorted((CARTELLA / "esempi").glob("*.json"))
BLENDER = shutil.which("blender") or ("/usr/local/bin/blender" if Path("/usr/local/bin/blender").exists() else None)
FFMPEG = shutil.which("ffmpeg")


def base_spec(**extra) -> dict:
    s = {
        "meta": {"id": "prova", "frames": 24},
        "camera": {"location": [0, -6, 1.5], "look_at": [0, 0, 1]},
        "objects": [
            {"name": "auto", "type": "car", "style": "coupe_80s"},
            {"name": "lei", "type": "mannequin", "pose": "standing", "accessories": ["hair_bun", "obi"]},
            {"name": "cubo", "type": "box", "size": [1, 2, 3], "material": "emissive:#CFF2E3:2"},
        ],
    }
    s.update(extra)
    return s


def errori_di(s: dict) -> str:
    return "\n".join(S.valida(s))


# ---------------------------------------------------------------------------
# Spec
# ---------------------------------------------------------------------------


def test_esempi_validi():
    assert len(ESEMPI) >= 3
    for p in ESEMPI:
        dati = json.loads(p.read_text(encoding="utf-8"))
        assert S.valida(dati) == [], p.name
        n = S.carica(p)
        assert n["meta"]["id"] == p.stem
        assert n["meta"]["fps"] == 24


def test_spec_minima_valida_e_default():
    n = S.normalizza(base_spec())
    assert n["meta"]["resolution"] == [1280, 720]
    assert n["render"]["samples"] == n["meta"]["samples"]
    assert n["render"]["view_transform"] == "Standard"
    assert n["camera"]["lens"] == 35.0
    # le luci del preset di mondo (studio) vengono incluse
    assert len(n["world"]["lights"]) == len(S.MONDI["studio"]["lights"])
    lei = next(o for o in n["objects"] if o["name"] == "lei")
    assert lei["height"] == 1.65 and lei["dress"] == "long"
    assert lei["location"] == [0.0, 0.0, 0.0]


@pytest.mark.parametrize("modifica, atteso", [
    (lambda s: s.pop("meta"), "meta"),
    (lambda s: s["meta"].update(frames=0), "meta.frames"),
    (lambda s: s["meta"].update(fps=30), "24 fps"),
    (lambda s: s["meta"].update(id="con spazi"), "meta.id"),
    (lambda s: s["objects"].append({"type": "astronave"}), "tipo sconosciuto"),
    (lambda s: s["objects"][2].update(material="oro_zecchino"), "materiale sconosciuto"),
    (lambda s: s["objects"][2].update(material="emissive:verde"), "emissive"),
    (lambda s: s["objects"][0].update(color="#zzzzzz"), "colore non valido"),
    (lambda s: s["objects"][0].update(colour="#ffffff"), "campi sconosciuti"),
    (lambda s: s["objects"][0].update(parent="nessuno"), "genitore"),
    (lambda s: s["objects"].append({"name": "auto", "type": "box"}), "duplicato"),
    (lambda s: s["objects"][0].update(style="carrozza"), "stili ammessi"),
    (lambda s: s["objects"][1].update(pose="moonwalk"), "posa sconosciuta"),
    (lambda s: s["objects"][1].update(accessories=["mantello"]), "accessori"),
    (lambda s: s["objects"][1].update(joints={"coda": [0, 0, 0]}), "giunto sconosciuto"),
    (lambda s: s["objects"][2].update(keys=[{"location": [0, 0, 0]}]), "manca il tempo"),
    (lambda s: s["objects"][2].update(keys=[{"f": 1, "t": 1}]), "non entrambi"),
    (lambda s: s["objects"][2].update(keys=[{"f": 1, "ease": "elastico"}]), "easing sconosciuto"),
    (lambda s: s["objects"][0].update(path={"points": [[0, 0, 0]]}), "almeno 2 punti"),
    (lambda s: s["camera"].update(moves=[{"type": "tracking"}]), "target"),
    (lambda s: s["camera"].update(moves=[{"type": "tracking", "target": "ufo"}]), "inesistente"),
    (lambda s: s["camera"].update(moves=[{"type": "volo"}]), "movimento sconosciuto"),
    (lambda s: s["camera"].update(look_at="ufo"), "inesistente"),
    (lambda s: s.update(world={"preset": "marte"}), "preset sconosciuto"),
    (lambda s: s.update(render={"engine": "eevee"}), "cycles"),
    (lambda s: s.update(extra=1), "sezioni sconosciute"),
    (lambda s: s["objects"][1].update(height="alta"), "atteso un numero"),
    (lambda s: s["objects"][0].update(popup_headlights="si"), "true/false"),
    (lambda s: s["objects"].append({"type": "room", "size": [4, 4]}), "3 numeri"),
    (lambda s: s["objects"].append({"type": "light", "visible": True}), "visible"),
])
def test_errori_di_validazione(modifica, atteso):
    s = base_spec()
    modifica(s)
    err = errori_di(s)
    assert atteso in err, err


def test_normalizza_tempi_in_frame_e_preset():
    s = base_spec()
    s["objects"][2]["keys"] = [{"t": 0.5, "location": [1, 0, 0]}, {"f": 20, "location": [2, 0, 0]}]
    s["objects"][0]["path"] = {"points": [[0, 5, 0], [0, 0, 0]], "start_t": 0.25}
    s["camera"]["preset"] = {"type": "dolly_in", "distance": 1, "end_t": 0.5}
    s["world"] = {"preset": "night_city", "replace_lights": True, "lights": [{"light_type": "point"}]}
    assert S.valida(s) == []
    n = S.normalizza(s)
    cubo = next(o for o in n["objects"] if o["name"] == "cubo")
    assert cubo["keys"][0]["f"] == 12.0 and "t" not in cubo["keys"][0]
    auto = next(o for o in n["objects"] if o["name"] == "auto")
    assert auto["path"]["start"] == 6.0 and auto["path"]["end"] == 23
    assert n["camera"]["moves"][0]["end"] == 12.0
    assert len(n["world"]["lights"]) == 1
    assert n["render"]["glare"]["type"] == "Bloom"  # dal preset night_city


def test_risolvi_materiale():
    m = S.risolvi_materiale("emissive:#CFF2E3:2.5")
    assert m["emissive_only"] and m["emission_strength"] == 2.5 and m["emission"] == "#CFF2E3"
    m = S.risolvi_materiale("wood:#112233")
    assert m["color"] == "#112233" and m["roughness"] == S.MATERIALI["wood"]["roughness"]
    m = S.risolvi_materiale({"preset": "metal", "roughness": 0.9})
    assert m["metallic"] == 1.0 and m["roughness"] == 0.9
    assert S.risolvi_materiale("#ABCDEF")["color"] == "#ABCDEF"
    assert S.hex_a_rgb("#fff") == (1.0, 1.0, 1.0)


def test_cli_validazione(tmp_path, capsys):
    buona = tmp_path / "buona.json"
    buona.write_text(json.dumps(base_spec()), encoding="utf-8")
    cattiva = tmp_path / "cattiva.json"
    cattiva.write_text("{ non json", encoding="utf-8")
    assert S.main([str(buona)]) == 0
    assert S.main([str(buona), str(cattiva)]) == 1
    assert "JSON non valido" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# Matematica dei movimenti
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("nome", sorted(moto.EASING))
def test_easing_estremi(nome):
    assert moto.ease(nome, 0.0) == pytest.approx(0.0, abs=1e-3)
    assert moto.ease(nome, 1.0) == pytest.approx(1.0, abs=1e-3)
    assert moto.ease(nome, -1) == moto.ease(nome, 0) and moto.ease(nome, 2) == moto.ease(nome, 1)


def test_campiona_chiavi():
    chiavi = [{"f": 0, "location": [0, 0, 0]}, {"f": 10, "location": [10, 0, 0], "ease": "linear"}]
    assert moto.campiona_chiavi(chiavi, "location", 5) == pytest.approx((5, 0, 0))
    assert moto.campiona_chiavi(chiavi, "location", -3) == [0, 0, 0]
    assert moto.campiona_chiavi(chiavi, "location", 99) == [10, 0, 0]
    assert moto.campiona_chiavi(chiavi, "lens", 5, base=35) == 35
    assert moto.campiona_chiavi([{"t": 1.0, "lens": 50}], "lens", 0) == 50


def test_look_at_euler():
    rx, ry, rz = moto.look_at_euler((0, -5, 0), (0, 0, 0))
    assert (math.degrees(rx), ry, math.degrees(rz)) == pytest.approx((90, 0, 0), abs=1e-6)
    rx, _, rz = moto.look_at_euler((0, 0, 0), (3, 0, 0))
    assert math.degrees(rz) == pytest.approx(-90)
    rx, _, _ = moto.look_at_euler((0, 0, 5), (0, 0, 0))
    assert math.degrees(rx) == pytest.approx(0, abs=1e-6)
    assert moto.srotola([3.1, -3.1, -3.0]) == pytest.approx([3.1, 3.1 + (2 * math.pi - 6.2), 2 * math.pi - 3.0])


def test_percorso_e_ruote():
    p = moto.Percorso([[0, 0, 0], [0, -10, 0]], liscio=False)
    assert p.lunghezza == pytest.approx(10)
    obj = {"location": [0, 0, 0], "path": {"points": [[0, 0, 0], [0, -10, 0]], "start": 0, "end": 10,
                                           "ease": "linear", "smooth": False}}
    camp = moto.campiona_oggetto(obj, 11)
    assert camp[5]["location"] == pytest.approx((0, -5, 0))
    assert camp[5]["rotation"][2] == pytest.approx(0)          # fronte (-Y) lungo il moto
    assert camp[10]["distance"] == pytest.approx(10)
    # auto animata con chiavi che va in retromarcia: distanza negativa
    retro = {"keys": [{"f": 0, "location": [0, 0, 0]}, {"f": 10, "location": [0, 4, 0], "ease": "linear"}]}
    assert moto.campiona_oggetto(retro, 11)[-1]["distance"] == pytest.approx(-4)
    assert moto.campiona_oggetto({"location": [1, 2, 3]}, 5) is None


def test_movimenti_camera():
    base = {"location": [0, -10, 1], "look_at": [0, 0, 1], "lens": 35}
    dolly = moto.campiona_camera(dict(base, moves=[{"type": "dolly_in", "distance": 2, "ease": "linear"}]), 11)
    assert dolly[0]["location"] == pytest.approx((0, -10, 1))
    assert dolly[-1]["location"] == pytest.approx((0, -8, 1))
    orb = moto.campiona_camera(dict(base, moves=[{"type": "orbit", "angle": 90, "ease": "linear"}]), 11)
    assert orb[-1]["location"] == pytest.approx((10, 0, 1), abs=1e-6)
    assert math.degrees(orb[-1]["rotation"][2]) == pytest.approx(90, abs=1e-6)
    pan = moto.campiona_camera(dict(base, moves=[{"type": "pan", "angle": 30}]), 5)
    assert pan[-1]["location"] == pytest.approx(pan[0]["location"])
    assert math.degrees(pan[-1]["rotation"][2] - pan[0]["rotation"][2]) == pytest.approx(30)
    zoom = moto.campiona_camera(dict(base, moves=[{"type": "zoom", "lens_end": 70}]), 5)
    assert zoom[-1]["lens"] == pytest.approx(70)
    # tracking: la camera segue il bersaglio con l'offset dato
    tr = moto.campiona_camera(dict(base, moves=[{"type": "tracking", "target": "auto", "offset": [0, -5, 1]}]), 3,
                              risolvi=lambda nome, f: (f * 1.0, 0.0, 0.0))
    assert tr[2]["location"] == pytest.approx((2, -5, 1))
    # micro-mosso: deterministico e piccolo
    hh = dict(base, handheld={"amplitude": 0.02, "rotation": 0.5, "seed": 3})
    a, b = moto.campiona_camera(hh, 24), moto.campiona_camera(hh, 24)
    assert a == b
    assert max(abs(p["location"][0]) for p in a) <= 0.02 + 1e-9
    # chiavi con look_at su oggetto
    k = {"keys": [{"f": 0, "location": [0, -5, 1], "look_at": "auto"}]}
    out = moto.campiona_camera(k, 2, risolvi=lambda n, f: (0.0, 0.0, 1.0))
    assert math.degrees(out[0]["rotation"][0]) == pytest.approx(90)


def test_pose_e_camminata():
    p = moto.posa("sitting_seiza")
    assert p["pelvis_drop"] > 0.5 and "knee_l" in p["joints"]
    obj = {"pose": "standing", "walk": {"cadence": 2.0}, "pose_keys": []}
    pose = moto.campiona_pose(obj, 24, None)
    hip = [q["joints"]["hip_l"][0] for q in pose]
    assert max(hip) > 10 and min(hip) < -10
    # due passi al secondo: dopo 12 frame (0.5 s) la fase e' tornata uguale
    assert pose[12]["joints"]["hip_l"][0] == pytest.approx(pose[0]["joints"]["hip_l"][0], abs=1e-6)
    gira = {"pose": "standing", "pose_keys": [{"f": 0, "joints": {"head": [0, 0, 0]}},
                                              {"f": 10, "joints": {"head": [0, 0, 40]}, "ease": "linear"}]}
    pose = moto.campiona_pose(gira, 11, None)
    assert pose[5]["joints"]["head"][2] == pytest.approx(20)


def test_parsing_cli():
    assert moto.range_frames(None, 24) == (0, 23)
    assert moto.range_frames("4-10", 24) == (4, 10)
    assert moto.range_frames("7", 24) == (7, 7)
    with pytest.raises(ValueError):
        moto.range_frames("10-30", 24)
    assert moto.risoluzione("1056x594") == (1056, 594)
    assert moto.risoluzione("641x361") == (640, 360)
    with pytest.raises(ValueError):
        moto.risoluzione("grande")


# ---------------------------------------------------------------------------
# Confronto (ffmpeg)
# ---------------------------------------------------------------------------


def _video_barra(percorso: Path, n: int, inizio: int = 0) -> None:
    """Clip 96x54 a 24 fps con una barra bianca che scorre (frame inizio..inizio+n-1)."""
    fr = np.zeros((n, 54, 96), dtype=np.uint8)
    for i in range(n):
        x = 4 + (i + inizio) * 2
        fr[i, 10:44, x:x + 6] = 255
        fr[i, 30:34, :] = 90
    subprocess.run([FFMPEG, "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "gray", "-s", "96x54", "-r", "24",
                    "-i", "pipe:0", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "10", str(percorso)],
                   input=fr.tobytes(), check=True)


@pytest.mark.skipif(FFMPEG is None, reason="ffmpeg non disponibile")
def test_confronta_griglia_e_offset(tmp_path):
    target = tmp_path / "target.mp4"
    blockout = tmp_path / "blockout.mp4"
    _video_barra(target, 36)
    _video_barra(blockout, 36, inizio=-5)   # il blockout e' 5 frame in ritardo
    stima = confronta.stima_offset(target, blockout, 0.5)
    assert stima[0][0] == 5
    img = confronta.griglia(target, blockout, [0.2, 0.6, 1.0], offset=5 / 24, larghezza=96, overlay=True)
    assert img.width == 3 * 96 + 4 * 6
    assert img.height > 3 * 54
    out = tmp_path / "griglia.png"
    assert confronta.main(["--target", str(target), "--blockout", str(blockout), "--frames", "0,12",
                           "--larghezza", "96", "--out", str(out)]) == 0
    assert out.exists()
    assert confronta.istanti_da_argomenti(None, None, 2, 1.0) == [0.25, 0.75]


# ---------------------------------------------------------------------------
# Smoke render con Blender
# ---------------------------------------------------------------------------


def _ffprobe(percorso: Path) -> dict:
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries",
                          "stream=codec_type,codec_name,width,height,r_frame_rate,nb_frames", "-of", "json",
                          str(percorso)], check=True, capture_output=True, text=True).stdout
    return json.loads(out)


@pytest.mark.skipif(BLENDER is None or FFMPEG is None, reason="blender/ffmpeg non disponibili")
def test_smoke_render(tmp_path):
    s = base_spec()
    s["meta"]["frames"] = 2
    s["world"] = {"preset": "night_city"}
    s["objects"].append({"name": "strada", "type": "street", "size": [10, 10]})
    s["objects"][0]["path"] = {"points": [[0, 2, 0], [0, 0, 0]]}
    s["objects"][1]["walk"] = True
    s["camera"]["moves"] = [{"type": "dolly_in", "distance": 0.5}]
    s["camera"]["dof"] = {"focus": "lei", "fstop": 4}
    sp = tmp_path / "smoke.json"
    sp.write_text(json.dumps(s), encoding="utf-8")
    out = tmp_path / "smoke.mp4"
    script = CARTELLA / "build_shot.py"
    cmd = [BLENDER, "-b", "--factory-startup", "--python", str(script), "--", "--spec", str(sp),
           "--out", str(out), "--res", "160x90", "--samples", "4"]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
    assert r.returncode == 0, r.stdout[-2000:] + r.stderr[-2000:]
    info = _ffprobe(out)
    video = [x for x in info["streams"] if x["codec_type"] == "video"]
    assert [x for x in info["streams"] if x["codec_type"] == "audio"] == []
    assert video[0]["codec_name"] == "h264"
    assert (video[0]["width"], video[0]["height"]) == (160, 90)
    assert video[0]["r_frame_rate"] == "24/1"
    assert int(video[0]["nb_frames"]) == 2
    resoconto = json.loads(out.with_suffix(".render.json").read_text())
    assert resoconto["frames"] == [0, 1] and resoconto["samples"] == 4

    # still PNG e spec non valida (codice d'uscita 2)
    r = subprocess.run(cmd[:-6] + ["--out", str(tmp_path / "still.mp4"), "--still", "1", "--res", "160x90",
                                   "--samples", "2"], capture_output=True, text=True, timeout=180)
    assert r.returncode == 0, r.stderr[-2000:]
    assert (tmp_path / "still.png").exists()
    rotta = copy.deepcopy(s)
    rotta["objects"][0]["type"] = "astronave"
    sp.write_text(json.dumps(rotta), encoding="utf-8")
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
    assert r.returncode == 2 and "tipo sconosciuto" in r.stderr
