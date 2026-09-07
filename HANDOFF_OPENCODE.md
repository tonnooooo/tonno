# Briefing operativo per l'agente che ha accesso alla VM

Questo documento è scritto per un agente (OpenCode o equivalente) che ha SSH e
accesso ai file sulla VM Vast.ai dove gira la chat. Chi lo ha scritto ha
analizzato i sintomi e ha già implementato e testato le correzioni in questo
stesso repository, ma **non** ha accesso alla macchina.

Obiettivo: eliminare i bug per cui la chat, dopo un po' di utilizzo, non
compatta più il contesto e in alcuni casi diventa inutilizzabile.

Stack dichiarato dall'utente: KoboldCpp + WebUI, modello locale da ~27-30B,
agenti di ricerca/OSINT aggiunti in un secondo momento.

---

## Fase 1 — Raccolta (da fare per prima, prima di toccare qualsiasi cosa)

```bash
# 1. Con quale finestra di contesto è REALMENTE avviato il motore
ps aux | grep -iE 'kobold|llama|vllm|ollama' | grep -v grep

# 2. Cosa dichiara il motore di supportare
curl -s http://127.0.0.1:5001/api/v1/model
curl -s http://127.0.0.1:5001/api/extra/true_max_context_length

# 3. Dove è salvata la cronologia
find /workspace -maxdepth 4 \( -name '*.json' -o -name '*.db' -o -name '*.sqlite*' \) -size +1k

# 4. Dove il codice taglia il contesto
grep -rnE 'contextsize|context_size|max_context|max_length|truncat|compact|summar|\.pop\(0\)|del .*(messages|history)|shift\(\)|splice\(' \
     /workspace --include='*.py' --include='*.js' --include='*.ts'
```

**Il primo confronto da fare** è tra il `--contextsize` con cui KoboldCpp è
avviato e il valore che la WebUI usa per decidere quando tagliare. Se la UI
crede di avere più finestra di quella reale, il motore tronca per conto suo,
in silenzio e dalla testa: la conversazione perde il system prompt e sembra
«impazzita». È la causa più frequente e la più facile da escludere.

---

## Fase 2 — I sei difetti da cercare, in ordine di probabilità

### 1. La compattazione cancella invece di archiviare
Sintomo riferito: «dopo due compattazioni elimina la chat».

Da cercare: `messages.pop(0)`, `messages = messages[n:]`, `del messages[...]`,
`history.shift()`, `DELETE FROM messages`.

Il meccanismo: la prima passata sostituisce N messaggi con un riassunto. La
seconda ri-seleziona anche il riassunto, lo rimuove e ciò che restava sparisce.

Correzione: non rimuovere. Marcare i messaggi come archiviati e tenerli. Il
riassunto è un record nuovo, inserito nella posizione cronologica del blocco
che sostituisce (non in coda: altrimenti l'ordine si scombina).

### 2. Il riassunto viene chiesto in una sola richiesta
Sintomo: «non riesce a compattare».

Si manda l'intera cronologia da riassumere — cioè proprio ciò che è troppo
lungo. Il motore risponde con un errore di contesto e si entra in un ciclo di
fallimenti.

Correzione: riassunto map-reduce. Blocchi che stanno nel budget, un riassunto
per blocco, poi una fusione finale.

### 3. La compattazione non è transazionale
Se la richiesta di riassunto fallisce a metà, i messaggi sono già stati
rimossi: la conversazione resta mutilata in modo permanente.

Correzione: prima si ottiene il riassunto, poi — in una sola transazione — si
inserisce e si archivia. Se il riassunto è vuoto o la chiamata fallisce, non
si tocca niente.

### 4. Il taglio spezza le coppie tool
Sintomo: dopo un po' ogni richiesta torna 400 e la chat sembra morta per
sempre.

Se un messaggio `assistant` con `tool_calls` viene rimosso ma i relativi
risultati `tool` restano (o viceversa), il payload non è più valido per
un'API OpenAI-compatible. E resta scritto a DB, quindi si ripresenta a ogni
richiesta successiva.

Correzione: il punto di taglio non deve mai cadere dentro un gruppo
`assistant(tool_calls) → tool...`; e prima di inviare, una passata di
sanificazione che scarta i risultati orfani e le tool_call senza risposta.
Va fatta **sempre**, non solo quando si compatta: è la garanzia che uno stato
sporco a monte non blocchi la chat in modo permanente.

### 5. L'output degli agenti OSINT entra intero nel contesto
Sintomo: «da quando ho aggiunto gli agenti va peggio».

Una pagina web sono facilmente 30-50k token. Basta un risultato per saturare
la finestra.

Correzione: tetto sui byte scaricati, output troncato a una soglia fissa
prima di entrare nel contesto, timeout per singolo strumento, limite al
numero di iterazioni di tool per turno.

### 6. Cronologia su file JSON riscritto a ogni turno
Sintomo: chat che sparisce o non si riapre dopo un riavvio.

Una riscrittura interrotta (kill, riavvio, due richieste in parallelo) lascia
il file troncato e non più parsabile.

Correzione: SQLite in WAL con transazioni, oppure — se si vuole restare su
file — scrittura atomica (file temporaneo + `os.replace`) e un lock.

---

## Fase 3 — Verifica

Non basta provare con tre messaggi: questi bug si manifestano dopo decine di
turni. In questo repository c'è `scripts/stress_test.py`, che simula ore di
conversazione contro un backend che sbaglia apposta (errori 5xx, superamento
di contesto, riassunti vuoti, output di tool enormi, JSON malformato,
richieste in parallelo) e verifica dopo ogni turno che:

- nessuna conversazione resti senza messaggi;
- nessun messaggio venga perso;
- l'ordine resti monotono e senza duplicati;
- non esistano tool_call senza risultato, né salvate né nel payload;
- il payload stia sempre nel budget di contesto;
- il database resti integro.

Va adattato al codice della VM e lanciato dopo ogni modifica.

---

## Implementazione di riferimento

In questo repository c'è un backend già scritto e testato con tutte le
correzioni sopra (46 test di regressione, oltre 5000 turni di soak senza
violazioni). I moduli sono trapiantabili singolarmente:

| File | Cosa risolve |
|---|---|
| `app/compaction.py` | difetti 1, 2, 3, 4 — archiviazione, map-reduce, transazione, sanificazione |
| `app/db.py` | difetto 6 — persistenza transazionale |
| `app/agents/tools.py`, `app/agents/loop.py` | difetto 5 — output limitato, invarianti sui tool |
| `app/llm.py` | timeout, retry, circuit breaker |
| `app/tokens.py` | conteggio token con margine |

La funzione da leggere per prima è `compact()` in `app/compaction.py`, e
subito dopo `_sanitize_tool_pairs()` — quest'ultima è la rete di sicurezza
che impedisce che uno stato sporco renda la chat inutilizzabile.

---

## Nota di coordinamento

Se due agenti lavorano sullo stesso progetto, non devono modificare gli
stessi file nello stesso momento: le scritture si sovrascrivono a vicenda
senza avviso. Meglio dividersi per file, o lavorare uno alla volta.
