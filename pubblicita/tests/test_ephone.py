"""Test del client ePhone con HTTP finto: nessuna rete, nessuna chiave reale."""
from __future__ import annotations

import base64
import io
import json
import logging
from pathlib import Path

import pytest
import requests
from PIL import Image

from pubblicita.ephone import client as client_mod
from pubblicita.ephone import pricing
from pubblicita.ephone.__main__ import main
from pubblicita.ephone.client import (
    ClientEphone, ErroreAPI, RispostaInattesa, SubmitIncerto, analizza_stato, analizza_submit,
    carica_configurazione, normalizza_stato,
)
from pubblicita.ephone.lavori import Esecutore
from pubblicita.ephone.manifest import carica as carica_manifest
from pubblicita.ephone.manifest import da_dati
from pubblicita.ephone.modelli import SEEDANCE_20, SEEDANCE_25, SEEDREAM_5_PRO
from pubblicita.ephone.richieste import ErroreValidazione, costruisci_immagine, costruisci_video

CHIAVE = "sk-finta-SEGRETISSIMA-0123456789"
BASE = "https://api.ephone.ai"
ESEMPIO = Path(__file__).resolve().parents[1] / "seedance" / "manifest.example.json"
MP4 = b"\x00\x00\x00\x18ftypmp42" + b"x" * 2048


# --- HTTP finto ---------------------------------------------------------------------------------

class RispostaFinta:
    def __init__(self, status=200, dati=None, testo=None, headers=None, contenuto=None):
        self.status_code = status
        self._dati = dati
        self._testo = testo
        self.headers = headers or {}
        self._contenuto = contenuto

    def json(self):
        if self._dati is None:
            raise ValueError("non JSON")
        return json.loads(json.dumps(self._dati))

    @property
    def text(self):
        if self._testo is not None:
            return self._testo
        return json.dumps(self._dati) if self._dati is not None else ""

    def iter_content(self, chunk_size=1024):
        dati = self._contenuto or b""
        for i in range(0, len(dati), chunk_size):
            yield dati[i:i + chunk_size]


class SessioneFinta:
    """Regole (metodo, frammento di URL) -> sequenza di risposte; l'ultima si ripete."""

    def __init__(self):
        self.regole = []
        self.chiamate = []

    def su(self, metodo, frammento, *risposte):
        self.regole.append([metodo, frammento, list(risposte)])
        return self

    def request(self, method, url, **kw):
        self.chiamate.append({"method": method, "url": url, "headers": kw.get("headers", {}),
                              "json": kw.get("json")})
        for metodo, frammento, risposte in self.regole:
            if metodo == method and frammento in url:
                r = risposte.pop(0) if len(risposte) > 1 else risposte[0]
                if callable(r) and not isinstance(r, RispostaFinta):
                    r = r(method, url, kw)
                if isinstance(r, BaseException):
                    raise r
                return r
        raise AssertionError(f"chiamata non prevista: {method} {url}")

    def di(self, metodo, frammento=""):
        return [c for c in self.chiamate if c["method"] == metodo and frammento in c["url"]]


@pytest.fixture(autouse=True)
def niente_rete(monkeypatch):
    def vietato(*a, **k):
        raise AssertionError("tentata una richiesta HTTP reale")
    monkeypatch.setattr(requests.Session, "request", vietato)
    monkeypatch.delenv("EPHONE_API_KEY", raising=False)
    monkeypatch.delenv("EPHONE_CNY_PER_USD", raising=False)
    monkeypatch.delenv("EPHONE_GROUP_RATIO", raising=False)


def png(percorso: Path, w=640, h=480, formato="PNG") -> Path:
    Image.new("RGB", (w, h), (200, 120, 40)).save(percorso, format=formato)
    return percorso


def png_b64(w=320, h=320) -> str:
    buf = io.BytesIO()
    Image.new("RGB", (w, h), (10, 20, 30)).save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode()


def client_finto(sessione, api="unified", sleep=None):
    return ClientEphone(CHIAVE, BASE, api, sessione=sessione, sleep=sleep or (lambda s: None))


def esecutore(sessione, tmp_path, api="unified", sleeps=None, **kw):
    sleeps = sleeps if sleeps is not None else []
    return Esecutore(client_finto(sessione, api), tmp_path / "out", api=api,
                     sleep=sleeps.append, sonda=None, notifica=lambda t: None, **kw)


# --- payload ------------------------------------------------------------------------------------

def test_payload_testo_unificato_e_nativo():
    r = costruisci_video({"id": "s01", "prompt": "  a car at night ", "duration": 5, "resolution": "1080p",
                          "aspect_ratio": "16:9", "generate_audio": False})
    assert r.modalita == "testo"
    assert r.payload_unificato() == {
        "model": "doubao-seedance-2-5-260628",
        "input": {"prompt": "a car at night", "duration": 5, "resolution": "1080p", "aspect_ratio": "16:9",
                  "generate_audio": False, "watermark": False},
    }
    percorso, nativo = r.payload("native")
    assert percorso == "/doubao/api/v3/contents/generations/tasks"
    assert nativo == {
        "model": "doubao-seedance-2-5-260628",
        "content": [{"type": "text", "text": "a car at night"}],
        "resolution": "1080p", "duration": 5, "generate_audio": False, "watermark": False, "ratio": "16:9",
    }


def test_payload_primo_e_ultimo_frame(tmp_path):
    png(tmp_path / "a.png")
    png(tmp_path / "b.jpg", formato="JPEG")
    r = costruisci_video({"id": "s02", "prompt": "move", "first_frame": "a.png", "last_frame": "b.jpg",
                          "aspect_ratio": "4:3"}, tmp_path)
    assert r.modalita == "immagine"
    assert r.input["first_frame"].startswith("data:image/png;base64,")
    assert r.input["last_frame"].startswith("data:image/jpeg;base64,")
    assert r.rapporto_input == pytest.approx(640 / 480)
    contenuto = r.payload_nativo()["content"]
    assert [c.get("role") for c in contenuto] == [None, "first_frame", "last_frame"]
    assert contenuto[1]["image_url"]["url"] == r.input["first_frame"]
    assert "first_frame" in r.payload_unificato()["input"]


