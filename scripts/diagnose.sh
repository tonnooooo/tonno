#!/usr/bin/env bash
# Raccoglie lo stato della VM (Vast.ai) e dell'applicazione di chat in un
# unico file di testo, da rileggere o incollare per l'analisi.
#
# Uso sulla VM:
#     bash scripts/diagnose.sh > diagnostica_$(date +%F_%H%M).txt 2>&1
#
# Non stampa segreti: le chiavi API vengono mascherate.

set -uo pipefail

sep() { printf '\n===== %s =====\n' "$1"; }
have() { command -v "$1" >/dev/null 2>&1; }

echo "DIAGNOSTICA CHAT — $(date -Is)"

sep "SISTEMA"
uname -a
echo "uptime: $(uptime -p 2>/dev/null || uptime)"
echo "CPU: $(nproc 2>/dev/null) core"
free -h 2>/dev/null | head -3
df -h / /root /workspace 2>/dev/null | grep -v '^Filesystem.*$' | head -8

sep "GPU"
if have nvidia-smi; then
  nvidia-smi --query-gpu=name,memory.total,memory.used,utilization.gpu,temperature.gpu \
             --format=csv 2>/dev/null || nvidia-smi
else
  echo "nvidia-smi non disponibile"
fi

sep "PROCESSI RILEVANTI (python / uvicorn / vllm / llama)"
ps aux --sort=-%mem 2>/dev/null | head -1
ps aux 2>/dev/null | grep -E 'uvicorn|gunicorn|vllm|llama|ollama|python' | grep -v grep | head -20

sep "PORTE IN ASCOLTO"
if have ss; then ss -lntp 2>/dev/null | head -25
elif have netstat; then netstat -lntp 2>/dev/null | head -25
else echo "ss/netstat non disponibili"; fi

sep "AMBIENTE (segreti mascherati)"
env | grep -iE '^(LLM_|MODEL|CONTEXT_|COMPACTION_|KEEP_|MIN_MESSAGES|MAX_SUMMARY|SUMMARY_|REQUEST_TIMEOUT|DB_PATH|SEARXNG|TOOL_|APP_|PORT|HOST|CUDA_|HF_|VLLM|OLLAMA)' \
    | sed -E 's/(KEY|TOKEN|SECRET|PASSWORD)=.*/\1=***MASCHERATO***/I' | sort

sep "PYTHON E DIPENDENZE"
python3 -V 2>&1
python3 -m pip list 2>/dev/null | grep -iE 'fastapi|uvicorn|httpx|pydantic|vllm|torch|transformers|tiktoken|sqlalchemy|starlette' || echo "pip list non disponibile"

sep "STRUTTURA DEL PROGETTO"
ROOT="${1:-$(pwd)}"
echo "radice: $ROOT"
find "$ROOT" -maxdepth 3 \( -name .git -o -name node_modules -o -name __pycache__ -o -name '.venv' \) -prune -o \
     -type f \( -name '*.py' -o -name '*.toml' -o -name '*.env*' -o -name '*.json' -o -name '*.yml' -o -name '*.yaml' \) \
     -printf '%10s  %p\n' 2>/dev/null | sort -k2 | head -60

sep "RIGHE DI CODICE PER FILE PYTHON"
find "$ROOT" -maxdepth 4 -name '*.py' -not -path '*/.venv/*' -not -path '*/__pycache__/*' \
     -exec wc -l {} + 2>/dev/null | sort -rn | head -25

sep "PUNTI SOSPETTI NEL CODICE (dove nascono i bug di compattazione)"
grep -rnE 'DELETE FROM|\.pop\(0\)|del .*messages|messages\s*=\s*messages\[|truncate|compact|summar' \
     "$ROOT" --include='*.py' --exclude-dir=.venv --exclude-dir=__pycache__ 2>/dev/null | head -40

sep "STATO DEL DATABASE"
DB="${DB_PATH:-}"
if [ -z "$DB" ]; then DB=$(find "$ROOT" -maxdepth 3 -name '*.db' -o -maxdepth 3 -name '*.sqlite*' 2>/dev/null | head -1); fi
if [ -n "$DB" ] && [ -f "$DB" ]; then
  echo "file: $DB ($(du -h "$DB" | cut -f1))"
  if have sqlite3; then
    echo "--- integrita' ---"; sqlite3 "$DB" "PRAGMA integrity_check;" 2>&1 | head -5
    echo "--- journal mode ---"; sqlite3 "$DB" "PRAGMA journal_mode;" 2>&1
    echo "--- tabelle ---"; sqlite3 "$DB" ".tables" 2>&1
    echo "--- conteggi ---"
    for t in $(sqlite3 "$DB" "SELECT name FROM sqlite_master WHERE type='table';" 2>/dev/null); do
      printf '%-24s %s\n' "$t" "$(sqlite3 "$DB" "SELECT COUNT(*) FROM \"$t\";" 2>/dev/null)"
    done
  else
    echo "sqlite3 non installato (apt-get install -y sqlite3 per i dettagli)"
  fi
else
  echo "nessun database SQLite trovato. Se la cronologia e' su file JSON, e' la causa"
  echo "piu' probabile della corruzione: vedi la sezione FILE JSON qui sotto."
fi

sep "FILE JSON DI CRONOLOGIA (candidati alla corruzione)"
find "$ROOT" -maxdepth 4 \( -name 'chat*.json' -o -name 'conversation*.json' -o -name 'history*.json' -o -name 'sessions*.json' \) \
     -not -path '*/node_modules/*' 2>/dev/null | head -10 | while read -r f; do
  printf '%s (%s) -> ' "$f" "$(du -h "$f" | cut -f1)"
  python3 -c "import json,sys; json.load(open(sys.argv[1])); print('JSON valido')" "$f" 2>&1 | tail -1
done

sep "TEST DI RAGGIUNGIBILITA' DEL BACKEND LLM"
BASE="${LLM_BASE_URL:-http://127.0.0.1:8000/v1}"
echo "provo $BASE/models"
curl -sS -m 10 -o /tmp/_models.json -w 'HTTP %{http_code} in %{time_total}s\n' "$BASE/models" 2>&1
head -c 600 /tmp/_models.json 2>/dev/null; echo

sep "TEST DELL'API DELLA CHAT"
APP="${APP_URL:-http://127.0.0.1:8080}"
for path in /health /health/deep; do
  echo "--- $APP$path ---"
  curl -sS -m 10 -w '\nHTTP %{http_code}\n' "$APP$path" 2>&1 | head -30
done

sep "LOG RECENTI"
for f in /var/log/chat.log ./chat.log ./app.log ./logs/app.log nohup.out; do
  [ -f "$f" ] && { echo "--- $f (ultime 60 righe) ---"; tail -60 "$f"; }
done
if have journalctl; then
  echo "--- journalctl ultimi errori ---"
  journalctl -n 60 --no-pager -p err 2>/dev/null | tail -40
fi

sep "ERRORI RICORRENTI NEI LOG"
grep -rhoE 'context length|maximum context|CUDA out of memory|OutOfMemory|database is locked|Traceback|400 Bad Request|500 Internal' \
     /var/log/*.log ./*.log ./logs/*.log 2>/dev/null | sort | uniq -c | sort -rn | head -20

echo
echo "FINE DIAGNOSTICA — $(date -Is)"
