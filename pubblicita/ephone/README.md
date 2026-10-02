# Client ePhone: Seedance 2.5 e Seedream 5.0 Pro

Questo pacchetto genera i clip del pannello inferiore dello spot con **Seedance 2.5**
(`doubao-seedance-2-5-260628`) e, quando servono, le immagini chiave con **Seedream 5.0 Pro**
(`doubao-seedream-5-0-pro-260628`). Passa per il gateway ePhone (`https://api.ephone.ai`).

Si usa da riga di comando:

```bash
python3 -m pubblicita.ephone <comando> [opzioni]      # --help su ogni comando
```

Comandi: `check`, `estimate`, `video`, `image`, `batch`, `resume`, `status`, `cancel`, `asset`.

Nessun comando spende soldi senza `--yes`: prima stampa la stima e poi si ferma. Con
`--dry-run` vedi i payload esatti senza inviare nulla, e senza chiave.

---

## 1. Chiave

La chiave si legge da `EPHONE_API_KEY` oppure, se la variabile manca, dal file
`pubblicita/.env`, che git ignora:

```bash
# una volta sola, in pubblicita/.env
EPHONE_API_KEY=sk-...
# facoltativi
EPHONE_BASE_URL=https://api.ephone.ai        # risponde anche https://platform.ephone.ai
EPHONE_API_MODE=unified                      # oppure native
```