def test_payload_omni_reference():
    r = costruisci_video({
        "id": "s03", "prompt": "same framing as the blockout",
        "reference_images": ["https://cdn.example.com/char.png", "asset://ast-1"],
        "reference_videos": [{"url": "https://cdn.example.com/blockout.mp4", "duration_s": 5}],
        "reference_audio": ["https://cdn.example.com/beat.mp3"],
        "omni_reference_task_type": "reference", "web_search": True,
        "callback_url": "https://hook.example.com/x", "aspect_ratio": "16:9", "duration": 5,
    })
    assert r.modalita == "omni" and r.con_video
    unif = r.payload_unificato()
    assert unif["callback_url"] == "https://hook.example.com/x"
    assert unif["input"]["reference_videos"] == ["https://cdn.example.com/blockout.mp4"]
    assert unif["input"]["omni_reference_task_type"] == "reference"
    nat = r.payload_nativo()
    ruoli = [(c["type"], c.get("role")) for c in nat["content"]]
    assert ruoli == [("text", None), ("image_url", "reference_image"), ("image_url", "reference_image"),
                     ("video_url", "reference_video"), ("audio_url", "reference_audio")]
    assert nat["tools"] == [{"type": "web_search"}]
    assert nat["omni_reference_task_type"] == "reference"
    assert nat["callback_url"] == "https://hook.example.com/x"
    assert "web_search" not in nat
    assert r.secondi_video_input() == (5.0, True)


def test_payload_immagine_seedream(tmp_path):
    png(tmp_path / "blockout.png", 1280, 720)
    r = costruisci_immagine({"id": "k01", "prompt": "photoreal version", "images": ["blockout.png"],
                             "size": "2K", "aspect_ratio": "16:9"}, tmp_path)
    corpo = r.payload_unificato()
    assert corpo["model"] == SEEDREAM_5_PRO.nome
    assert corpo["input"]["watermark"] is False          # il default del modello è true
    assert corpo["input"]["images"][0].startswith("data:image/png;base64,")
    percorso, sincrono = r.payload("native")
    assert percorso == "/v1/images/edits" and sincrono["image"].startswith("data:image/png")
    senza_ref = costruisci_immagine({"id": "k02", "prompt": "x"})
    assert senza_ref.payload("native")[0] == "/v1/images/generations"


# --- validazione --------------------------------------------------------------------------------

CASI_NON_VALIDI = [
    ({"first_frame": "https://x/a.png", "reference_images": ["https://x/b.png"]}, "si escludono"),
    ({"last_frame": "https://x/a.png"}, "richiede anche first_frame"),
    ({"duration": 3}, "'duration'"),
    ({"duration": 20, "model": "seedance-2.0"}, "fra 4 e 15"),
    ({"duration": 5.5}, "'duration'"),
    ({"resolution": "1080p", "model": "doubao-seedance-2-0-fast-260128"}, "non disponibile"),
    ({"resolution": "4k"}, "non disponibile"),
    ({"reference_images": [f"https://x/{i}.png" for i in range(31)]}, "massimo 30"),
    ({"reference_videos": [f"https://x/{i}.mp4" for i in range(4)], "model": "seedance-2.0"}, "massimo 3"),
    ({"reference_videos": [{"url": "https://x/a.mp4", "duration_s": 20},
                           {"url": "https://x/b.mp4", "duration_s": 15}]}, "in totale"),
    ({"reference_videos": [{"url": "https://x/a.mp4", "duration_s": 1}]}, "fra 2"),
    ({"reference_videos": ["https://x/a.mp4"], "omni_reference_task_type": "edit",
      "aspect_ratio": "16:9", "duration": -1}, "adaptive"),
    ({"reference_videos": ["https://x/a.mp4"], "omni_reference_task_type": "edit", "duration": 5}, "duration -1"),
    ({"reference_images": ["https://x/a.png"], "omni_reference_task_type": "extend"}, "reference_video"),
    ({"reference_videos": [{"url": "https://x/a.mp4", "duration_s": 3}], "omni_reference_task_type": "edit"}, "fra 4"),
    ({"reference_images": ["https://x/a.png"], "omni_reference_task_type": "reference",
      "model": "seedance-2.0"}, "non è supportato"),
    ({"omni_reference_task_type": "reference"}, "solo con reference"),
    ({"reference_audio": ["https://x/a.mp3"], "model": "seedance-2.0"}, "non accetta solo audio"),
    ({"reference_videos": ["clip_locale.mp4"]}, "asset upload"),
    ({"reference_videos": ["data:video/mp4;base64,AAAA"]}, "base64"),
    ({"reference_audio": ["/tmp/musica.wav"]}, "locale"),
    ({"prompt": "x" * 2001}, "massimo 2000"),
    ({"prompt": "   "}, "serve un 'prompt'"),
    ({"durata": 5}, "campi sconosciuti"),
    ({"id": "a/b"}, "'id'"),
    ({"output_format": "mov", "model": "seedance-2.0"}, "output_format"),
    ({"priority": 10}, "'priority'"),
    ({"generate_audio": "no"}, "true/false"),
    ({"aspect_ratio": "2:1"}, "'aspect_ratio'"),
    ({"execution_expires_after": 60}, "execution_expires_after"),
    ({"model": "seedance-9"}, "modello video sconosciuto"),
]


@pytest.mark.parametrize("modifica,atteso", CASI_NON_VALIDI)
def test_validazioni(modifica, atteso, tmp_path):
    spec = {"id": "s01", "prompt": "a shot", **modifica}
    with pytest.raises(ErroreValidazione) as e:
        costruisci_video(spec, tmp_path)
    assert atteso in str(e.value)


def test_validazioni_valide_ai_limiti():
    r = costruisci_video({"id": "e1", "reference_videos": [{"url": "https://x/a.mp4", "duration_s": 30}],
                          "omni_reference_task_type": "edit", "aspect_ratio": "adaptive", "duration": -1})
    assert r.input["duration"] == -1
    assert costruisci_video({"id": "a1", "reference_audio": ["https://x/a.mp3"]}).modalita == "omni"
    assert costruisci_video({"id": "d30", "prompt": "x", "duration": 30}).input["duration"] == 30


