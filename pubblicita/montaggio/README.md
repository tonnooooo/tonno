# Montaggio

Dall'EDL (lista dei tagli, a tempo di musica) alle due tracce sincronizzate dei pannelli:
`top.mp4` (blockout Blender) e `bottom.mp4` (render finale Seedance).

```bash
python3 -m pubblicita.montaggio render  --edl edl.json --out-dir pubblicita/output/montaggio
python3 -m pubblicita.montaggio check   --edl edl.json [--no-media]      # valida e stampa i tagli
python3 -m pubblicita.montaggio beats   --bpm 115 --pattern "1,0.5,0.5,1/3"
python3 -m pubblicita.montaggio analyze --video spot.mp4 --crop 1056:594:12:1070
```

`render` scrive in `--out-dir`: `top.mp4`, `bottom.mp4` (H.264 CRF 10, 24 fps, muti, risoluzione
`size` dell'EDL, scala «cover» + ritaglio centrale), `timeline.json` (confini di ogni shot in frame
e secondi, sorgenti risolte) e `audio.wav` se l'EDL ha una traccia audio (ritagliata da
`offset_s`, allungata con silenzio fino alla durata esatta; offset negativo = silenzio in testa).

## EDL

```json
{"fps": 24, "bpm": 115, "size": [1920, 1080],
 "audio": {"src": null, "offset_s": 0},
 "shots": [
   {"id": "s01", "frames": 8,
    "top":    {"src": "pubblicita/output/blender/setup01.mp4", "in": 0, "speed": 1.0},
    "bottom": {"src": "pubblicita/output/seedance/setup01.mp4", "in": 0, "speed": 1.0},
    "note": ""},
   {"id": "s02", "beats": 0.5, "top": {"...": "..."}, "bottom": {"...": "..."}}
 ]}
```

- Durata di uno shot: `frames` (intero) **oppure** `beats` (al `bpm` dell'EDL). Il confine di ogni
  taglio è `round(posizione_cumulativa)`, con la posizione in battiti convertita una sola volta:
  `round(battiti_cumulativi × 60 / bpm × fps)`. Nessuna deriva, anche mescolando frame e battiti.
- Top e bottom di uno shot durano sempre uguale (la durata è dello shot).
- `in`: indice di frame a 24 fps nella sorgente già conformata a 24 fps (clip a 25/30/60 fps vanno bene).
- `speed`: > 1 accelera, < 1 rallenta; la sorgente consumata è circa `frames × speed`.
- Sorgente: `src` (video o immagine fissa) oppure `{"color": "#202428"}` come segnaposto.
- Percorsi relativi: prima rispetto alla cartella dell'EDL, poi alla cartella corrente.
- Errori chiari, con lo shot indicato: sorgente mancante, `in` + durata oltre la fine del clip,
  `top`/`bottom` mancanti, `frames` e `beats` insieme, fps diversi da 24, id duplicati.

`edl.example.json` mostra 26 tagli che riusano 10 setup (stesso `in` sopra e sotto: il blockout e il
clip Seedance sono allineati frame per frame), come nel riferimento.

## Ritmo del riferimento

`ritmo_riferimento.json`: le 26 durate in frame del reel di riferimento (somma 336 = 14,0 s),
rilevate con `analyze` sul pannello inferiore e coincidenti con i tagli misurati. Il riferimento non
è tagliato esattamente sui battiti a 115 bpm: per rifarlo al frame si usano `frames`.
