"""Riga di comando: ``python3 -m pubblicita.ephone <comando> ...``

Comandi: check, video, image, batch, resume, status, cancel, estimate, asset.
Nulla che costi denaro parte senza ``--yes``; ``--dry-run`` mostra i payload senza inviarli.
Codici di uscita: 0 ok, 1 errori su qualche task, 2 validazione o conferma mancante,
3 configurazione (chiave mancante).
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path

from . import pricing
from .client import (
    API_AMMESSE, ClientEphone, ErroreConfigurazione, ErroreEphone, FiltroRedazione, StatoTask,
    carica_configurazione, redigi, redigi_oggetto,
)
from .lavori import CARTELLA_OUTPUT, Esecutore, Esito
from .manifest import carica as carica_manifest
from .media import compatta
from .modelli import (
    IMMAGINE_PREDEFINITA, MODELLI_VIDEO, RAPPORTI_IMMAGINE, RAPPORTI_VIDEO, SEEDANCE_25, SEEDREAM_5_PRO,
    TIPI_TASK_OMNI, modello_immagine, modello_video, nomi_accettati,
)
from .richieste import ErroreValidazione, costruisci_immagine, costruisci_video

ESITO_OK, ESITO_ERRORI, ESITO_VALIDAZIONE, ESITO_CONFIG = 0, 1, 2, 3


def _out(testo: str = "") -> None:
    print(redigi(testo), flush=True)


def _err(testo: str) -> None:
    print(redigi(testo), file=sys.stderr, flush=True)


# --- parser ---------------------------------------------------------------------------------

def _parser() -> argparse.ArgumentParser:
    comuni = argparse.ArgumentParser(add_help=False)
    comuni.add_argument("--api", choices=API_AMMESSE, default=None,
                        help="formato API: unified (default, /v1/task/submit) o native (mirror Ark)")
    comuni.add_argument("--base-url", default=None, help="URL del gateway (default EPHONE_BASE_URL o https://api.ephone.ai)")
    comuni.add_argument("--env-file", default=None, help="file .env alternativo a pubblicita/.env")
    comuni.add_argument("--output-dir", default=None,
                        help=f"cartella output (default {CARTELLA_OUTPUT}); i clip vanno in <dir>/seedance")
    comuni.add_argument("-v", "--verbose", action="store_true", help="log dettagliato")

    p = argparse.ArgumentParser(prog="python3 -m pubblicita.ephone",
                                description="Client ePhone per Seedance 2.5 e Seedream 5.0 Pro.")
    sub = p.add_subparsers(dest="comando", required=True)

    sub.add_parser("check", parents=[comuni], help="verifica la chiave e i modelli disponibili (gratis)")

    def esecuzione(sp, batch: bool = False):
        sp.add_argument("--yes", action="store_true", help="conferma la spesa stimata")
        sp.add_argument("--dry-run", action="store_true", help="mostra payload e stima senza inviare nulla")
        sp.add_argument("--force", action="store_true", help="rigenera anche se l'output esiste già")
        sp.add_argument("--max-cost-usd", type=float, default=None, help="annulla se la stima supera questo importo")
        sp.add_argument("--timeout-min", type=float, default=30.0, help="attesa massima per task (default 30)")
        sp.add_argument("--no-wait", action="store_true", help="solo submit; scarica poi con `resume`")
        if batch:
            sp.add_argument("--concurrency", type=int, default=3, help="task attivi insieme (default 3)")

    v = sub.add_parser("video", parents=[comuni], help="genera un clip Seedance")
    v.add_argument("--id", required=True, help="id dello shot (nome del file di output)")
    v.add_argument("--prompt", default=None)
    v.add_argument("--model", default=SEEDANCE_25.nome)
    v.add_argument("--duration", type=int, default=None,
                   help="secondi (4-30 per 2.5) oppure -1; default 5 (-1 per il task edit)")
    v.add_argument("--resolution", default="1080p")
    v.add_argument("--aspect-ratio", default=None, choices=RAPPORTI_VIDEO,
                   help="default 16:9 (adaptive per i task edit/extend)")
    v.add_argument("--first-frame", default=None, help="immagine iniziale: file locale, URL o asset://ID")
    v.add_argument("--last-frame", default=None)
    v.add_argument("--ref-image", action="append", default=[], help="immagine di riferimento (ripetibile)")
    v.add_argument("--ref-video", action="append", default=[], help="video di riferimento: URL o asset://ID")
    v.add_argument("--ref-audio", action="append", default=[], help="audio di riferimento: URL o asset://ID")
    v.add_argument("--task-type", choices=TIPI_TASK_OMNI, default=None, help="omni_reference_task_type")
    v.add_argument("--audio", action="store_true", help="genera anche l'audio (default: muto)")
    v.add_argument("--return-last-frame", action="store_true", help="scarica anche l'ultimo frame PNG")
    v.add_argument("--output-format", choices=("mp4", "mov"), default=None)
    v.add_argument("--priority", type=int, default=None)
    esecuzione(v)

    im = sub.add_parser("image", parents=[comuni], help="genera un'immagine Seedream 5.0 Pro")
    im.add_argument("--id", required=True)
    im.add_argument("--prompt", required=True)
    im.add_argument("--model", default=IMMAGINE_PREDEFINITA.nome)
    im.add_argument("--ref", action="append", default=[], help="immagine di riferimento (ripetibile, max 10)")
    im.add_argument("--size", default="2K", help="1K, 2K, 4K oppure LxA (default 2K)")
    im.add_argument("--aspect-ratio", default="16:9", choices=RAPPORTI_IMMAGINE)
    im.add_argument("--output-format", choices=("png", "jpeg"), default="png")
    im.add_argument("--seed", type=int, default=None)
    esecuzione(im)

    b = sub.add_parser("batch", parents=[comuni], help="genera tutti gli shot di un manifest")
    b.add_argument("manifest")
    b.add_argument("--only", default=None, help="solo questi shot (id separati da virgola)")
    b.add_argument("--auto-duration", type=float, default=None,
                   help="secondi da assumere nelle stime quando duration è -1")
    esecuzione(b, batch=True)

    r = sub.add_parser("resume", parents=[comuni], help="riprende i task non conclusi del ledger")
    r.add_argument("--assign", action="append", default=[], metavar="ID=TASK",
                   help="collega a mano un task id a uno shot dall'esito incerto")
    r.add_argument("--concurrency", type=int, default=3)
    r.add_argument("--timeout-min", type=float, default=30.0)

    s = sub.add_parser("status", parents=[comuni], help="stato di un task (id shot o task id)")
    s.add_argument("ident")
    s.add_argument("--raw", action="store_true", help="mostra anche la risposta grezza")

    c = sub.add_parser("cancel", parents=[comuni], help="annulla un task in coda (id shot o task id)")
    c.add_argument("ident")

    e = sub.add_parser("estimate", parents=[comuni], help="stima dei costi (manifest o singolo task)")
    e.add_argument("manifest", nargs="?", default=None)
    e.add_argument("--only", default=None)
    e.add_argument("--model", default=None)
    e.add_argument("--duration", type=int, default=5)
    e.add_argument("--resolution", default="1080p")
    e.add_argument("--aspect-ratio", default="16:9")
    e.add_argument("--input-video-seconds", type=float, default=0.0,
                   help="secondi di video di riferimento in input (cambia prezzo e token)")
    e.add_argument("--count", type=int, default=1, help="numero di clip/immagini uguali")
    e.add_argument("--image", action="store_true", help="stima immagini Seedream invece di clip")
    e.add_argument("--size", default="2K")
    e.add_argument("--refs", type=int, default=0, help="immagini di riferimento per immagine")
    e.add_argument("--auto-duration", type=float, default=None)
    e.add_argument("--json", action="store_true")

    a = sub.add_parser("asset", parents=[comuni], help="libreria asset (doubao-asset, gratuita)")
    asub = a.add_subparsers(dest="azione", required=True)
    up = asub.add_parser("upload", parents=[comuni], help="registra un file pubblico come asset")
    up.add_argument("--url", required=True, help="URL pubblico del file")
    up.add_argument("--type", required=True, choices=("image", "video", "audio", "Image", "Video", "Audio"))
    up.add_argument("--name", default=None)
    up.add_argument("--group-id", default=None)
    q = asub.add_parser("query", parents=[comuni])
    q.add_argument("--id", required=True)
    asub.add_parser("list", parents=[comuni])
    d = asub.add_parser("delete", parents=[comuni])
    d.add_argument("--id", required=True)
    vs = asub.add_parser("validate-session", parents=[comuni], help="avvia la verifica di una persona reale")
    vs.add_argument("--callback-url", default=None)
    vr = asub.add_parser("validate-result", parents=[comuni])
    vr.add_argument("--token", required=True, help="byted_token restituito dalla sessione")
    raw = asub.add_parser("raw", parents=[comuni], help="input passato così com'è (per campi non previsti)")
    raw.add_argument("--input-json", required=True)
    return p


# --- supporto -------------------------------------------------------------------------------

class Contesto:
    def __init__(self, args, sessione=None, sleep=None, ambiente=None):
        self.args = args
        self.sessione = sessione
        self.sleep = sleep
        self.ambiente = os.environ if ambiente is None else ambiente
        self.conf = carica_configurazione(Path(args.env_file) if args.env_file else None, self.ambiente)
        self.cartella = Path(args.output_dir) if args.output_dir else Path(
            self.ambiente.get("EPHONE_OUTPUT_DIR") or CARTELLA_OUTPUT)

    def api(self, dal_manifest: str | None = None) -> str:
        return self.args.api or dal_manifest or self.ambiente.get("EPHONE_API_MODE") or "unified"

    def client(self, api: str | None = None) -> ClientEphone:
        chiave = self.conf.richiedi_chiave()
        return ClientEphone(chiave, self.args.base_url or self.conf.url_base, api or self.api(),
                            sessione=self.sessione, **({"sleep": self.sleep} if self.sleep else {}))

    def esecutore(self, client: ClientEphone, concorrenza: int = 3, timeout_min: float = 30.0) -> Esecutore:
        return Esecutore(client, self.cartella, api=client.api, concorrenza=concorrenza,
                         timeout_s=timeout_min * 60, sleep=self.sleep)

    def esecutore_offline(self, api: str) -> Esecutore:
        """Esecutore senza rete, per pianificare (ledger e file esistenti) prima di chiedere la chiave."""
        return Esecutore(ClientEphone(None, self.conf.url_base, api), self.cartella, api=api)


def _tabella_stime(stime, n_task: int | None = None) -> None:
    _out(f"{'shot':<14} {'descrizione':<44} {'token':>9} {'CNY':>9} {'USD':>8}")
    for s in stime:
        ident, _, descr = s.descrizione.partition(": ")
        if not descr:
            ident, descr = "-", s.descrizione
        _out(f"{ident:<14} {descr[:44]:<44} {s.token or '':>9} {s.cny:>9.2f} {s.usd:>8.2f}")
        for nota in s.note:
            _out(f"{'':<14}   nota: {nota}")
    cny, usd = pricing.somma(stime)
    etichetta = f"{n_task if n_task is not None else len(stime)} task"
    _out(f"{'TOTALE':<14} {etichetta:<44} {'':>9} {cny:>9.2f} {usd:>8.2f}")
    _out(f"(listino × {pricing.coeff_gruppo():g} gruppo bytedance, cambio {pricing.cambio_cny_usd():g} CNY/USD; "
         "si paga solo ciò che riesce)")


def _conferma(args, stime) -> int | None:
    """None se si può procedere, altrimenti il codice di uscita."""
    _, usd = pricing.somma(stime)
    if args.max_cost_usd is not None and usd > args.max_cost_usd:
        _err(f"Stima ${usd:.2f} oltre --max-cost-usd {args.max_cost_usd:.2f}: annullato.")
        return ESITO_VALIDAZIONE
    if args.dry_run:
        return None
    if not args.yes:
        _err(f"Spesa stimata ${usd:.2f}. Ripeti con --yes per procedere (oppure --dry-run per vedere i payload).")
        return ESITO_VALIDAZIONE
    return None


def _riepilogo(esiti: list[Esito]) -> int:
    if not esiti:
        _out("Niente da fare.")
        return ESITO_OK
    _out("")
    _out(f"{'shot':<14} {'esito':<11} dettagli")
    for e in esiti:
        dettaglio = e.file or e.messaggio
        if e.costo_usd is not None:
            dettaglio += f"  (${e.costo_usd:.2f})"
        _out(f"{e.id:<14} {e.esito:<11} {dettaglio}")
    spesa = sum(e.costo_usd for e in esiti if e.costo_usd)
    if spesa:
        _out(f"Costo effettivo (da usage): ${spesa:.2f}")
    if any(e.esito == "incerto" for e in esiti):
        _out("ATTENZIONE: ci sono submit dall'esito incerto. Controlla la console ePhone prima di ripetere; "
             "se il task esiste: `python3 -m pubblicita.ephone resume --assign ID=TASK`.")
    if any(e.esito in ("timeout", "interrotto", "inviato") for e in esiti):
        _out("Per scaricare i task ancora in corso: python3 -m pubblicita.ephone resume")
    return ESITO_OK if all(e.ok for e in esiti) else ESITO_ERRORI


def _esegui(ctx: Contesto, richieste, api: str, concorrenza: int = 1) -> int:
    args = ctx.args
    offline = ctx.esecutore_offline(api)
    piano = offline.pianifica(richieste, forza=args.force)
    da_inviare = [p.richiesta for p in piano if p.azione == "invia"]
    for p in piano:
        if p.azione != "invia":
            _out(f"[{p.richiesta.id}] {p.azione}: {p.motivo}")
    for r in richieste:
        for a in r.avvisi:
            _err(f"[{r.id}] avviso: {a}")
    stime = [r.stima(getattr(args, "auto_duration", None)) for r in da_inviare]
    if stime:
        _tabella_stime(stime)
    esito = _conferma(args, stime)
    if esito is not None:
        return esito
    if args.dry_run:
        for r in da_inviare:
            percorso, corpo = r.payload(api)
            _out(f"\n# {r.id} -> POST {percorso}")
            _out(json.dumps(compatta(corpo), ensure_ascii=False, indent=2))
        return ESITO_OK
    if not any(p.azione in ("invia", "riprendi") for p in piano):
        return _riepilogo([Esito(p.richiesta.id, "saltato", p.motivo) for p in piano])
    esecutore = ctx.esecutore(ctx.client(api), concorrenza, args.timeout_min)
    try:
        esiti = esecutore.esegui(piano, attendi=not args.no_wait)
    except KeyboardInterrupt:
        esecutore.interrompi()
        _err("Interrotto. I task creati sono nel ledger: riprendi con `python3 -m pubblicita.ephone resume`.")
        return ESITO_ERRORI
    return _riepilogo(esiti)


def _cerca_nel_ledger(ctx: Contesto, ident: str):
    esecutore = ctx.esecutore_offline(ctx.api())
    for ledger in (esecutore.ledger_video, esecutore.ledger_immagini):
        voce = ledger.leggi(ident)
        if voce is not None:
            return ledger, voce
    return None, None


def _trova_id_asset(obj) -> str | None:
    if isinstance(obj, dict):
        for k in ("Id", "AssetId", "asset_id", "assetId"):
            if isinstance(obj.get(k), str) and obj[k]:
                return obj[k]
        for k in ("data", "Result", "result", "asset"):
            trovato = _trova_id_asset(obj.get(k))
            if trovato:
                return trovato
    return None


# --- comandi --------------------------------------------------------------------------------

def cmd_check(ctx: Contesto) -> int:
    client = ctx.client("unified")
    _out(f"Gateway: {client.url_base}")
    _out(f"Chiave: presente (da {ctx.conf.origine_chiave})")
    nomi = client.modelli()
    visibili = {n.lower() for n in nomi}
    _out(f"Chiave valida: {len(nomi)} modelli visibili.")
    tutto_ok = True
    for m in (SEEDANCE_25, SEEDREAM_5_PRO):
        ok = bool(nomi_accettati(m) & visibili)
        tutto_ok &= ok
        _out(f"  {m.etichetta:<18} ({m.nome}): {'disponibile' if ok else 'NON visibile con questa chiave'}")
    altri = [m.etichetta for m in MODELLI_VIDEO[1:] if nomi_accettati(m) & visibili]
    if altri:
        _out(f"  altri modelli Seedance: {', '.join(altri)}")
    saldo = client.saldo()
    if saldo:
        _out(f"Saldo/limiti (endpoint billing): {json.dumps(saldo)}")
    if not tutto_ok:
        _out("Se un modello non è visibile, abilita il gruppo 'bytedance' per la chiave nella console ePhone.")
    return ESITO_OK if tutto_ok else ESITO_ERRORI


def cmd_video(ctx: Contesto) -> int:
    a = ctx.args
    modifica = a.task_type in ("edit", "extend")
    durata = a.duration if a.duration is not None else (-1 if a.task_type == "edit" else 5)
    spec = {
        "id": a.id, "model": a.model, "prompt": a.prompt, "duration": durata,
        "resolution": a.resolution, "aspect_ratio": a.aspect_ratio or ("adaptive" if modifica else "16:9"),
        "generate_audio": a.audio,
        "first_frame": a.first_frame, "last_frame": a.last_frame,
        "reference_images": a.ref_image or None, "reference_videos": a.ref_video or None,
        "reference_audio": a.ref_audio or None, "omni_reference_task_type": a.task_type,
        "return_last_frame": a.return_last_frame or None, "output_format": a.output_format,
        "priority": a.priority,
    }
    spec = {k: v for k, v in spec.items() if v is not None}
    richiesta = costruisci_video(spec, Path.cwd())
    return _esegui(ctx, [richiesta], ctx.api())


def cmd_image(ctx: Contesto) -> int:
    a = ctx.args
    spec = {"id": a.id, "model": a.model, "prompt": a.prompt, "images": a.ref or None, "size": a.size,
            "aspect_ratio": a.aspect_ratio, "output_format": a.output_format, "seed": a.seed,
            "watermark": False}
    richiesta = costruisci_immagine({k: v for k, v in spec.items() if v is not None}, Path.cwd())
    return _esegui(ctx, [richiesta], ctx.api())


def _solo(valore: str | None) -> set[str] | None:
    return {x.strip() for x in valore.split(",") if x.strip()} if valore else None


def cmd_batch(ctx: Contesto) -> int:
    a = ctx.args
    manifest = carica_manifest(a.manifest, _solo(a.only))
    for avviso in manifest.avvisi:
        _err(f"avviso: {avviso}")
    return _esegui(ctx, manifest.richieste, ctx.api(manifest.api), a.concurrency)


def cmd_resume(ctx: Contesto) -> int:
    a = ctx.args
    offline = ctx.esecutore_offline(ctx.api())
    for voce in a.assign:
        ident, sep, task = voce.partition("=")
        if not sep or not ident or not task:
            _err(f"--assign {voce!r}: formato atteso ID=TASK")
            return ESITO_VALIDAZIONE
        try:
            offline.assegna(ident.strip(), task.strip())
        except KeyError as e:
            _err(str(e.args[0]))
            return ESITO_VALIDAZIONE
        _out(f"{ident}: collegato al task {task}")
    lavori, incerti = offline.da_riprendere()
    if not lavori:
        for testo in incerti:
            _err(testo)
        _out("Nessun task da riprendere.")
        return ESITO_ERRORI if incerti else ESITO_OK
    esecutore = ctx.esecutore(ctx.client(), a.concurrency, a.timeout_min)
    try:
        esiti = esecutore.riprendi()
    except KeyboardInterrupt:
        esecutore.interrompi()
        _err("Interrotto: rilancia `resume` quando vuoi.")
        return ESITO_ERRORI
    return _riepilogo(esiti)


def cmd_status(ctx: Contesto) -> int:
    ledger, voce = _cerca_nel_ledger(ctx, ctx.args.ident)
    task_id, api = ctx.args.ident, ctx.api()
    if voce is not None:
        if not voce.get("task_id") or voce["task_id"] == "(sincrono)":
            _out(json.dumps({"id": voce.get("id"), "status": voce.get("status"), "error": voce.get("error")},
                            ensure_ascii=False, indent=2))
            return ESITO_OK
        task_id, api = voce["task_id"], ctx.args.api or voce.get("api") or api
    st: StatoTask = ctx.client(api).stato(task_id, api)
    if voce is not None and voce.get("status") not in (st.stato, "downloaded"):
        ledger.aggiorna(voce["id"], status=st.stato, raw_status=st.stato_grezzo)
    dati = st.come_dict()
    if ctx.args.raw:
        dati["grezzo"] = st.grezzo
    _out(json.dumps(redigi_oggetto(compatta(dati)), ensure_ascii=False, indent=2))
    return ESITO_OK


def cmd_cancel(ctx: Contesto) -> int:
    ledger, voce = _cerca_nel_ledger(ctx, ctx.args.ident)
    task_id = ctx.args.ident
    if voce is not None:
        if not voce.get("task_id"):
            _err(f"{ctx.args.ident}: nessun task id nel ledger (stato {voce.get('status')})")
            return ESITO_VALIDAZIONE
        task_id = voce["task_id"]
        if voce.get("api") == "unified":
            _err("Nota: il formato unificato non documenta l'annullamento; si usa il mirror Ark "
                 "(funziona solo se il task id è riconosciuto anche lì).")
    risposta = ctx.client().annulla(task_id)
    if voce is not None:
        ledger.aggiorna(voce["id"], status="failed", raw_status="cancelled", error="annullato dall'utente")
    _out(json.dumps(risposta, ensure_ascii=False, indent=2))
    return ESITO_OK


def cmd_estimate(ctx: Contesto) -> int:
    a = ctx.args
    if a.manifest:
        manifest = carica_manifest(a.manifest, _solo(a.only))
        stime = [r.stima(a.auto_duration) for r in manifest.richieste]
        quante = len(stime)
    elif a.image:
        m = modello_immagine(a.model)
        stime = [pricing.stima_immagine(m, a.size, None, a.refs, a.count)]
        quante = a.count
    else:
        m = modello_video(a.model)
        if a.resolution not in m.risoluzioni:
            _err(f"{m.etichetta} non supporta {a.resolution} ({', '.join(m.risoluzioni)})")
            return ESITO_VALIDAZIONE
        una = pricing.stima_video(m, a.resolution, a.aspect_ratio, a.duration,
                                  durata_input_s=a.input_video_seconds, con_video=a.input_video_seconds > 0,
                                  durata_auto_s=a.auto_duration)
        if a.count > 1:
            una.descrizione += f" ×{a.count}"
            una.token, una.cny, una.usd = una.token * a.count, una.cny * a.count, una.usd * a.count
        stime = [una]
        quante = a.count
    if a.json:
        cny, usd = pricing.somma(stime)
        _out(json.dumps({"stime": [s.come_dict() for s in stime], "totale_cny": round(cny, 4),
                         "totale_usd": round(usd, 4), "cambio_cny_usd": pricing.cambio_cny_usd(),
                         "coeff_gruppo": pricing.coeff_gruppo()}, ensure_ascii=False, indent=2))
    else:
        _tabella_stime(stime, quante)
    return ESITO_OK


def cmd_asset(ctx: Contesto) -> int:
    a = ctx.args
    if a.azione == "upload":
        ingresso = {"action": "upload", "url": a.url, "asset_type": a.type.capitalize()}
        if a.name:
            ingresso["name"] = a.name
        if a.group_id:
            ingresso["group_id"] = a.group_id
    elif a.azione == "query":
        ingresso = {"action": "query", "asset_id": a.id}
    elif a.azione == "list":
        ingresso = {"action": "list"}
    elif a.azione == "delete":
        ingresso = {"action": "delete", "asset_id": a.id}
    elif a.azione == "validate-session":
        ingresso = {"action": "create_validate_session"}
        if a.callback_url:
            ingresso["callback_url"] = a.callback_url
    elif a.azione == "validate-result":
        ingresso = {"action": "get_validate_result", "byted_token": a.token}
    else:
        try:
            ingresso = json.loads(a.input_json)
        except json.JSONDecodeError as e:
            _err(f"--input-json non è JSON valido: {e}")
            return ESITO_VALIDAZIONE
        if not isinstance(ingresso, dict) or "action" not in ingresso:
            _err("--input-json deve essere un oggetto con almeno 'action'")
            return ESITO_VALIDAZIONE
    risposta = ctx.client("unified").asset(ingresso)
    _out(json.dumps(risposta, ensure_ascii=False, indent=2))
    ident = _trova_id_asset(risposta)
    if a.azione == "upload" and ident:
        _out(f"\nDa usare nei manifest: asset://{ident}")
    return ESITO_OK


COMANDI = {
    "check": cmd_check, "video": cmd_video, "image": cmd_image, "batch": cmd_batch,
    "resume": cmd_resume, "status": cmd_status, "cancel": cmd_cancel, "estimate": cmd_estimate,
    "asset": cmd_asset,
}


def main(argv=None, *, sessione=None, sleep=None, ambiente=None) -> int:
    args = _parser().parse_args(argv)
    gestore = logging.StreamHandler(sys.stderr)
    gestore.addFilter(FiltroRedazione())
    gestore.setFormatter(logging.Formatter("%(levelname)s %(message)s"))
    registro = logging.getLogger("pubblicita.ephone")
    registro.handlers[:] = [gestore]
    registro.setLevel(logging.DEBUG if args.verbose else logging.WARNING)
    registro.propagate = False
    try:
        ctx = Contesto(args, sessione=sessione, sleep=sleep, ambiente=ambiente)
        return COMANDI[args.comando](ctx)
    except ErroreValidazione as e:
        _err("Richiesta non valida, nessuna chiamata effettuata:")
        if e.contesto:
            _err(f"  [{e.contesto}]")
        for problema in e.problemi:
            _err(f"  - {problema}")
        return ESITO_VALIDAZIONE
    except ErroreConfigurazione as e:
        _err(f"Configurazione: {e}")
        return ESITO_CONFIG
    except ErroreEphone as e:
        _err(f"Errore: {e}")
        return ESITO_ERRORI
    except ValueError as e:
        _err(f"Errore: {redigi(e)}")
        return ESITO_VALIDAZIONE


if __name__ == "__main__":
    sys.exit(main())