def test_tutti_i_problemi_insieme():
    with pytest.raises(ErroreValidazione) as e:
        costruisci_video({"id": "s01", "prompt": "x", "duration": 99, "resolution": "8k", "priority": -1})
    assert len(e.value.problemi) == 3


def test_controlli_immagini_locali(tmp_path):
    with pytest.raises(ErroreValidazione, match="lato"):
        costruisci_video({"id": "s", "prompt": "x", "first_frame": str(png(tmp_path / "p.png", 200, 200))})
    with pytest.raises(ErroreValidazione, match="rapporto"):
        costruisci_video({"id": "s", "prompt": "x", "first_frame": str(png(tmp_path / "w.png", 1000, 300))})
    with pytest.raises(ErroreValidazione, match="non trovata"):
        costruisci_video({"id": "s", "prompt": "x", "first_frame": "manca.png"}, tmp_path)
    (tmp_path / "rotta.png").write_bytes(b"non un'immagine")
    with pytest.raises(ErroreValidazione, match="non leggibile"):
        costruisci_video({"id": "s", "prompt": "x", "first_frame": "rotta.png"}, tmp_path)
    # formati insoliti diventano PNG
    png(tmp_path / "f.bmp", 800, 600, formato="BMP")
    r = costruisci_video({"id": "s", "prompt": "x", "first_frame": "f.bmp"}, tmp_path)
    assert r.input["first_frame"].startswith("data:image/png;base64,")
    # data URI già pronto: controllato ma inviato così com'è
    uri = "data:image/png;base64," + png_b64(400, 400)
    assert costruisci_video({"id": "s", "prompt": "x", "first_frame": uri}).input["first_frame"] == uri


def test_avviso_rapporto_diverso(tmp_path):
    png(tmp_path / "q.png", 800, 600)
    r = costruisci_video({"id": "s", "prompt": "x", "first_frame": "q.png", "aspect_ratio": "16:9"}, tmp_path)
    assert any("rapporto" in a for a in r.avvisi)


# --- manifest -----------------------------------------------------------------------------------

def test_manifest_variabili_default_e_percorsi(tmp_path):
    png(tmp_path / "still.png")
    dati = {
        "_nota": "commento ignorato",
        "variabili": {"soggetto": "a red bike", "stile": "cinematic"},
        "defaults": {"resolution": "720p", "duration": 5, "reference_images": ["https://x/char.png"]},
        "shots": [
            {"id": "a", "prompt": "Wide shot of $soggetto. ${stile}.", "_blockout": "x"},
            {"id": "b", "prompt": "Close-up of $soggetto", "reference_images": ["https://x/other.png"],
             "duration": 8},
            {"id": "c", "prompt": "Start", "first_frame": "still.png", "reference_images": None},
        ],
    }
    m = da_dati(dati, tmp_path)
    a, b, c = m.richieste
    assert a.input["prompt"] == "Wide shot of a red bike. cinematic."
    assert a.input["reference_images"] == ["https://x/char.png"]
    assert b.input["reference_images"] == ["https://x/other.png"] and b.input["duration"] == 8
    assert c.input["first_frame"].startswith("data:image/png")
    assert "reference_images" not in c.input


def test_manifest_errori_aggregati(tmp_path):
    dati = {"defaults": {"duration": 5}, "extra": 1, "shots": [
        {"id": "a", "prompt": "uses $mancante"},
        {"id": "a", "prompt": "dup"},
        {"id": "b", "prompt": "x", "duration": 2},
    ]}
    with pytest.raises(ErroreValidazione) as e:
        da_dati(dati, tmp_path)
    testo = str(e.value)
    assert "$mancante" in testo and "duplicato" in testo and "b:" in testo and "extra" in testo


def test_manifest_esempio_valido():
    m = carica_manifest(ESEMPIO)
    assert len(m.richieste) == 10
    assert all("$" not in r.input["prompt"] for r in m.richieste)
    assert all(r.input["resolution"] == "1080p" and r.input["generate_audio"] is False for r in m.richieste)
    cny, usd = pricing.somma([r.stima() for r in m.richieste])
    assert usd == pytest.approx(24.057, abs=0.01)
    assert carica_manifest(ESEMPIO, {"setup03"}).richieste[0].id == "setup03"
    with pytest.raises(ErroreValidazione, match="assenti"):
        carica_manifest(ESEMPIO, {"nessuno"})


# --- prezzi -------------------------------------------------------------------------------------

def test_stime_seedance():
    s = pricing.stima_video(SEEDANCE_25, "1080p", "16:9", 5)
    assert s.token == 243000 and (s.larghezza, s.altezza) == (1920, 1080)
    assert s.cny == pytest.approx(243000 * 77 / 1e6 * 0.9)
    assert s.usd == pytest.approx(s.cny / 7.0)
    assert pricing.stima_video(SEEDANCE_25, "720p", "16:9", 5).cny == pytest.approx(6.804)
    con_video = pricing.stima_video(SEEDANCE_25, "1080p", "16:9", 5, durata_input_s=5, con_video=True)
    assert con_video.token == 486000 and con_video.prezzo_milione_cny == 46
    assert pricing.stima_video(SEEDANCE_20, "4k", "16:9", 5).cny == pytest.approx(972000 * 26 / 1e6 * 0.9)
    assert pricing.dimensioni_output("1080p", "9:16") == (1080, 1920)
    assert pricing.dimensioni_output("1080p", "1:1") == (1440, 1440)
    auto = pricing.stima_video(SEEDANCE_25, "720p", "16:9", -1)
    assert auto.durata_out_s == 30 and auto.note
    edit = pricing.stima_video(SEEDANCE_25, "720p", "adaptive", -1, durata_input_s=6, con_video=True)
    assert edit.durata_out_s == 6


