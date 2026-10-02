# Spec degli shot blockout (pannello «Blender»)

Una spec JSON descrive **un** shot del pannello superiore: scena, luci, animazioni e
camera. `build_shot.py` la trasforma in un mp4 H.264 a 24 fps senza audio, nello stile
del riferimento: blockout pulito senza texture, manichini avorio lucidi con pochi
accenti neri, auto squadrate low-poly, pannelli emissivi pastello, pavimenti riflettenti.
Tutto si ottiene combinando prefab e primitive nel JSON: **non serve scrivere Python**.

## Comandi

```bash
# validazione (senza Blender, istantanea)
python3 -m pubblicita.blender.spec pubblicita/blender/esempi/*.json

# still per l'allineamento rapido (PNG; con .mp4 in --out scrive lo stesso nome .png)
blender -b --factory-startup --python pubblicita/blender/build_shot.py -- \
    --spec pubblicita/blender/esempi/strada_notte.json --out pubblicita/output/blender/strada.png --still 0

# clip completa (default 1280x720, campioni della spec)
blender -b --factory-startup --python pubblicita/blender/build_shot.py -- \
    --spec pubblicita/blender/esempi/strada_notte.json --out pubblicita/output/blender/strada.mp4

# anteprima veloce (640x360, 8 campioni, niente motion blur) di una parte dello shot
blender -b --factory-startup --python pubblicita/blender/build_shot.py -- \
    --spec spec.json --out prova.mp4 --preview --frames 0-11
```