Le stesse impostazioni si possono dare come variabili d'ambiente, che hanno la precedenza sul
file. Solo come variabile d'ambiente esiste anche `EPHONE_OUTPUT_DIR`, che sostituisce la
cartella `pubblicita/output` (equivale all'opzione `--output-dir`).

Poi verifica la chiave (è gratis):

```bash
python3 -m pubblicita.ephone check
```

`check` chiama `GET /v1/models` e ti dice se con questa chiave vedi Seedance 2.5 e Seedream 5 Pro.
Se un modello manca, abilita il gruppo "bytedance" per la chiave nella console ePhone.

Il codice non stampa mai la chiave: la toglie da log, messaggi d'errore, ledger e sidecar.
L'header `Authorization` va solo all'host del gateway e mai ai CDN da cui scarichiamo gli output.

## 2. Stime di costo

Seedance si paga a token:

`token ≈ (durata del video in input + durata dell'output) × larghezza × altezza × 24 / 1024`

Il prezzo è a milione di token: 77 CNY a 1080p e 70 CNY a 480p/720p (46 e 42 se l'input contiene
un video). Il gruppo "bytedance" applica un coefficiente di 0,9 e il cambio è di 7,0 CNY per USD.
Cambio e coefficiente si modificano con `EPHONE_CNY_PER_USD` ed `EPHONE_GROUP_RATIO`. Paghi
solo i task riusciti. A fine task il costo vero si calcola da `usage.completion_tokens` e finisce
nel sidecar.

| Caso (clip da 5 s, 16:9) | per clip | 10 clip |
|---|---|---|
| Seedance 2.5, 1080p | 16,84 CNY ≈ **$2,41** | 168,40 CNY ≈ **$24,06** |
| Seedance 2.5, 720p | 6,80 CNY ≈ $0,97 | 68,04 CNY ≈ $9,72 |
| Seedance 2.5, 480p | 3,03 CNY ≈ $0,43 | 30,26 CNY ≈ $4,32 |
| Seedance 2.5, 1080p, con 5 s di video di riferimento | 20,12 CNY ≈ $2,87 | 201,20 CNY ≈ $28,74 |
| Seedance 2.0 Fast, 720p (anteprime) | 3,60 CNY ≈ $0,51 | 35,96 CNY ≈ $5,14 |
| Seedance 2.0 Mini, 480p (anteprime) | 0,99 CNY ≈ $0,14 | 9,94 CNY ≈ $1,42 |
| Seedream 5.0 Pro, 2K (per immagine) | 0,54 CNY ≈ $0,08 | 5,40 CNY ≈ $0,77 |

Una clip da 10 s costa il doppio di una da 5 s. A parità di risoluzione il formato 9:16 costa
quanto il 16:9, perché il numero di pixel è lo stesso.

```bash
python3 -m pubblicita.ephone estimate --count 10                              # 10 × 5 s a 1080p
python3 -m pubblicita.ephone estimate --resolution 720p --duration 8
python3 -m pubblicita.ephone estimate pubblicita/seedance/manifest.example.json
python3 -m pubblicita.ephone estimate --image --size 2K --count 4 --refs 2
```

Quando `duration` vale `-1` la durata la sceglie il modello. In quel caso la stima prende il
massimo del modello (30 s per la 2.5) e così resta prudente. Puoi indicare tu una durata con
`--auto-duration`. Con un video in input il gateway applica anche un minimo di token che non è
documentato, quindi la stima può risultare più bassa del costo vero.

## 3. Un clip singolo

```bash
# solo testo (default: 2.5, 1080p, 16:9, 5 s, senza audio)
python3 -m pubblicita.ephone video --id setup01 --prompt "Low tracking shot alongside ..." --yes

# immagine iniziale (file locale -> data URI dopo i controlli) e, se vuoi, finale
python3 -m pubblicita.ephone video --id setup03 --prompt "..." \
    --first-frame pubblicita/output/seedream/setup03_key.png --last-frame fine.png --yes

# riferimenti omni: immagini, video e audio (i video solo come URL pubblico o asset://)
python3 -m pubblicita.ephone video --id setup05 --prompt "Same framing and motion as the reference video" \
    --ref-video https://storage.example.com/blockout/setup05.mp4 --ref-image personaggio.png \
    --task-type reference --yes

# rifare un video esistente (task edit): adaptive e durata -1 sono impostati in automatico
python3 -m pubblicita.ephone video --id setup06 --prompt "Turn this grey blockout into a photoreal night street" \
    --ref-video asset://<ID> --task-type edit --yes
```

Altre opzioni sono `--resolution`, `--aspect-ratio`, `--duration`, `--audio`, `--return-last-frame`
(scarica anche `<id>_last.png`), `--output-format mov`, `--priority`, `--no-wait` (fa solo il
submit, poi scarichi con `resume`), `--max-cost-usd`, `--timeout-min` e `--model` (accetta anche
gli alias `seedance-2.0`, `seedance-2.0-fast` e `seedance-2.0-mini`).

**Scrivi i prompt in inglese**: l'italiano non è fra le lingue supportate da Seedance.

## 4. Tutti gli shot: il manifest

Parti da `pubblicita/seedance/manifest.example.json` (10 setup da 5 s):

```json
{
  "variabili": {"soggetto": "...", "luogo": "...", "stile": "..."},
  "defaults": {"model": "doubao-seedance-2-5-260628", "resolution": "1080p", "aspect_ratio": "16:9",
               "duration": 5, "generate_audio": false, "watermark": false},
  "shots": [
    {"id": "setup01", "prompt": "Establishing aerial shot over $luogo; $soggetto enters frame. $stile."},
    {"id": "setup02", "prompt": "...", "first_frame": "../output/seedream/setup02_key.png"},
    {"id": "setup03", "prompt": "...",
     "reference_videos": [{"url": "https://.../setup03.mp4", "duration_s": 5}],
     "omni_reference_task_type": "reference"}
  ]
}
```

Come funziona:

- I campi di uno shot hanno gli stessi nomi dei parametri dell'API unificata. Sono `prompt`,
  `duration` (`-1` oppure 4-30), `resolution`, `aspect_ratio`, `generate_audio`, `watermark`,
  `return_last_frame`, `output_format`, `first_frame` e `last_frame`, `reference_images`
  (fino a 30), `reference_videos` (fino a 10) e `reference_audio` (fino a 10),
  `omni_reference_task_type`, `priority`, `execution_expires_after`, `safety_identifier`,
  `web_search` e `callback_url`. A questi si aggiunge `model`.
- `defaults` vale per tutti gli shot. Uno shot può ridefinire qualsiasi campo, e una lista
  scritta nello shot sostituisce quella di `defaults`.
- Nei prompt `$nome` prende il valore da `variabili`. Così il soggetto dello spot lo cambi in un
  punto solo.
- Le chiavi che iniziano con `_` sono commenti.
- I percorsi relativi partono dalla cartella del manifest.

Prima di spendere qualsiasi cosa, il comando controlla l'intero manifest e ti elenca tutti i
problemi insieme. Le regole sono queste:

- first/last frame e `reference_*` si escludono a vicenda, e `last_frame` richiede `first_frame`;
- i limiti valgono per modello: per la 2.5 la durata va da 4 a 30 s, mentre la 2.0 ha 15 s, al
  massimo 3 video e 9 immagini, e non accetta solo audio;
- ogni video di riferimento dura da 2 a 30 s e il totale non supera 30 s. Indica `duration_s`
  per far controllare queste durate e per affinare la stima;
- `edit` richiede `aspect_ratio: adaptive`, `duration: -1` e un video da 4 a 30 s, mentre `extend`
  richiede `adaptive`;
- un'immagine pesa al massimo 30 MB, ogni lato misura da 300 a 6000 px e il rapporto sta fra 0,4
  e 2,5;
- un video o un audio non può essere un file locale (vedi §6).

```bash
cp pubblicita/seedance/manifest.example.json pubblicita/seedance/manifest.json   # e poi modificalo
python3 -m pubblicita.ephone batch pubblicita/seedance/manifest.json             # stima e si ferma
python3 -m pubblicita.ephone batch pubblicita/seedance/manifest.json --dry-run   # payload esatti
python3 -m pubblicita.ephone batch pubblicita/seedance/manifest.json --yes --max-cost-usd 30
python3 -m pubblicita.ephone batch pubblicita/seedance/manifest.json --only setup03,setup07 --yes
```

Il batch si può rilanciare senza rischi:

- gli shot che hanno già il loro `<id>.mp4` vengono saltati, salvo `--force`;
- se uno shot ha già un task in corso nel ledger, il batch lo riprende invece di pagarlo di nuovo;
- `--concurrency N` (default 3) fissa quanti task restano attivi insieme;
- il polling parte ogni 5 s e rallenta fino a 15 s;
- ogni task ha un timeout di 30 minuti, modificabile con `--timeout-min`.

## 5. File prodotti

| File | Contenuto |
|---|---|
| `pubblicita/output/seedance/<id>.mp4` | il clip, scaricato appena è pronto (gli URL del fornitore durano 24 ore) |
| `pubblicita/output/seedance/<id>_last.png` | l'ultimo frame, se l'hai chiesto con `return_last_frame` |
| `pubblicita/output/seedance/<id>.json` | il sidecar: prompt, task id, parametri, usage, costo stimato ed effettivo, ffprobe (fps, durata, risoluzione) e avvisi |
| `pubblicita/output/seedance/jobs.json` | il ledger di tutti i task (vedi sotto) |
| `pubblicita/output/seedream/<id>.png` | le immagini Seedream, con il loro sidecar e un ledger a parte |

Seedance produce clip a 24 fps, cioè al frame rate del progetto. Se ffprobe trova un frame rate
diverso lo segnala negli avvisi del sidecar, e il montaggio lo conforma a 24 fps.

Il **ledger** viene scritto in tre momenti:

1. prima del submit, con stato `submitting` e il payload senza chiave (le immagini incorporate
   sono riassunte);
2. subito dopo il submit, con task id e stato `queued`, prima di iniziare il polling;
3. alla fine, con stato `downloaded`, file, usage e costo.

Gli stati possibili sono `submitting`, `queued`, `running`, `succeeded`, `downloaded`, `failed`,
`submit_rejected` (nessun addebito) e `submit_uncertain`. Le ripetizioni con `--force` lasciano
traccia in `history`.

## 6. Media di input

- **Immagini.** Puoi passare un file locale, che viene convertito in data URI base64 dopo i
  controlli (BMP, TIFF e simili diventano PNG). Vanno bene anche un URL pubblico, un data URI o
  `asset://ID`.
- **Video e audio.** Servono un URL pubblico HTTPS oppure `asset://ID`. Il gateway non accetta
  video in base64 e un file locale non è raggiungibile dal fornitore. Carica il file su uno storage
  con link pubblico (bucket S3/R2/GCS, release GitHub, CDN) e usa quell'URL.
- **Volti reali.** Seedance non accetta volti reali passati direttamente, quindi questi file vanno
  prima registrati nella libreria asset:

```bash
python3 -m pubblicita.ephone asset upload --url https://storage.example.com/volto.jpg --type image --name protagonista
# -> stampa  asset://<ID>  da usare in first_frame / reference_images / reference_videos
python3 -m pubblicita.ephone asset list
python3 -m pubblicita.ephone asset query --id <ID>
python3 -m pubblicita.ephone asset delete --id <ID>
python3 -m pubblicita.ephone asset validate-session            # verifica di una persona reale
python3 -m pubblicita.ephone asset validate-result --token <byted_token>
python3 -m pubblicita.ephone asset raw --input-json '{"action": "list"}'   # campi non previsti
```

La libreria è gratuita e risponde subito. Ogni asset appartiene all'account che lo ha caricato.

## 7. Dal blockout Blender al clip

Ci sono tre modi per far seguire a ogni clip Seedance il blockout Blender dello stesso setup. Li
elenco in ordine di controllo crescente:

1. **Immagine chiave da Seedream, poi Seedance.** Renderizzi uno still del blockout e lo passi a
   Seedream, che ne fa una versione fotorealistica mantenendo l'inquadratura. Quell'immagine
   diventa il `first_frame` del clip:
   ```bash
   python3 -m pubblicita.ephone image --id setup03_key --ref pubblicita/output/blender/setup03_first.png \
       --prompt "Photorealistic night street, same composition and camera as the reference" --size 2K --yes
   ```
   Poi nel manifest scrivi `"first_frame": "../output/seedream/setup03_key.png"`.
2. **Video di riferimento.** Pubblichi il render del blockout a un URL pubblico e lo usi in
   `reference_videos` con `"omni_reference_task_type": "reference"`. Il modello riprende i
   movimenti di camera e il blocking.
3. **Task `edit`.** Seedance rifà il video del blockout in fotorealistico. Il clip esce lungo
   quanto il video di input, che deve durare da 4 a 30 s. Il prezzo a token è più basso, ma conta
   anche la durata dell'input.

## 8. Quando qualcosa va storto

- **Rete e limiti.** Le richieste di stato e di download si ripetono con backoff sugli errori 429
  e 5xx e sui problemi di rete. Il client rispetta `Retry-After`.
- **Submit dall'esito incerto.** Succede con un timeout in lettura, una connessione caduta dopo
  l'invio o un errore 500, 502 o 504. Qui il client **non ripete**, perché il task potrebbe
  esistere ed essere addebitato. Lo shot resta in `submit_uncertain` e i batch successivi lo
  saltano. Controlla la console ePhone e scegli fra due strade:
  ```bash
  python3 -m pubblicita.ephone resume --assign setup04=task_xxx   # il task esiste: lo colleghi e lo scarichi
  python3 -m pubblicita.ephone batch manifest.json --only setup04 --force --yes   # il task non esiste
  ```
  Il client ripete il submit solo in due casi: la richiesta non è mai partita (connessione
  rifiutata, timeout di connessione) oppure il gateway l'ha respinta con 429 o 503.
- **Processo interrotto o timeout.** Lancia `python3 -m pubblicita.ephone resume`. Riprende i task
  `queued`, `running` e `succeeded` non ancora scaricati, e riscarica gli output cancellati per
  sbaglio finché il task è consultabile (7 giorni; gli URL scadono dopo 24 ore).
- **Risposte di forma inattesa.** La risposta grezza finisce nel ledger (`raw_response`) e il
  comando mostra un errore leggibile.
- **Stato di un task e annullamento.** `status <id-shot|task-id>` (con `--raw` mostra la risposta
  intera) e `cancel <id-shot|task-id>`.

Codici di uscita:

| Codice | Significato |
|---|---|
| 0 | tutto a posto |
| 1 | almeno un task fallito o incerto |
| 2 | validazione fallita o conferma mancante (nessuna chiamata effettuata) |
| 3 | chiave mancante |

## 9. Due formati API

| | `unified` (default) | `native` (`--api native`) |
|---|---|---|
| submit | `POST /v1/task/submit` `{"model", "input": {...}}` | `POST /doubao/api/v3/contents/generations/tasks` (corpo Ark: `content[]` con i ruoli, `ratio`) |
| stato | `GET /v1/task/{id}`: queued / in_progress / completed / failed | `GET .../tasks/{id}`: queued / running / succeeded / failed / cancelled / expired |
| output | `outputs[]` | `content.video_url`, `content.last_frame_url` |
| immagini | task Seedream sullo stesso endpoint | `POST /v1/images/generations` o `/v1/images/edits` (sincrono) |

Il client riduce gli stati di entrambe le famiglie a `queued`, `running`, `succeeded` e `failed`.
Conta come `failed` anche un task annullato o scaduto. Il parser accetta l'involucro
`{"code", "data": ...}` di new-api.

## 10. Da verificare con la chiave vera

Queste cose le ho ricavate dalla documentazione pubblica del gateway, ma senza chiave non le ho
potute provare:

- **Stato unificato.** Non so se `GET /v1/task/{id}` riporti `usage` e l'URL dell'ultimo frame. Se
  mancano, il costo effettivo nel sidecar resta vuoto e fa fede la stima; per l'ultimo frame si
  può usare `--api native`.
- **Annullamento.** Il formato unificato non documenta come annullare un task, quindi `cancel` usa
  sempre il mirror Ark. Bisogna controllare che accetti anche i task id creati con
  `/v1/task/submit`.
- **Libreria asset.** Va confermata la forma esatta delle risposte, cioè dove si trova `data.Id`,
  e se `asset_type` vada scritto in maiuscolo come nello schema (`Image`/`Video`/`Audio`) o in
  minuscolo come nell'esempio della documentazione. Per i casi dubbi c'è `asset raw`.
- **Immagini con `--api native`.** Va verificato che `/v1/images/edits` accetti le immagini di
  riferimento come JSON (URL o data URI) e non solo come multipart.
- **Saldo.** `check` prova anche `/v1/dashboard/billing/subscription`, ma è un tentativo: se il
  gateway non espone quell'endpoint, l'informazione semplicemente non compare.

## 11. Uso da Python

```python
from pubblicita.ephone import ClientEphone, Esecutore, carica_configurazione, carica_manifest

conf = carica_configurazione()
client = ClientEphone(conf.richiedi_chiave(), conf.url_base, api="unified")
manifest = carica_manifest("pubblicita/seedance/manifest.json")
esecutore = Esecutore(client, concorrenza=3)
piano = esecutore.pianifica(manifest.richieste)
print(sum(p.richiesta.stima().usd for p in piano if p.azione == "invia"))
esiti = esecutore.esegui(piano)
```