def test_stime_seedream_e_cambio(monkeypatch):
    assert pricing.stima_immagine(SEEDREAM_5_PRO, "1K").cny == pytest.approx(0.27)
    assert pricing.stima_immagine(SEEDREAM_5_PRO, "2K").cny == pytest.approx(0.54)
    assert pricing.stima_immagine(SEEDREAM_5_PRO, "4K", n_riferimenti=3).cny == pytest.approx((0.6 + 0.04) * 0.9)
    monkeypatch.setenv("EPHONE_CNY_PER_USD", "7.2")
    assert pricing.stima_video(SEEDANCE_25, "1080p", "16:9", 5).usd == pytest.approx(16.8399 / 7.2, rel=1e-4)


def test_stima_richiesta_con_video_di_durata_ignota():
    r = costruisci_video({"id": "s", "reference_videos": ["https://x/a.mp4"], "prompt": "x",
                          "resolution": "1080p", "duration": 5})
    s = r.stima()
    assert s.durata_in_s == 30 and any("non nota" in n for n in s.note)


# --- normalizzazione e parsing ------------------------------------------------------------------

@pytest.mark.parametrize("grezzo,atteso", [
    ("queued", "queued"), ("in_progress", "running"), ("running", "running"), ("completed", "succeeded"),
    ("succeeded", "succeeded"), ("SUCCESS", "succeeded"), ("failed", "failed"), ("cancelled", "failed"),
    ("expired", "failed"), ("NOT_START", "queued"), ("boh", None), (None, None),
])
def test_normalizza_stato(grezzo, atteso):
    assert normalizza_stato(grezzo) == atteso


def test_analizza_stato_unificato_e_nativo():
    st = analizza_stato({"id": "task_1", "status": "completed",
                         "outputs": ["https://c/x.mp4?sig=1", "https://c/x_last.png"]})
    assert st.stato == "succeeded" and st.video_url == "https://c/x.mp4?sig=1"
    nat = analizza_stato({"id": "cgt-1", "status": "succeeded",
                          "content": {"video_url": "https://c/v", "last_frame_url": "https://c/f"},
                          "usage": {"completion_tokens": 243000, "total_tokens": 243000}})
    assert (nat.video_url, nat.ultimo_frame_url, nat.usage["completion_tokens"]) == ("https://c/v", "https://c/f", 243000)
    avvolto = analizza_stato({"code": "success", "message": "", "data": {"task_id": "t9", "status": "in_progress"}})
    assert avvolto.stato == "running" and avvolto.task_id == "t9"
    annidato = analizza_stato({"code": "success", "data": {"task_id": "t", "status": "SUCCESS",
                                                           "data": {"content": {"video_url": "https://c/n.mp4"}}}})
    assert annidato.video_url == "https://c/n.mp4"
    fallito = analizza_stato({"id": "x", "status": "failed", "error": {"code": "OutputVideoSensitive",
                                                                       "message": "blocked"}})
    assert fallito.stato == "failed" and "blocked" in fallito.errore
    assert analizza_stato({"id": "x", "status": "cancelled"}).errore == "task cancelled"
    immagine = analizza_stato({"id": "i", "status": "completed", "outputs": [{"url": "https://c/img.png"}]})
    assert immagine.immagini == ["https://c/img.png"]


def test_analizza_stato_inatteso():
    with pytest.raises(RispostaInattesa) as e:
        analizza_stato({"id": "x", "status": "teleporting"})
    assert e.value.grezzo == {"id": "x", "status": "teleporting"}
    with pytest.raises(RispostaInattesa):
        analizza_stato({"id": "x", "status": "completed", "outputs": []})
    with pytest.raises(RispostaInattesa):
        analizza_stato(["lista"])


def test_analizza_submit():
    assert analizza_submit({"id": "task_1", "status": "queued", "created_at": 1}) == ("task_1", "queued")
    assert analizza_submit({"code": "success", "data": "task_2"}) == ("task_2", "queued")
    assert analizza_submit({"data": {"task_id": "t3"}}) == ("t3", "queued")
    assert analizza_submit({"id": "cgt-4"}) == ("cgt-4", "queued")
    with pytest.raises(RispostaInattesa):
        analizza_submit({"ok": True})


# --- trasporto: errori, retry, submit non ripetuto ----------------------------------------------

def test_errore_http_quota():
    s = SessioneFinta().su("POST", "/v1/task/submit", RispostaFinta(
        402, {"error": {"type": "insufficient_quota", "message": "Insufficient balance"}}))
    with pytest.raises(ErroreAPI) as e:
        client_finto(s).invia("/v1/task/submit", {"model": "m", "input": {}})
    assert e.value.status == 402 and e.value.tipo == "insufficient_quota" and "Insufficient balance" in str(e.value)
    assert len(s.di("POST")) == 1


def test_errore_in_corpo_con_http_200():
    s = SessioneFinta().su("GET", "/v1/task/t", RispostaFinta(200, {"success": False, "message": "token scaduto"}))
    with pytest.raises(ErroreAPI, match="token scaduto"):
        client_finto(s).stato("t")
    s2 = SessioneFinta().su("GET", "/v1/task/t", RispostaFinta(200, testo="<html>gateway</html>"))
    with pytest.raises(RispostaInattesa):
        client_finto(s2).stato("t")


def test_retry_get_con_backoff_e_retry_after():
    attese = []
    s = SessioneFinta().su("GET", "/v1/task/t1",
                           RispostaFinta(503, {"error": {"message": "busy"}}),
                           RispostaFinta(429, {}, headers={"Retry-After": "7"}),
                           requests.exceptions.ConnectionError("reset"),
                           RispostaFinta(200, {"id": "t1", "status": "queued"}))
    st = client_finto(s, sleep=attese.append).stato("t1")
    assert st.stato == "queued" and len(s.chiamate) == 4
    assert attese[1] == 7 and len(attese) == 3


def test_get_esaurisce_i_tentativi():
    s = SessioneFinta().su("GET", "/v1/task/t1", RispostaFinta(500, {"error": {"message": "giù"}}))
    with pytest.raises(ErroreAPI, match="dopo 5 tentativi"):
        client_finto(s).stato("t1")


