# Backend chat — compattazione sicura, agenti di ricerca, test di tenuta

Backend FastAPI per un modello servito in locale con API OpenAI-compatible
(vLLM, llama.cpp, TGI, Ollama) su una VM GPU tipo Vast.ai.

È scritto attorno a un obiettivo preciso: **una conversazione non si deve mai
rompere in modo permanente**. Nessuna cancellazione distruttiva, ogni
compattazione è una transazione, e il payload verso il modello è sempre
strutturalmente valido anche se lo stato a monte è sporco.

---

## I sintomi e la loro causa

| Sintomo | Causa tecnica | Dove è risolto |
|---|---|---|
| «dopo due compattazioni elimina la chat e non funziona più» | la compattazione **cancellava** i messaggi sostituendoli con un riassunto; alla passata successiva veniva riassunto il riassunto e non restava niente | `app/compaction.py` — i messaggi si **archiviano** (`archived_at`), mai si cancellano; il riassunto è un record nuovo, inserito nel punto cronologico giusto |
| «la chat non riesce a compattare bene» | si mandava tutta la cronologia in **una sola** richiesta di riassunto, cioè proprio la cosa troppo lunga per la finestra → 400 → ciclo di fallimenti | `summarize_block()` — riassunto **map-reduce** a blocchi, ognuno entro `MAX_SUMMARY_INPUT_TOKENS` |
| dopo un po' ogni richiesta torna 400 e la chat sembra morta | il taglio spezzava una coppia `assistant(tool_calls)` → `tool`, payload non valido per l'API | `_sanitize_tool_pairs()` + confine di taglio sicuro in `select_range()` |
| chat che sparisce dopo un riavvio | cronologia su file JSON riscritto a ogni turno: si tronca al primo crash o alla prima scrittura concorrente | `app/db.py` — SQLite in **WAL**, transazioni esplicite, `seq` monotono con vincolo `UNIQUE` |
| la chat «si pianta» e non risponde più | nessun timeout sulle chiamate al modello: una richiesta appesa blocca il worker | `app/llm.py` — timeout espliciti, retry con backoff sui soli errori transitori, **circuit breaker** |
| tutto peggiora da quando ci sono gli agenti OSINT | l'output di un tool (una pagina web = decine di migliaia di token) finiva **intero** nel contesto | `app/agents/tools.py` — tetto sui byte scaricati, output troncato, timeout per tool |
| ordine dei messaggi che si scombina | doppio invio dal browser / richieste in parallelo sulla stessa chat | lock **per conversazione** in `app/api.py` |
| errore generico e schermata vuota nel frontend | eccezioni non gestite → 500 muto | handler globali in `app/main.py`, errori JSON con `error_kind` e `retryable` |

---

## Installazione sulla VM

```bash
git clone <questo-repo> chat && cd chat
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env      # e poi si modifica
```

Nel `.env` **la cosa più importante** è che `CONTEXT_WINDOW` combaci con il
`--max-model-len` con cui è avviato vLLM. Se qui c'è scritto 32768 e vLLM è
partito con 8192, la chat si romperà regolarmente e in modo inspiegabile.

```bash
# controllo rapido di com'è avviato il server del modello
ps aux | grep -E 'vllm|llama' | grep -v grep
curl -s http://127.0.0.1:8000/v1/models | head -c 400
```

Avvio:

```bash
set -a && source .env && set +a
uvicorn app.main:app --host 0.0.0.0 --port 8080 --workers 1
```

**Un solo worker.** Con SQLite e i lock applicativi per conversazione, più
processi che scrivono lo stesso file sono un'altra strada verso la chat
corrotta. Il collo di bottiglia è la GPU, non il Python: i thread bastano.

Verifica immediata:

```bash
curl -s localhost:8080/health/deep | python3 -m json.tool
```

Se `problems` non è vuoto, quello che c'è scritto lì è il motivo per cui la
chat si romperà più avanti. Va sistemato prima di usarla.

---

