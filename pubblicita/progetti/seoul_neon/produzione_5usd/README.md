# Produzione "Seoul neon" con 5 $ di budget

Versione ridotta dello spot: 4 clip Seedance 2.5 (720p, 24 fps, muti) tagliati e
riordinati in 26 shot, con il blockout Blender sopra e il marchio Kleo AI sull'etichetta.
Nessuna musica.

| Clip | Durata | Contenuto | Shot che lo usano |
|---|---|---|---|
| `c1_strada` | 5 s | ragazza con ombrello accanto alla R34, Gangnam | 7, 11, 14, 15, 16, 18, 20, 21, 23 |
| `c2_torre` | 4 s | ragazza di spalle, N Seoul Tower | 5, 6, 22, 25 |
| `c3_hanok` | 4 s | stanza hanok, ragazza seduta | 2, 4, 8, 9, 17, 26 |
| `c4_auto` | 4 s | orbita attorno alla R34 | 1, 3, 10, 12, 13, 19, 24 |

- Immagini: Seedream 5.0 Pro (riferimento ragazza + 3 keyframe, 1920x1080 / 1080x1920), il quarto
  keyframe e' la prova dell'auto.
- Clip: `doubao-seedance-2-5-260628`, modalita' primo fotogramma, `aspect_ratio: adaptive`
  (con il primo fotogramma l'API rifiuta `16:9`), 720p.
- Spesa stimata dai token restituiti: circa 3,6 $ (non e' stato letto il saldo reale).
- `edl.json`: montaggio dei 26 shot (durate del riferimento, somma 336 frame); `assegnazione_shot.json`:
  shot -> clip e frame di partenza; `clip_seedance.json`: prompt e parametri dei clip.
- I blockout Blender sono in `../blockout/`, resa 704x396, 6 campioni: bozza fedele allo stile ma
  non allineata inquadratura per inquadratura ai clip.

Ricomporre:

```bash
python3 -m pubblicita.compositore spot --edl pubblicita/progetti/seoul_neon/produzione_5usd/edl.json \
    --config pubblicita/config/kleo.json --out pubblicita/output/spot.mp4
```

(I percorsi dell'EDL puntano a `pubblicita/output/seedance/` e `pubblicita/output/blender/`, ignorate da git.)