@pytest.mark.parametrize("problema", [requests.exceptions.ReadTimeout("lento"), RispostaFinta(502, {}),
                                      RispostaFinta(504, testo="gateway timeout"),
                                      requests.exceptions.ConnectionError("Connection aborted.")])
def test_submit_ambiguo_non_ripetuto(problema):
    s = SessioneFinta().su("POST", "/v1/task/submit", problema)
    with pytest.raises(SubmitIncerto, match="console"):
        client_finto(s).invia("/v1/task/submit", {"model": "m", "input": {}})
    assert len(s.di("POST")) == 1


def test_submit_ripetuto_se_mai_partito_o_respinto():
    s = SessioneFinta().su("POST", "/v1/task/submit", requests.exceptions.ConnectTimeout("no connect"),
                           RispostaFinta(429, {"error": {"message": "slow down"}}),
                           RispostaFinta(200, {"id": "task_ok", "status": "queued"}))
    assert client_finto(s).invia("/v1/task/submit", {})[0] == "task_ok"
    assert len(s.di("POST")) == 3


# --- redazione della chiave ---------------------------------------------------------------------

def test_chiave_mai_in_errori_log_ledger(tmp_path, caplog):
    eco = RispostaFinta(401, {"error": {"message": f"Invalid token Bearer {CHIAVE}"}})
    s = SessioneFinta().su("POST", "/v1/task/submit", eco)
    ex = esecutore(s, tmp_path)
    r = costruisci_video({"id": "s01", "prompt": f"testo con la chiave {CHIAVE} dentro"})
    with caplog.at_level(logging.DEBUG, logger="pubblicita.ephone"):
        client_mod.log.warning("prova %s", CHIAVE)
        esito = ex.esegui(ex.pianifica([r]))[0]
    assert esito.esito == "rifiutato" and CHIAVE not in esito.messaggio
    assert CHIAVE not in caplog.text and "***" in caplog.text
    ledger = (tmp_path / "out" / "seedance" / "jobs.json").read_text()
    assert CHIAVE not in ledger and "***" in ledger
    assert CHIAVE not in repr(ex.client)
    # l'header arriva al gateway
    assert s.chiamate[0]["headers"]["Authorization"] == f"Bearer {CHIAVE}"


def test_configurazione_da_env_e_file(tmp_path):
    f = tmp_path / ".env"
    f.write_text('# commento\nexport EPHONE_API_KEY="dal-file-123"\nEPHONE_BASE_URL=https://platform.ephone.ai/ # x\n')
    conf = carica_configurazione(f, {})
    assert conf.chiave == "dal-file-123" and conf.url_base == "https://platform.ephone.ai"
    assert conf.origine_chiave == "file .env"
    conf2 = carica_configurazione(f, {"EPHONE_API_KEY": "da-ambiente-456"})
    assert conf2.chiave == "da-ambiente-456" and conf2.origine_chiave == "ambiente"
    assert carica_configurazione(tmp_path / "manca.env", {}).chiave is None
    assert carica_configurazione(f, {"EPHONE_API_MODE": "native"}).modo_api == "native"
    with pytest.raises(client_mod.ErroreConfigurazione):
        carica_configurazione(f, {"EPHONE_API_MODE": "boh"})
    assert client_mod.redigi("x dal-file-123 y") == "x *** y"


# --- esecuzione: ledger, polling, download, resume ----------------------------------------------

def sessione_completa(tmp_path, task="task_A", cdn="https://cdn.example.com"):
    letture = {}

    def stato(method, url, kw):
        # il ledger deve contenere il task PRIMA del primo polling
        if "prima" not in letture:
            voce = json.loads((tmp_path / "out" / "seedance" / "jobs.json").read_text())["jobs"]["s01"]
            letture["prima"] = (voce["task_id"], voce["status"])
            return RispostaFinta(200, {"id": task, "status": "in_progress"})
        return RispostaFinta(200, {"id": task, "status": "completed", "completed_at": 2,
                                   "outputs": [f"{cdn}/a.mp4?x=1", f"{cdn}/a_last.png"],
                                   "usage": {"completion_tokens": 243000}})

    s = (SessioneFinta()
         .su("POST", "/v1/task/submit", RispostaFinta(200, {"id": task, "status": "queued", "created_at": 1}))
         .su("GET", f"/v1/task/{task}", stato)
         .su("GET", "a.mp4", RispostaFinta(200, headers={"Content-Type": "video/mp4"}, contenuto=MP4))
         .su("GET", "a_last.png", RispostaFinta(200, headers={"Content-Type": "image/png"}, contenuto=b"PNGDATA")))
    return s, letture


def test_batch_completo(tmp_path):
    s, letture = sessione_completa(tmp_path)
    sleeps = []
    ex = esecutore(s, tmp_path, sleeps=sleeps)
    r = costruisci_video({"id": "s01", "prompt": "hero shot", "duration": 5, "resolution": "1080p",
                          "aspect_ratio": "16:9", "return_last_frame": True})
    esiti = ex.esegui(ex.pianifica([r]))
    assert [e.esito for e in esiti] == ["scaricato"]
    assert letture["prima"] == ("task_A", "queued")
    cartella = tmp_path / "out" / "seedance"
    assert (cartella / "s01.mp4").read_bytes() == MP4
    assert (cartella / "s01_last.png").read_bytes() == b"PNGDATA"
    sidecar = json.loads((cartella / "s01.json").read_text())
    assert sidecar["task_id"] == "task_A" and sidecar["prompt"] == "hero shot"
    assert sidecar["params"]["resolution"] == "1080p" and sidecar["usage"]["completion_tokens"] == 243000
    assert sidecar["cost"]["usd"] == pytest.approx(2.4057, abs=1e-3)
    voce = json.loads((cartella / "jobs.json").read_text())["jobs"]["s01"]
    assert voce["status"] == "downloaded" and voce["files"]["main"].endswith("s01.mp4")
    assert voce["payload"]["input"]["prompt"] == "hero shot" and voce["estimate"]["token"] == 243000
    assert sleeps == [5.0]
    # niente chiave verso il CDN
    assert all("Authorization" not in c["headers"] for c in s.chiamate if "cdn.example.com" in c["url"])
    assert not list(cartella.glob("*.part")) and not list(cartella.glob("*.tmp"))
    # idempotenza: senza --force si salta, con --force si rigenera e si conserva lo storico
    assert ex.pianifica([r])[0].azione == "salta"
    assert ex.pianifica([r], forza=True)[0].azione == "invia"
    s2, _ = sessione_completa(tmp_path, task="task_B")
    ex2 = esecutore(s2, tmp_path)
    ex2.esegui(ex2.pianifica([r], forza=True))
    voce = json.loads((cartella / "jobs.json").read_text())["jobs"]["s01"]
    assert voce["task_id"] == "task_B" and voce["history"][0]["task_id"] == "task_A"