## Endpoint utili per capire cosa sta succedendo

| Endpoint | A cosa serve |
|---|---|
| `GET /health/deep` | integrità DB, raggiungibilità del modello, errori di configurazione |
| `GET /conversations/{id}/stats` | token attuali, soglia di compattazione, storico di **tutte** le compattazioni con esito e motivo |
| `GET /conversations/{id}/context` | il payload **esatto** che verrebbe mandato al modello. Se il modello «ha perso il filo», si guarda qui: se manca qualcosa il problema è la compattazione, non il modello |
| `POST /conversations/{id}/compact` | compattazione manuale |
| `POST /conversations/{id}/compact/undo` | **annulla** l'ultima compattazione e ripristina i messaggi archiviati |
| `POST /conversations/{id}/restore` | ripristina una chat cancellata (la cancellazione è solo logica) |

---

## Test

```bash
pip install pytest pytest-asyncio
python3 -m pytest tests/ -q
```

46 test, di cui uno per ogni sintomo dell'elenco sopra: sono test di
regressione, servono a impedire che quei bug tornino.

### Test di tenuta (soak)

```bash
python3 scripts/stress_test.py --turns 1200 --conversations 12 --seed 42
```

Simula ore di conversazione in una ventina di secondi contro un backend LLM
**avverso** (che sbaglia apposta: errori 504, `context length exceeded`,
riassunti vuoti, output di tool da 40.000 parole, JSON malformato negli
argomenti, raffiche di richieste in parallelo sulla stessa chat) e dopo ogni
turno verifica le invarianti:

- nessuna conversazione resta senza messaggi;
- nessun messaggio viene perso;
- l'ordine (`seq`) resta monotono e senza duplicati;
- nessuna `tool_call` senza risultato, né a DB né nel payload;
- il payload sta **sempre** nel budget di contesto;
- SQLite resta integro.

Esce con codice 1 e l'elenco dei problemi se un'invariante salta. È lo
strumento da rilanciare dopo ogni modifica.

---

## Diagnostica della VM

```bash
bash scripts/diagnose.sh > diagnostica_$(date +%F_%H%M).txt 2>&1
```

Raccoglie GPU, processi, porte, dipendenze, struttura del progetto, stato e
integrità del database, validità di eventuali file JSON di cronologia,
raggiungibilità del backend LLM ed errori ricorrenti nei log. Le chiavi API
vengono mascherate.

---

## Mandare il proprio codice per l'analisi

Se l'assistente non puo' collegarsi alla VM (rete chiusa, niente SSH), invece
di condividere accessi si manda il codice:

```bash
cd /percorso/del/progetto
bash scripts/impacchetta_progetto.sh > progetto.txt
```

Produce un unico file di testo con l'albero dei file e il contenuto dei
sorgenti, escludendo pesi del modello, ambienti virtuali e cache, e
**mascherando** chiavi API, token e password. Prima di inviarlo conviene
comunque scorrerlo: il mascheramento e' euristico, non infallibile.

In alternativa, se sulla VM c'e' git configurato, il modo piu' comodo e'
pubblicare lo stato attuale su un branch dedicato:

```bash
cd /percorso/del/progetto
git init 2>/dev/null; git add -A && git commit -m "stato attuale della VM"
git remote add origin https://github.com/<utente>/<repo> 2>/dev/null
git push origin HEAD:refs/heads/stato-vm
```

Attenzione a non pubblicare il file `.env`: va aggiunto a `.gitignore` prima
del commit.

---

## Note sul modello

`LLM_MODEL` e `CONTEXT_WINDOW` vanno allineati al modello effettivamente
caricato. Per un modello da ~27-30B in quantizzazione su una singola GPU,
conviene partire prudenti (`CONTEXT_WINDOW=16384` o `32768`) e alzare solo
dopo aver verificato che vLLM regga senza andare in `CUDA out of memory`: una
finestra dichiarata più larga di quella realmente servita produce esattamente
il sintomo «dopo un po' la chat si buga».
