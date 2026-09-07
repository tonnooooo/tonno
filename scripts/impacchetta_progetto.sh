#!/usr/bin/env bash
# Impacchetta il codice del progetto in UN file di testo, da allegare in chat.
#
# Serve quando l'assistente non puo' collegarsi alla VM: invece di dare accessi,
# si manda il codice. Esclude pesi del modello, ambienti virtuali e cache, e
# MASCHERA i segreti (chiavi API, token, password) prima di scrivere.
#
# Uso sulla VM, dentro la cartella del progetto:
#     bash impacchetta_progetto.sh > progetto.txt
#     # poi si allega progetto.txt in chat
#
# Con un limite diverso (default 800 KB, oltre si tronca):
#     LIMITE_KB=1500 bash impacchetta_progetto.sh > progetto.txt

set -uo pipefail

RADICE="${1:-$(pwd)}"
LIMITE_KB="${LIMITE_KB:-800}"
LIMITE_BYTE=$((LIMITE_KB * 1024))
MAX_FILE_BYTE="${MAX_FILE_BYTE:-120000}"   # oltre, il singolo file viene troncato

# Estensioni da includere: codice e configurazione, niente dati né binari.
INCLUDI=( -name '*.py' -o -name '*.js' -o -name '*.ts' -o -name '*.jsx' -o -name '*.tsx'
          -o -name '*.html' -o -name '*.css' -o -name '*.sh' -o -name '*.toml'
          -o -name '*.yaml' -o -name '*.yml' -o -name '*.ini' -o -name '*.cfg'
          -o -name '*.json' -o -name '*.md' -o -name 'Dockerfile*' -o -name '*.service'
          -o -name 'requirements*.txt' -o -name '.env.example' )

ESCLUDI_DIR=( -name .git -o -name node_modules -o -name __pycache__ -o -name '.venv'
              -o -name venv -o -name '.mypy_cache' -o -name '.pytest_cache'
              -o -name dist -o -name build -o -name 'models' -o -name 'weights'
              -o -name '.cache' -o -name 'huggingface' )

mascera() {
  # Sostituisce i valori che sembrano segreti. Non e' infallibile: prima di
  # inviare, una scorsa al file conviene sempre.
  sed -E \
    -e 's/(api[_-]?key|apikey|token|secret|password|passwd|bearer|authorization)([\"'"'"']?\s*[:=]\s*[\"'"'"']?)[A-Za-z0-9._\-]{8,}/\1\2***MASCHERATO***/Ig' \
    -e 's/\b(sk-|hf_|ghp_|gho_|github_pat_)[A-Za-z0-9._\-]{10,}/\1***MASCHERATO***/g' \
    -e 's/\b[a-f0-9]{48,}\b/***MASCHERATO_HEX***/g'
}

printf '# PACCHETTO PROGETTO — %s\n' "$(date -Is)"
printf '# radice: %s\n' "$RADICE"
printf '# NOTA: i valori che sembravano segreti sono stati mascherati.\n\n'

printf '===== ALBERO DEI FILE =====\n'
find "$RADICE" \( "${ESCLUDI_DIR[@]}" \) -prune -o -type f -print 2>/dev/null \
  | sed "s|^$RADICE/||" | sort | head -400
printf '\n'

printf '===== DIMENSIONI (i 30 file di codice piu grandi) =====\n'
find "$RADICE" \( "${ESCLUDI_DIR[@]}" \) -prune -o -type f \( "${INCLUDI[@]}" \) -printf '%10s  %P\n' 2>/dev/null \
  | sort -rn | head -30
printf '\n'

TOTALE=0
SALTATI=0
while IFS= read -r f; do
  REL="${f#"$RADICE"/}"
  DIM=$(stat -c%s "$f" 2>/dev/null || echo 0)
  if [ "$TOTALE" -ge "$LIMITE_BYTE" ]; then
    SALTATI=$((SALTATI + 1))
    continue
  fi
  printf '\n===== FILE: %s (%s byte) =====\n' "$REL" "$DIM"
  if [ "$DIM" -gt "$MAX_FILE_BYTE" ]; then
    head -c "$MAX_FILE_BYTE" "$f" | mascera
    printf '\n[...file troncato, %s byte omessi...]\n' "$((DIM - MAX_FILE_BYTE))"
    TOTALE=$((TOTALE + MAX_FILE_BYTE))
  else
    mascera < "$f"
    TOTALE=$((TOTALE + DIM))
  fi
done < <(find "$RADICE" \( "${ESCLUDI_DIR[@]}" \) -prune -o -type f \( "${INCLUDI[@]}" \) -print 2>/dev/null | sort)

printf '\n===== FINE PACCHETTO =====\n'
printf '# byte inclusi: %s (limite %s KB)\n' "$TOTALE" "$LIMITE_KB"
[ "$SALTATI" -gt 0 ] && printf '# ATTENZIONE: %s file saltati per il limite. Rilancia con LIMITE_KB piu alto.\n' "$SALTATI"
exit 0