def test_polling_con_backoff(tmp_path):
    risposte = [RispostaFinta(200, {"id": "t", "status": "queued"})] * 5 + [
        RispostaFinta(200, {"id": "t", "status": "completed", "outputs": ["https://c/v.mp4"]})]
    s = (SessioneFinta().su("POST", "/v1/task/submit", RispostaFinta(200, {"id": "t"}))
         .su("GET", "/v1/task/t", *risposte)
         .su("GET", "https://c/v.mp4", RispostaFinta(200, contenuto=MP4)))
    sleeps = []
    ex = esecutore(s, tmp_path, sleeps=sleeps)
    ex.esegui(ex.pianifica([costruisci_video({"id": "s01", "prompt": "x"})]))
    assert sleeps == [5.0, 7.5, 11.25, 15.0, 15.0]


def test_batch_riprende_task_gia_creato_senza_nuovo_submit(tmp_path):
    ex = esecutore(SessioneFinta(), tmp_path)
    ex.ledger_video.aggiorna("s01", task_id="task_X", status="running", api="unified", kind="video", ext="mp4")
    r = costruisci_video({"id": "s01", "prompt": "x"})
    assert ex.pianifica([r])[0].azione == "riprendi"
    ex.ledger_video.aggiorna("s02", status="submit_uncertain")
    r2 = costruisci_video({"id": "s02", "prompt": "x"})
    assert ex.pianifica([r2])[0].azione == "salta"


def test_submit_incerto_registrato(tmp_path):
    s = SessioneFinta().su("POST", "/v1/task/submit", requests.exceptions.ReadTimeout("lento"))
    ex = esecutore(s, tmp_path)
    r = costruisci_video({"id": "s01", "prompt": "x"})
    assert ex.esegui(ex.pianifica([r]))[0].esito == "incerto"
    voce = ex.ledger_video.leggi("s01")
    assert voce["status"] == "submit_uncertain" and "console" in voce["error"]
    assert ex.pianifica([r])[0].azione == "salta"
    lavori, incerti = ex.da_riprendere()
    assert lavori == [] and "resume --assign s01" in incerti[0]
    ex.assegna("s01", "task_trovato")
    assert ex.da_riprendere()[0] == [("s01", "video")]


def test_resume_nativo(tmp_path):
    s = (SessioneFinta()
         .su("GET", "/doubao/api/v3/contents/generations/tasks/cgt-9",
             RispostaFinta(200, {"id": "cgt-9", "status": "succeeded",
                                 "content": {"video_url": "https://cdn.ark/v9.mp4"},
                                 "usage": {"completion_tokens": 108000}}))
         .su("GET", "v9.mp4", RispostaFinta(200, contenuto=MP4)))
    ex = esecutore(s, tmp_path, api="unified")
    ex.ledger_video.aggiorna("s09", task_id="cgt-9", status="running", api="native", kind="video", ext="mp4",
                             model=SEEDANCE_25.nome, pricing_basis={"resolution": "720p", "with_video": False})
    ex.ledger_video.aggiorna("s10", status="downloaded", task_id="t10",
                             files={"main": str(tmp_path / "out" / "seedance" / "s10.mp4")})
    (tmp_path / "out" / "seedance" / "s10.mp4").write_bytes(MP4)
    esiti = ex.riprendi()
    assert [(e.id, e.esito) for e in esiti] == [("s09", "scaricato")]
    assert esiti[0].costo_usd == pytest.approx(108000 * 70 / 1e6 * 0.9 / 7, abs=1e-4)
    assert (tmp_path / "out" / "seedance" / "s09.mp4").exists()


def test_task_fallito(tmp_path):
    s = (SessioneFinta().su("POST", "/v1/task/submit", RispostaFinta(200, {"id": "t"}))
         .su("GET", "/v1/task/t", RispostaFinta(200, {"id": "t", "status": "failed",
                                                      "error": "Content violates safety policy"})))
    ex = esecutore(s, tmp_path)
    esito = ex.esegui(ex.pianifica([costruisci_video({"id": "s01", "prompt": "x"})]))[0]
    assert esito.esito == "fallito" and "safety" in esito.messaggio
    assert ex.ledger_video.leggi("s01")["status"] == "failed"
    # un task fallito non è addebitato: si può reinviare senza --force
    assert ex.pianifica([costruisci_video({"id": "s01", "prompt": "x"})])[0].azione == "invia"


def test_timeout_polling(tmp_path):
    tempo = [0.0]

    def dormi(secondi):
        tempo[0] += secondi

    s = (SessioneFinta().su("POST", "/v1/task/submit", RispostaFinta(200, {"id": "t"}))
         .su("GET", "/v1/task/t", RispostaFinta(200, {"id": "t", "status": "in_progress"})))
    ex = Esecutore(client_finto(s), tmp_path / "out", sleep=dormi, orologio=lambda: tempo[0],
                   timeout_s=60, sonda=None, notifica=lambda t: None)
    esito = ex.esegui(ex.pianifica([costruisci_video({"id": "s01", "prompt": "x"})]))[0]
    assert esito.esito == "timeout"
    voce = ex.ledger_video.leggi("s01")
    assert voce["status"] == "running" and voce["task_id"] == "t"
    assert ex.da_riprendere()[0] == [("s01", "video")]


