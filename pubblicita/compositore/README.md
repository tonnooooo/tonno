# Compositore

Impaginazione verticale 1080×1920 a 24 fps dello spot: sfondo chiaro con linee ondulate animate,
intestazione (marchio + titolo animati), due pannelli 16:9 con etichetta e barra di avanzamento.

```bash
# due video qualsiasi nei pannelli (scalati «cover»)
python3 -m pubblicita.compositore --top top.mp4 --bottom bottom.mp4 --out spot.mp4 \
    [--audio musica.wav | --audio-from-bottom] [--config mio.json] [--duration 14]
# anteprima rapida: solo alcuni frame in PNG
python3 -m pubblicita.compositore --top top.mp4 --bottom bottom.mp4 --out prova.png --still 0.3 2.6
# tutto in uno: EDL → montaggio → impaginazione
python3 -m pubblicita.compositore spot --edl edl.json --out spot.mp4 [--config mio.json]
```

Uscita: H.264 (libx264, yuv420p, CRF 16, preset medium, BT.709), AAC 192 kbit/s, `+faststart`.
Audio: tagliato o allungato alla durata con fade-out finale (`audio.fade_out_s`); senza audio viene
aggiunta una traccia muta (`--no-audio-track` per ometterla). La durata di default è quella del
video inferiore; il pannello più corto tiene l'ultima posa. Lo spot da 14 s si compone in ~20 s
su 4 CPU; lo stesso input produce lo stesso file (bit per bit).

## Layout

Il layout di default è `pubblicita/config/layout.json`, misurato sul reel di riferimento.
`--config` accetta un JSON con le sole chiavi da cambiare, fuso sopra il default:

```json
{"header": {"title": {"text": "Opus 5.5"}},
 "panels": {
   "top":    {"label": {"items": [{"icon": "cubo"}, {"text": "Blender"}]}},
   "bottom": {"label": {"items": [{"icon": "mia_icona.png"}, {"text": "Seedance 2.5"}]}}}}
```

- Etichette: elementi in fila (`icon` o `text`), larghezza della pillola calcolata dal contenuto;
  per elemento si possono dare `gap_before`, `color`, `opacity`, `size`, `tracking`, `dy`.
  Icone procedurali: `cubo`, `spark`, `play`, `dot`; oppure un PNG (anche `{"src": "x.png", "radius": 7}`).
- Marchio: quadrato + asterisco disegnati per SDF (12 raggi a capsula rastremata, misure in
  frazioni del lato); colori e geometria nel config.
- Animazioni (`header.animation`): curve `cubic-bezier` per proprietà (opacità, scala, rotazione,
  spostamento, sfocatura) del marchio e di ogni parola del titolo, più il riflesso («shimmer»)
  che attraversa il titolo a 1,8 s. Valori ricavati frame per frame dal riferimento.
- Sfondo (`background`): tinta a gradiente (griglia B-spline 6×10) e 15 linee (5 profili ripetuti
  ogni 640 px), ciascuna una Catmull-Rom con punti ogni 72 px che oscillano con periodo proprio e
  seconda armonica. Deterministico e continuo anche oltre i 14 s.
- Pannelli: box `[12, 336, 1056, 594]` e `[12, 1070, 1056, 594]`, raggio 27, ombra
  `0 14px σ18 rgba(0,0,0,0.13)`, barra 6 px: riempimento = frame / (frame totali − 1).

## Misure principali (riferimento → config)

| elemento | valore |
|---|---|
| sfondo | ≈ (241, 243, 240) con tinta ±4 livelli |
| marchio | x 492,9–587,5, y 108,0–203,1, colore (215, 118, 86), angoli vivi |
| titolo | Hanken Grotesk Bold 71,4 px, tracking −3, baseline 281,25, colore (25, 34, 29) |
| etichetta | pillola h 56, raggio 15, a 20 px dal bordo del pannello, riempimento (13, 19, 21) al 78%, bordo bianco 7,5%, testo Hanken Grotesk Bold 27,5 px |
| barre | alte 6 px, binario (240, 240, 240) al 37%, riempimento (234, 132, 27) sopra e (18, 168, 137) sotto |

Font: `fonts/` (Hanken Grotesk, SIL OFL 1.1), scelto confrontando 60 sans OFL sul titolo.