Opzioni di `build_shot.py`: `--spec`, `--out`, `--res WxH`, `--samples N`,
`--frames a-b` (estremi inclusi, base 0), `--still N`, `--preview`,
`--save-blend scena.blend` (per aprire la scena in Blender e ritoccarla a mano),
`--keep-frames` (conserva i PNG in `<out>_frames/`).
Accanto all'uscita scrive `<out>.render.json` (risoluzione, campioni, intervallo di frame,
secondi per frame). Con `--frames a-b` l'mp4 contiene solo quei frame: il suo frame 0 e' il frame
`a` della spec (tenerne conto nel campo `"in"` dell'EDL).
Codici d'uscita: 0 ok, 2 spec non valida o argomenti errati, 1 errore durante il render.

Per il pannello finale (1056x594 nel reel) conviene `--res 1056x594`: stessa resa,
circa il 30% di tempo in meno rispetto a 1280x720.

## Convenzioni

- Unita' in **metri**, **Z in alto**, angoli in **gradi** (Euler XYZ).
- Il **fronte** di ogni prefab (manichino, auto, cartellone, abitacolo) guarda verso **-Y**:
  una camera in `[0, -8, 1.6]` che guarda `[0, 0, 1]` li vede di fronte. Per girare un oggetto
  si usa `rotation: [0, 0, gradi]` (es. `-90` = fronte verso -X, auto di profilo che va a sinistra).
- I prefab hanno l'origine **a terra** (z = 0 sotto i piedi/le ruote); le primitive al centro,
  salvo `"origin": "bottom"`.
- Il tempo si esprime in frame a 24 fps **con base 0** (`"f": 12`) oppure in secondi (`"t": 0.5`).
  Il frame N dell'mp4 corrisponde al frame N della spec, quindi coincide con il campo `"in"`
  dell'EDL di montaggio.
- Colori: `"#rrggbb"` (sRGB, come in un editor grafico) o `[r, g, b]` in 0..1.
- Con la vista `Standard` (default) un pannello emissivo a forza 1.0 appare esattamente del suo
  colore hex: e' il trucco per avere i pastelli piatti del riferimento.

## Struttura

```json
{
  "meta":    {"id": "s03_strada", "frames": 14, "resolution": [1280, 720], "samples": 12, "seed": 0, "note": "..."},
  "world":   {"preset": "night_city", "lights": [], "fog": null},
  "render":  {"vignette": 0.22, "motion_blur": false},
  "camera":  {"lens": 35, "location": [0, -8, 1.6], "look_at": [0, 0, 1.2], "moves": []},
  "objects": [ {"name": "auto", "type": "car", "style": "coupe_80s"} ]
}
```

Campi sconosciuti sono errori (un refuso non passa in silenzio). I nomi degli oggetti
sono facoltativi ma servono per `parent`, `look_at`, `tracking`, `dof.focus`; devono essere unici.

### meta

| campo | default | note |
|---|---|---|
| `id` | obbligatorio | lettere, cifre, `_ . -` |
| `frames` | obbligatorio | oppure `seconds` (convertito a 24 fps) |
| `fps` | 24 | solo 24 e' accettato |
| `resolution` | `[1280, 720]` | sovrascrivibile con `--res` |
| `samples` | 12 | campioni Cycles; con OIDN 12 bastano per superfici lisce. 24 per la resa finale se c'e' tempo |
| `seed` | 0 | seme di Cycles e dei generatori casuali (pannelli, skyline) |
| `note` | `""` | testo libero: cosa deve corrispondere nello shot AI |

### world

| campo | default | note |
|---|---|---|
| `preset` | `studio` | `night_city`, `night_sky`, `warm_interior`, `studio`, `dusk`, `day`, `none` |
| `color`, `strength` | dal preset | luce ambiente del mondo |
| `background`, `background_strength` | dal preset | colore del cielo **visto dalla camera** (separato dalla luce ambiente); `null` = uguale alla luce |
| `lights` | `[]` | luci aggiuntive (schema come l'oggetto `light`, senza `type`) |
| `replace_lights` | `false` | `true` = ignora le luci del preset e usa solo `lights` |
| `fog` | `null` | nebbia economica in compositing: `{"start": 5, "depth": 40, "color": "#1A1F2A", "amount": 0.6}` |
| `volumetric` | `null` | volume vero `{"density": 0.02, "color": "#FFFFFF", "anisotropy": 0.3}`: lento e rumoroso, preferire `fog` |

Preset: `night_city` (cielo nero, luce fredda dall'alto, glow), `night_sky` (cielo blu notte
visibile, come lo shot della torre), `warm_interior` (interni caldi), `studio` (grigio neutro),
`dusk` (sole basso arancio), `day`.

### render

| campo | default | note |
|---|---|---|
| `samples` | da `meta.samples` | |
| `denoise` | `true` | OIDN, prefiltro veloce |
| `adaptive_threshold` | 0.04 | |
| `light_tree` | `false` | spento e' ~30% piu' veloce con poche luci |
| `bounces` | `{"max":4,"diffuse":2,"glossy":2,"transmission":2,"transparent":4,"volume":0}` | |
| `clamp_indirect` | 6.0 | riduce le lucciole |
| `motion_blur`, `shutter` | `false`, 0.5 | utile per i passaggi "whip" e le auto veloci |
| `view_transform`, `look` | `Standard`, `None` | anche `AgX` (+ `Medium High Contrast`, `Punchy`...), `Filmic` |
| `exposure`, `gamma` | 0, 1 | |
| `glare` | `"preset"` | glow del compositor: `false` oppure `{"type": "Bloom", "threshold": 0.9, "strength": 0.4, "size": 0.6}` (tipi: Bloom, Fog Glow, Streaks, Ghosts, Simple Star, Sun Beams) |
| `vignette` | 0.22 | 0 = spenta |
| `film_transparent` | `false` | PNG/mp4 con sfondo trasparente non serve quasi mai |
| `crf` | 14 | qualita' H.264 |

### camera

| campo | default | note |
|---|---|---|
| `lens`, `sensor` | 35, 36 | mm; sensore orizzontale |
| `location` | `[0, -8, 1.6]` | |
| `look_at` | `[0, 0, 1.2]` | punto, nome oggetto (`"auto"`) o `{"object": "auto", "offset": [0,0,1]}`: segue l'oggetto se si muove |
| `rotation` | `null` | alternativa a `look_at` (gradi; `[90, 0, 0]` = orizzontale verso +Y) |
| `roll` | 0 | inclinazione laterale (gradi) |
| `shift` | `[0, 0]` | decentramento ottico |
| `keys` | `[]` | chiavi `{"f"|"t", "location", "look_at", "rotation", "lens", "roll", "focus_distance", "ease"}` |
| `moves` (o `preset`) | `[]` | movimenti preset applicati in sequenza alla posa base o alle chiavi |
| `dof` | `null` | `{"focus": "nome" | [x,y,z] | distanza | {"object","offset"}, "fstop": 4}`; senza `focus` mette a fuoco il punto guardato |
| `handheld` | `null` | micro-mosso a mano `{"amplitude": 0.012, "rotation": 0.3, "frequency": 1.0, "seed": 1}` (m, gradi, Hz); `true` = valori di default |

Movimenti (`moves`), tutti con `start`/`end` (frame, default l'intero shot; oppure `start_t`/`end_t`)
ed `ease` (default `in_out`):

| tipo | parametri | effetto |
|---|---|---|
| `static` | | nessuno |
| `dolly_in` / `dolly_out` | `distance` (m) | avanza/arretra lungo lo sguardo |
| `truck` | `distance`, `keep_target` | carrello laterale (positivo = a destra) |
| `pedestal` | `distance`, `keep_target` | sale/scende senza cambiare inclinazione |
| `pan` | `angle` | rotazione orizzontale sul posto (positivo = verso sinistra) |
| `tilt` | `angle` | inclinazione verticale sul posto (positivo = verso l'alto) |
| `orbit` | `angle`, `center`, `height` | orbita attorno al bersaglio (o a `center`) |
| `crane_up` / `crane_down` | `height`, `keep_target` (default `true`) | gru: sale/scende continuando a guardare il bersaglio |
| `tracking` | `target`, `offset` `[0,-4,1.2]`, `look_offset` `[0,0,1]` | segue un oggetto con offset fisso (mondo) |
| `zoom` | `lens_end` | cambia focale |
| `dolly_zoom` | `distance` | effetto vertigo: avanza e accorcia la focale |
| `roll` | `angle` | rollio progressivo |

Easing disponibili: `linear`, `in`, `out`, `in_out`, `smooth`, `sine`, `expo_in`, `expo_out`,
`back_out`, `constant`. Nelle chiavi l'`ease` indica come si **arriva** a quella chiave.

### objects: campi comuni

| campo | default | note |
|---|---|---|
| `type` | obbligatorio | vedi tabelle sotto |
| `name` | `<tipo>_<indice>` | |
| `location`, `rotation`, `scale` | `[0,0,0]`, `[0,0,0]`, 1 | `scale` numero o `[x,y,z]` |
| `material` | dipende dal tipo | vedi «Materiali» |
| `color` | dipende dal tipo | colore principale (sostituisce quello del materiale) |
| `parent` | `null` | nome di un altro oggetto: coordinate relative al genitore |
| `keys` | `[]` | `{"f"|"t", "location", "rotation", "scale", "ease"}` |
| `path` | `null` | `{"points": [[x,y,z], ...], "start": 0, "end": ultimo frame, "ease": "linear", "smooth": true, "orient": true, "yaw_offset": 0, "offset": [0,0,0]}`: moto lungo una spline; con `orient` il fronte segue la direzione |
| `visible` | `null` | `{"from": f, "to": f}`: visibile solo in quell'intervallo |
| `repeat` | `null` | `{"count": n, "offset": [dx,dy,dz], "rotation": [gradi per copia]}`: copie `nome_1`, `nome_2`... |
| `shadow` | `true` | `false` = non proietta ombre |
| `note` | `""` | |

Le auto fanno girare le ruote in base alla strada percorsa (anche in retromarcia, anche con
`keys`); i manichini con `walk` cadenzano i passi sulla distanza percorsa.

## Prefab

### mannequin

Manichino liscio color avorio (testa a uovo, busto con spalle larghe, braccia a capsula),
articolato su giunti. Default: `height` 1.65, `pose` `standing`, `dress` `long`,
`color` `#EEE7DB`, `accent` `#1E1E20` (obi, chignon, occhiali, borsa), `umbrella_color` `#141416`.

- `dress`: `long` (kimono/abito lungo: colonna fino a terra; da seduti diventa gambe piene),
  `none`, `pants`, `skirt` (gambe visibili).
- `accessories`: `hair_bun` (chignon e calotta nera), `kanzashi` (bastoncini bianchi a V),
  `flower`, `sunglasses`, `umbrella` (ombrello a cono davanti al busto), `obi`, `hat`, `bag`.
- `pose`: `standing`, `walking`, `sitting_chair`, `sitting_seiza`, `driving`, `hand_raise`,
  `turning_head`, `holding_umbrella`, `arms_front`, `looking_up`, `t_pose`.
- `joints`: angoli per giunto che si sommano/sostituiscono al preset, es.
  `{"head": [0, 0, 35], "shoulder_r": [-90, 0, 0]}`. Giunti: `pelvis`, `spine`, `neck`, `head`,
  `shoulder_l/r`, `elbow_l/r`, `wrist_l/r`, `hip_l/r`, `knee_l/r`, `ankle_l/r`
  (`_l` = sinistra del manichino = +X quando guarda -Y). Arti a riposo verso il basso:
  X negativo porta l'arto in avanti; per le braccia Y negativo apre il sinistro, Y positivo il destro;
  Z ruota attorno all'asse verticale (testa che si gira).
- `pose_keys`: `[{"f": 0, "pose": "standing"}, {"f": 12, "joints": {"head": [0,0,40]}, "ease": "in_out"}]`
  interpola tra pose (preset e/o giunti).
- `walk`: `true` o `{"cadence": 1.8, "stride": 0.7, "amplitude": 1.0, "phase": 0}`. Se l'oggetto si
  muove (path/keys) i passi seguono la distanza; altrimenti camminata sul posto con `cadence` passi/s.
- Per il manichino alla guida: stessa `location` di un `car_interior` + `pose: "driving"`.

### car

Auto low-poly a estrusioni: carrozzeria, abitacolo con vetri neri, paraurti e frontale neri,
fari bianchi emissivi, fanali posteriori rosa, ruote nere. Lunghezza lungo Y, muso verso -Y.

| campo | default | note |
|---|---|---|
| `style` | `coupe_80s` | `coupe_80s` (4.2 m, tipo AE86), `hatchback`, `sedan`, `sports`, `suv`, `van` |
| `color`, `lower_color` | `#E6E4E0`, `#121315` | |
| `popup_headlights` | `false` | fari a scomparsa sollevati (blocchi luminosi sul cofano) |
| `lights_on`, `headlight_strength`, `headlight_beams` | `true`, 30, `true` | i fasci sono spot reali che illuminano pavimento e muri |
| `taillights_on`, `taillight_color` | `true`, `#FF5C70` | |
| `doors_open` | `none` | `left`, `right`, `both` |
| `stripe` | `true` | filetto nero laterale |

### Citta'

- **building_block**: `size` `[w, d, h]` (default `[10,10,20]`, origine a terra), `color` `#101217`.
  `panels`: elenco di pannelli emissivi `{"face": "front|back|left|right", "x": 0, "z": centro,
  "w": 2, "h": 1.2, "color": "#CFF2E3", "strength": 1.1, "depth": 0.06}` (x orizzontale dal centro
  della faccia) oppure generazione casuale `{"count": 4, "faces": ["front"], "palette": [...],
  "w": [1.2, 3.5], "h": [0.8, 2.2], "z": [2, 9], "strength": 1.1}`. `windows`: griglia di finestre
  `{"faces": ["front"], "rows": 6, "cols": 4, "size": [0.8, 1.1], "fill": 0.6, "color": "#F2E6D8", "strength": 1.6, "margin": 1}`.
- **skyline**: fila di blocchi casuali: `count`, `axis` (`x`/`y`), `spacing`, `width`/`depth`/`height`
  come intervalli `[min, max]`, `seed`, `panels` (come sopra), `color`.
- **billboard**: pannello emissivo `size` `[w, h]`, `color`, `strength` 1.1, `frame` (colore cornice o `null`).
- **street**: piano `size` `[w, l]`, `wet` 0..1 (1 = specchio bagnato), `color`, `crosswalk`
  `{"center": [x, y], "count": 8, "stripe": [0.5, 4.0], "gap": 0.55, "axis": "x"}`,
  `lane_lines` (tratteggio centrale), `sidewalks` `{"height": 0.15, "width": 3, "gap": 7}`.
- **tower_lattice**: torre a traliccio (tipo Tokyo Tower) in aste bianche emissive: `height` 30,
  `base` 8, `top` 1.2, `levels` 10, `strut` 0.08, `antenna` 6, `color`, `emission` 1.2 (0 = argilla).
- **tree**: `height`, `radius`, `style` `round|cone`, `color`, `trunk_color`.

Palette pastello del riferimento: menta `#CFF2E3`, lilla `#E9C8F0`, crema `#F2E6D8`,
rosa `#F7BCD8`, celeste `#C4E4F8`.

### Interni

- **room**: stanza con origine al centro del pavimento, parete di fondo a +Y. `size` `[w, d, h]`
  (default `[6, 5, 2.6]`), `walls` (`back`, `left`, `right`, `front`), `wall_style`
  `shoji|plain|wood`, `floor` `tatami|wood|concrete|tiles`, `lintel` 1.85 (altezza dei pannelli;
  sopra c'e' la fascia in legno `beam_color`), `panel_width` 1.5 (passo dei montanti `frame_color`),
  `wall_color`, `ceiling`, `beam`, `light` (luce d'area calda a soffitto).
- **corridor**: corridoio/vicolo da y = 0 verso +Y: `length`, `width`, `height`, `wall_style`
  `wood_slats|plain|shoji`, `floor` `tiles|wood|stone` (piastrelle lucide con fughe), `signs`
  (pannelli blu scuro alle pareti), `end` `dark|wall|open`, `wall_color`, `lamps`
  `{"count": 6, "side": "both|left|right", "radius": 0.22, "height": 2.35, "color": "#FFF1DC", "strength": 6, "light_energy": 35}`.
- **lantern**: sfera bianca emissiva con luce puntiforme interna: `radius`, `color`, `strength`,
  `light_energy`, `cord` (filo verso l'alto, m), `stretch` (allungamento verticale).
- **table** (`size` `[1.2, 0.8, 0.75]`), **chair** (`seat_height` 0.45), con `material` (default `wood`).
- **car_interior**: abitacolo attorno al guidatore, origine a terra sotto il bacino: sedile,
  cruscotto, strumenti emissivi (`gauges_color`), volante, montanti e tetto (`frame`). `drive`
  `right|left` indica il lato della portiera.
- **text** / **sign**: testo 3D in piedi rivolto a -Y: `text`, `size`, `extrude`, `align`
  `center|left|right`, `material` (default `emissive:#FFFFFF:3`).

### Primitive

| tipo | parametri (default) |
|---|---|
| `box` | `size` `[1,1,1]`, `bevel` 0, `origin` `center|bottom` |
| `cylinder` | `radius` 0.5, `depth` 1, `vertices` 32, `origin`, `smooth` |
| `cone` | `radius1` 0.5, `radius2` 0, `depth` 1, `vertices`, `origin`, `smooth` |
| `sphere` | `radius` 0.5, `segments` 32, `rings` 16 |
| `plane` | `size` `[2, 2]` (orizzontale) |
| `torus` | `major` 0.5, `minor` 0.1, `segments` 48 |
| `capsule` | `radius` 0.1, `length` 1, `origin` |
| `lathe` | `profile` `[[raggio, z], ...]` ruotato attorno a Z (vasi, lampade, colonne, forme organiche) |
| `extrude` | `profile` `[[y, z], ...]` poligono laterale estruso lungo X per `width` (sagome di veicoli, rampe, tetti) |
| `empty` | nessuna geometria: perno per raggruppare (`parent`) e animare insieme |
| `light` | `light_type` `area|sun|point|spot`, `color`, `energy` (W; per `sun` W/m²), `size`, `size_y` (area rettangolare), `spot_size`, `spot_blend`, `angle` (sun), `look_at` (punto o nome), `camera_visible` (default `false`), `cast_shadow` |

## Materiali

`material` accetta:

- un preset: `clay`, `clay_dark`, `mannequin`, `white_glossy`, `car_paint`, `black_matte`,
  `glossy_black`, `accent_dark`, `building`, `wet_ground`, `asphalt`, `concrete`, `wood`,
  `wood_dark`, `wood_light`, `metal`, `chrome`, `glass` (vetro scuro da blockout, opaco e lucido),
  `glass_clear` (trasparente vero), `paper`, `shoji`, `tatami`, `beige`, `navy`, `tile`, `rubber`, `plastic`;
- `"preset:#rrggbb"` (preset con altro colore), es. `"building:#07080B"`;
- `"#rrggbb"` (argilla di quel colore);
- `"emissive:#rrggbb[:forza]"` (superficie che emette luce piatta, default forza 3);
- un dizionario `{"preset": "clay", "color": "#..", "roughness": 0.4, "metallic": 0, "coat": 0,
  "transmission": 0, "specular": 0.5, "ior": 1.5, "emission": "#..", "emission_strength": 1, "alpha": 1}`.

## Ricostruire uno shot AI

1. Guarda primo, centrale e ultimo frame dello shot Seedance: annota soggetti, lente apparente,
   altezza della camera, movimento.
2. Scrivi la spec partendo dall'esempio piu' vicino in `esempi/`. Nella stanza o nella strada
   misura le proporzioni: con lente `L` mm la larghezza inquadrata a distanza `D` e'
   `D * 36 / L` metri (altezza: `D * 20.25 / L` in 16:9).
3. Still veloce sul frame chiave (`--still N --res 528x298 --samples 6`), poi confronto:

   ```bash
   python3 -m pubblicita.blender.confronta --target pubblicita/output/seedance/s03.mp4 \
       --blockout pubblicita/output/blender/s03.png --tempi 0.4 --overlay --out confronto.png
   ```

4. Render della clip e verifica temporale con piu' istanti; `--stima-offset 1.0` propone lo
   sfasamento (in frame) che massimizza la somiglianza dei contorni. Un offset positivo `k`
   significa che nel montaggio il blockout va preso da `"in": k`.
5. Durata: renderizza almeno i frame che l'EDL usa (`in` + durata dello shot) — conviene un
   margine di qualche frame per poter ritoccare il taglio.

## Prestazioni (macchina di sviluppo: 4 core CPU condivisi, nessuna GPU)

Il limite e' la CPU: una scena banale (cubo + piano) a 1280x720 con 12 campioni richiede gia'
~4.5 s. Il costo fisso per frame (sincronizzazione, OIDN, compositor, salvataggio) e' ~1.2 s,
il resto e' path tracing (~0.6 s per campione a 720p negli esterni, ~1.1 s negli interni, dove
i raggi non escono mai dalla scena). Misure con i default (12 campioni, OIDN), con altri
processi attivi sulla macchina:

| scena | 640x360 | 1056x594 | 1280x720 |
|---|---|---|---|
| strada notturna (esterno) | ~2.8 s | ~6 s | ~7.7-10 s |
| stanza / corridoio (interni) | ~3.5-3.8 s | ~8-12 s | ~14-17 s |

Ottimizzazioni gia' attive: light tree spento, rimbalzi ridotti, caustiche spente, clamp
dell'indiretto, campionamento adattivo, OIDN con prefiltro veloce, dati persistenti tra i frame,
mesh dei prefab accorpate per materiale. Leve rimaste: `--res 1056x594` (la dimensione del
pannello nel reel), `--samples 8`, `--preview` per le prove, `--frames` per renderizzare solo i
frame che l'EDL usa davvero.

## Esempi

- `strada_notte.json` — strada bagnata, coupe di profilo, manichino con ombrello, cartelloni pastello (riferimento ~2.6 s).
- `stanza_shoji.json` — interno caldo con fusuma e tatami, manichino in kimono al centro (riferimento ~0.5 s).
- `corridoio_auto.json` — vicolo in legno con lanterne, coupe a fari accesi che avanza verso la camera (riferimento 0.0 s).
- `torre_notte.json` — manichino di spalle con chignon e kanzashi, torre a traliccio sul cielo notturno.
- `guida_interno.json` — manichino al volante visto da dietro la spalla, pareti che scorrono (scenografia animata).
- `catalogo.json` — vetrina di tutti i prefab e delle primitive.