def test_risposta_inattesa_salvata(tmp_path):
    s = (SessioneFinta().su("POST", "/v1/task/submit", RispostaFinta(200, {"id": "t"}))
         .su("GET", "/v1/task/t", RispostaFinta(200, {"id": "t", "stato_strano": True})))
    ex = esecutore(s, tmp_path)
    esito = ex.esegui(ex.pianifica([costruisci_video({"id": "s01", "prompt": "x"})]))[0]
    assert esito.esito == "errore" and "ledger" in esito.messaggio
    assert ex.ledger_video.leggi("s01")["raw_response"] == {"id": "t", "stato_strano": True}


def test_submit_senza_id_e_incerto(tmp_path):
    s = SessioneFinta().su("POST", "/v1/task/submit", RispostaFinta(200, {"accepted": True}))
    ex = esecutore(s, tmp_path)
    assert ex.esegui(ex.pianifica([costruisci_video({"id": "s01", "prompt": "x"})]))[0].esito == "incerto"
    assert ex.ledger_video.leggi("s01")["raw_response"] == {"accepted": True}


def test_download_link_scaduto(tmp_path):
    s = SessioneFinta().su("GET", "https://cdn/x.mp4", RispostaFinta(200, testo="<html>expired</html>",
                                                                     headers={"Content-Type": "text/html"}))
    with pytest.raises(ErroreAPI, match="text/html"):
        client_finto(s).scarica("https://cdn/x.mp4", tmp_path / "x.mp4")
    assert not (tmp_path / "x.mp4").exists() and not (tmp_path / "x.mp4.part").exists()


def test_immagine_sincrona_e_unificata(tmp_path):
    s = SessioneFinta().su("POST", "/v1/images/generations", RispostaFinta(200, {"data": [{"b64_json": png_b64()}]}))
    ex = esecutore(s, tmp_path, api="native")
    esito = ex.esegui(ex.pianifica([costruisci_immagine({"id": "k01", "prompt": "poster"})]))[0]
    assert esito.esito == "scaricato"
    assert Image.open(tmp_path / "out" / "seedream" / "k01.png").size == (320, 320)
    assert s.chiamate[0]["json"]["watermark"] is False
    s2 = (SessioneFinta().su("POST", "/v1/task/submit", RispostaFinta(200, {"id": "img1", "status": "queued"}))
          .su("GET", "/v1/task/img1", RispostaFinta(200, {"id": "img1", "status": "completed",
                                                          "outputs": ["https://c/i.jpeg"]}))
          .su("GET", "https://c/i.jpeg", RispostaFinta(200, contenuto=b"JPEGDATA")))
    ex2 = esecutore(s2, tmp_path)
    r = costruisci_immagine({"id": "k02", "prompt": "x", "output_format": "jpeg"})
    assert ex2.esegui(ex2.pianifica([r]))[0].esito == "scaricato"
    assert (tmp_path / "out" / "seedream" / "k02.jpg").read_bytes() == b"JPEGDATA"
    assert s2.chiamate[0]["json"]["model"] == SEEDREAM_5_PRO.nome


# --- CLI ----------------------------------------------------------------------------------------

def argomenti_base(tmp_path):
    return ["--output-dir", str(tmp_path / "out"), "--env-file", str(tmp_path / "nessuno.env")]


def test_cli_batch_chiede_conferma_e_rispetta_il_tetto(tmp_path, capsys):
    s = SessioneFinta()
    amb = {"EPHONE_API_KEY": CHIAVE}
    assert main(["batch", str(ESEMPIO), *argomenti_base(tmp_path)], sessione=s, ambiente=amb) == 2
    assert "--yes" in capsys.readouterr().err
    assert main(["batch", str(ESEMPIO), "--yes", "--max-cost-usd", "5", *argomenti_base(tmp_path)],
                sessione=s, ambiente=amb) == 2
    assert s.chiamate == []
    assert main(["batch", str(ESEMPIO), "--dry-run", "--only", "setup01", *argomenti_base(tmp_path)],
                sessione=s, ambiente={}) == 0
    uscita = capsys.readouterr().out
    assert '"model": "doubao-seedance-2-5-260628"' in uscita and s.chiamate == []


def test_cli_video_end_to_end(tmp_path, capsys):
    s, _ = sessione_completa(tmp_path)
    codice = main(["video", "--id", "s01", "--prompt", "hero shot", "--yes", *argomenti_base(tmp_path)],
                  sessione=s, sleep=lambda x: None, ambiente={"EPHONE_API_KEY": CHIAVE})
    assert codice == 0
    corpo = s.di("POST")[0]["json"]
    assert corpo["input"] == {"prompt": "hero shot", "duration": 5, "resolution": "1080p",
                              "aspect_ratio": "16:9", "generate_audio": False, "watermark": False}
    assert (tmp_path / "out" / "seedance" / "s01.mp4").exists()
    uscita = capsys.readouterr()
    assert CHIAVE not in uscita.out + uscita.err


def test_cli_chiave_mancante(tmp_path, capsys):
    codice = main(["video", "--id", "s01", "--prompt", "x", "--yes", *argomenti_base(tmp_path)],
                  sessione=SessioneFinta(), ambiente={})
    assert codice == 3 and "EPHONE_API_KEY" in capsys.readouterr().err


def test_cli_validazione_prima_di_spendere(tmp_path, capsys):
    s = SessioneFinta()
    codice = main(["video", "--id", "s01", "--prompt", "x", "--ref-video", "locale.mp4", "--yes",
                   *argomenti_base(tmp_path)], sessione=s, ambiente={"EPHONE_API_KEY": CHIAVE})
    assert codice == 2 and s.chiamate == []
    assert "asset upload" in capsys.readouterr().err


def test_cli_check(tmp_path, capsys):
    s = (SessioneFinta()
         .su("GET", "/v1/models", RispostaFinta(200, {"object": "list", "data": [
             {"id": "doubao-seedance-2-5-260628"}, {"id": "doubao-seedream-5-0-pro-260628"}, {"id": "gpt-x"}]}))
         .su("GET", "/v1/dashboard/billing/subscription", RispostaFinta(404, {"error": {"message": "no"}})))
    assert main(["check", *argomenti_base(tmp_path)], sessione=s, ambiente={"EPHONE_API_KEY": CHIAVE}) == 0
    uscita = capsys.readouterr().out
    assert uscita.count("disponibile") == 2 and CHIAVE not in uscita
    s2 = SessioneFinta().su("GET", "/v1/models", RispostaFinta(401, {"error": {"message": "No token provided"}}))
    assert main(["check", *argomenti_base(tmp_path)], sessione=s2, ambiente={"EPHONE_API_KEY": CHIAVE}) == 1


def test_cli_estimate(tmp_path, capsys):
    assert main(["estimate", "--count", "10", "--json", *argomenti_base(tmp_path)], ambiente={}) == 0
    dati = json.loads(capsys.readouterr().out)
    assert dati["totale_usd"] == pytest.approx(24.057, abs=0.01)
    assert main(["estimate", str(ESEMPIO), *argomenti_base(tmp_path)], ambiente={}) == 0
    assert "TOTALE" in capsys.readouterr().out
    assert main(["estimate", "--resolution", "1080p", "--model", "seedance-2.0-fast",
                 *argomenti_base(tmp_path)], ambiente={}) == 2


def test_cli_status_cancel_resume(tmp_path, capsys):
    ex = esecutore(SessioneFinta(), tmp_path)
    ex.ledger_video.aggiorna("s05", task_id="cgt-5", status="queued", api="native", kind="video", ext="mp4")
    s = (SessioneFinta()
         .su("GET", "/doubao/api/v3/contents/generations/tasks/cgt-5", RispostaFinta(200, {"id": "cgt-5", "status": "running"}))
         .su("DELETE", "/doubao/api/v3/contents/generations/tasks/cgt-5", RispostaFinta(200, {})))
    amb = {"EPHONE_API_KEY": CHIAVE}
    assert main(["status", "s05", *argomenti_base(tmp_path)], sessione=s, ambiente=amb) == 0
    assert json.loads(capsys.readouterr().out)["stato"] == "running"
    assert ex.ledger_video.leggi("s05")["status"] == "running"
    assert main(["cancel", "s05", *argomenti_base(tmp_path)], sessione=s, ambiente=amb) == 0
    assert ex.ledger_video.leggi("s05")["raw_status"] == "cancelled"
    assert len(s.di("DELETE")) == 1
    capsys.readouterr()
    assert main(["resume", *argomenti_base(tmp_path)], sessione=s, ambiente=amb) == 0
    assert "Nessun task" in capsys.readouterr().out
    assert main(["resume", "--assign", "ignoto=t", *argomenti_base(tmp_path)], sessione=s, ambiente=amb) == 2


def test_cli_asset_upload(tmp_path, capsys):
    s = SessioneFinta().su("POST", "/v1/task/submit", RispostaFinta(200, {"code": 0, "data": {"Id": "asset-20261002-abc"}}))
    codice = main(["asset", "upload", "--url", "https://cdn.example.com/face.jpg", "--type", "image",
                   "--name", "protagonista", *argomenti_base(tmp_path)], sessione=s, ambiente={"EPHONE_API_KEY": CHIAVE})
    assert codice == 0
    assert s.chiamate[0]["json"] == {"model": "doubao-asset", "input": {
        "action": "upload", "url": "https://cdn.example.com/face.jpg", "asset_type": "Image", "name": "protagonista"}}
    assert "asset://asset-20261002-abc" in capsys.readouterr().out
    errore = SessioneFinta().su("POST", "/v1/task/submit", RispostaFinta(200, {
        "ResponseMetadata": {"Error": {"Code": "InvalidParameter", "Message": "url not reachable"}}}))
    assert main(["asset", "list", *argomenti_base(tmp_path)], sessione=errore, ambiente={"EPHONE_API_KEY": CHIAVE}) == 1
    assert main(["asset", "raw", "--input-json", "[1]", *argomenti_base(tmp_path)], sessione=s,
                ambiente={"EPHONE_API_KEY": CHIAVE}) == 2


def test_solo_invio_poi_resume(tmp_path):
    s = (SessioneFinta().su("POST", "/v1/task/submit", RispostaFinta(200, {"id": "t1", "status": "queued"}))
         .su("GET", "/v1/task/t1", RispostaFinta(200, {"id": "t1", "status": "completed",
                                                       "outputs": ["https://c/t1.mp4"]}))
         .su("GET", "https://c/t1.mp4", RispostaFinta(200, contenuto=MP4)))
    ex = esecutore(s, tmp_path)
    r = costruisci_video({"id": "s01", "prompt": "x"})
    esiti = ex.esegui(ex.pianifica([r]), attendi=False)
    assert [e.esito for e in esiti] == ["inviato"] and s.di("GET") == []
    assert ex.esegui(ex.pianifica([r]), attendi=False)[0].esito == "inviato"   # nessun secondo submit
    assert len(s.di("POST")) == 1
    assert [e.esito for e in ex.riprendi()] == ["scaricato"]


def test_errore_imprevisto_non_ferma_gli_altri(tmp_path):
    def esplode(method, url, kw):
        raise RuntimeError("bug imprevisto")

    s = (SessioneFinta()
         .su("POST", "/v1/task/submit", lambda m, u, kw: RispostaFinta(200, {"id": "t_" + kw["json"]["input"]["prompt"]}))
         .su("GET", "/v1/task/t_a", esplode)
         .su("GET", "/v1/task/t_b", RispostaFinta(200, {"id": "t_b", "status": "completed",
                                                        "outputs": ["https://c/b.mp4"]}))
         .su("GET", "https://c/b.mp4", RispostaFinta(200, contenuto=MP4)))
    ex = esecutore(s, tmp_path, concorrenza=2)
    richieste = [costruisci_video({"id": "a", "prompt": "a"}), costruisci_video({"id": "b", "prompt": "b"})]
    esiti = {e.id: e for e in ex.esegui(ex.pianifica(richieste))}
    assert esiti["a"].esito == "errore" and "bug imprevisto" in esiti["a"].messaggio
    assert esiti["b"].esito == "scaricato"
    assert ex.ledger_video.leggi("a")["task_id"] == "t_a"   # il task resta riprendibile
