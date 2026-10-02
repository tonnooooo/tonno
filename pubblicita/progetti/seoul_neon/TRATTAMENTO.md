# Seoul neon: trattamento finale

Spot verticale 1080x1920 nel formato del reel @themira.creators ("26 shots, cut to 115 BPM / Blender blockout + one prompt"): due pannelli 16:9 sincronizzati, sopra il blockout Blender, sotto il render fotorealistico. Header "Opus 5.5", etichette a pillola "Blender" (sopra) e "Seedance 2.5" (sotto, al posto di "Mira AI x After Effects" del riferimento). 26 shot con le durate esatte del riferimento: 336 frame, 14,0 s a 24 fps, musica a 115 BPM.

Pipeline: keyframe Seedream 5.0 Pro, poi clip Seedance 2.5 (1080p, muti, uno per setup: 13 setup), poi blockout Blender costruiti sopra ogni clip (stessa camera e stesso movimento), poi montaggio sincrono dei due pannelli e impaginazione. Revisione 2: le modifiche rispetto alla prima versione sono riassunte nel §13.

## 1. Logline

Una notte di pioggia a Seoul in 26 tagli a 115 BPM. Una donna in hanbok avorio e corallo e la sua Skyline R34 Bayside Blue passano dai vicoli di hanok di Bukchon ai neon di Gangnam, dalla N Seoul Tower blu alla porta dorata di Gwanghwamun e a un minimarket sotto la pioggia, per chiudere nel silenzio di una stanza in fondo al corridoio del palazzo. Sopra, lo stesso film rifatto in blockout Blender, fotogramma per fotogramma.

Lettura leggera, presa dal trattamento "cinema": lo sguardo cresce lungo lo spot. Occhi bassi (shot 4), contatto (8), si volta (11), sorride (16), occhiali nei fari (18-20), frontale con la torre (25), poi la calma simmetrica della chiusura (26).

## 2. Giudizio dei tre trattamenti e scelta

Punteggi da 1 a 10. La media pesata conta doppia la fedelta', perche' la richiesta e' rifare "esattamente questa pubblicita'" con un video diverso.

| Trattamento | Impatto visivo | Fedelta' a formato e ritmo | Fattibilita' Seedance 2.5 | Facilita' blockout | Coerenza musica | Media | Media pesata |
|---|---|---|---|---|---|---|---|
| A "fedele" | 8 | 10 | 6 | 7 | 9 | 8,0 | **8,3** |
| B "cinema" | 9 | 5 | 6 | 7 | 8 | 7,0 | 6,7 |
| C "fattibile" | 7 | 8 | 9 | 9 | 8 | 8,2 | 8,2 |
| **Finale (A + innesti di C e B)** | 9 | 9 | 8 | 8 | 9 | 8,6 | **8,7** |

**A "fedele".** Pro: mappa 1:1 dei 26 shot sui setup del riferimento, con gli stessi riusi (vicolo 1/12/13, stanza 2/9/17, volante 3/6/14, viso 4/8, torre 5/22/25, citta' 7/11/15/16/23/24). Il dolly unico di S01 da' campo largo, medio e dettaglio del faro nativi, senza crop. Mappa degli accenti musicali precisa. Contro: azioni rischiose per Seedance (girata di 180 gradi in S05, inginocchiarsi in chima in S02, infilarsi gli occhiali con due mani in S09, quattro azioni in 8 s in S08). Il palazzo compare solo come corridoio, il vicolo in 7 shot su 26.

**B "cinema".** Pro: arco narrativo arrivo / incontro / partenza, immagini forti (silhouette nei fari, ramyeon al minimarket, quattro punti rossi sotto Gwanghwamun). Contro: l'ordine e il ruolo dei setup si allontanano dal riferimento (shot 2 volante, shot 3 portiera, chiusura sull'auto invece che sul corridoio). Il passaggio ad alta velocita' generato (S11) rischia lo smear, il ramyeon mette insieme mani, bicchiere e vapore, ci sono due dolly lunghi da ricostruire.

**C "fattibile".** Pro: grammatica di camera minima (fissa o un solo dolly), mani quasi sempre nascoste, girate di testa al posto dei gesti con oggetti, blockout semplice (gonna a cono, camminata come traslazione), set condivisi, Gwanghwamun come campo largo. Contro: i gesti del riferimento (capelli, occhiali) diventano sguardi e lo spot perde vita; gli shot 15/16 passano al palazzo e al viso; il whip si risolve sul minimarket invece che sul campo largo cittadino.

**Scelta: A come base**, perche' e' l'unico che rifa' davvero lo spot inquadratura per inquadratura. Innesti:

- **Da C (fattibilita').**
  - S09: gli occhiali sono gia' indossati e una mano li sistema alla stanghetta. Niente occhiali da infilare con due mani.
  - S10: l'inquadratura taglia sulla linea del finestrino, testa e spalle restano fuori campo. Il volto non si vede, quindi niente rischio di moderazione.
  - In ogni clip con mani: lock "natural hands, five fingers". Camera fissa su treppiede o un solo dolly lineare (S01).
  - Ripieghi dichiarati: S02 con il last_frame seduta (lf_S02) come keyframe di partenza; S08b senza il gesto della mano.
  - Blockout semplificato: gonna a cono, camminata come traslazione con bob, girate come rotazioni su un empty.
  - I crop e il micro push-in si fanno in post, identici sul render Blender. I momenti si ri-temporizzano di +-0,5 s sui clip veri.
  - Lo shot 12 parte ~4 frame prima del lampeggio, che cade cosi' sul beat 10.
- **Da B (impatto).**
  - S07, il retro della R34 con i quattro fanali tondi (shot 10, 19), si sposta dal vicolo al viale davanti alla porta Gwanghwamun illuminata d'oro. Il palazzo diventa un esterno iconico, oltre al corridoio di chiusura, e il vicolo scende da 7 a 5 shot.
  - Coloritura di gayageum nella musica.
  - La lettura dello sguardo che cresce lungo lo spot.
- **Dalla revisione 2.** Le due azioni piu' rischiose di A sono divise: S05 diventa S05a (di spalle, immobile) + S05b (frontale dal basso con occhiali, nuovo keyframe, come lo shot 25 del riferimento); S08 diventa S08a (cammina e si volta) + S08b (frontale accanto al cofano, mano ai capelli, come gli shot 15 e 16 del riferimento).

## 3. Look e palette

**Formato.**
- Fondo off-white con onde sottili verde acqua.
- Header: logo e "Opus 5.5". "Opus" compare a ~0,5 s, "5.5" entro 0,75 s, sul clap e lo stab del beat 1 a 0,55 s.
- Due pannelli 16:9 larghi ~1048 px, angoli arrotondati, ombra morbida, pillola in alto a sinistra: "Blender" sopra, "Seedance 2.5" sotto.
- Clip a 1080p: lo zoom massimo e' 1,65x (crop 1,6x dello shot 19 per il push digitale 1,03), cioe' ~1165 px nativi per un pannello da ~1048 px, senza upscale.

**Pannello inferiore (Seedance 2.5).** Notte di pioggia, look pellicola Vision3 500T, grana fine, neri profondi ma aperti, alte luci che sfumano morbide. Luce sempre motivata, superfici bagnate ovunque con lunghe strisce speculari.

| Famiglia | Toni | Calore / accenti |
|---|---|---|
| Esterni notte (vicolo, Gangnam, torre, palazzo) | ombre teal-nere #070E14-#192024, medi grigio-ciano desaturati, alte luci neutre fredde | solo dalle sorgenti: lanterne ambra #FFB866, oro di Gwanghwamun #E8A84A, fanali rossi, neon; Bayside Blue (~#1F5FAE) protetto con un rim freddo; torre blu in rima con l'auto |
| Interni hanok | monocromo miele-seppia #2A1D0F -> #B88E55 -> #F3DDB0, contrasto basso | l'hanbok avorio e' la massa piu' chiara |
| Ritratto | fondale beige caldo #876E4D, key frontale morbida | orecchini oro |
| Minimarket | bianco fluorescente freddo | un solo lampo di bianco contro il blu dell'auto |

Costume contro auto: avorio #F2EBDD, corallo #D9603B, oro #C9A24B, prugna #6B1F2E. Il complementare del blu fa staccare l'hanbok senza fondersi con l'auto.

**Ottiche (fisse per setup).**
- 24mm: corridoio.
- 35mm: vicolo, stanza, Gangnam largo, portiera.
- 50mm: abitacolo, Gangnam stretto e frontale accanto al cofano, retro davanti al palazzo.
- 85mm: viso e torre (compressione), anche dal basso in S05b.
- Camera bassa per l'auto (40-70 cm), altezza occhi per i ritratti.

**Composizione e movimento.** Simmetrie a un punto di fuga (fari, stanza, retro con la porta, corridoio), terzi con la torre, vicolo che fugge verso il centro in S01. Camera sempre ferma: su treppiede, o solidale all'auto in S03. L'unico movimento di macchina e' il dolly di S01. Il micro push-in non si chiede piu' a Seedance ("locked-off" + "slow push-in" si contraddicono e fSpy lavora su camera fissa): e' un push digitale 1,00 -> 1,03 sul tempo del clip, identico sui due pannelli, nei setup S02, S04, S05a, S05b, S06, S07, S09, S11 (`fx.push` nell'EDL). Il resto lo fanno soggetto, luci, pioggia e montaggio. L'unico whip (shot 24) si fa in post, identico nei due pannelli.

**Pannello superiore (Blender).** EEVEE con la stessa palette del clip (navy di notte, beige negli interni), ombre morbide, riflessi in screen space, bloom leggero.
- Manichino in argilla crema senza volto. Chignon = sfera nera con binyeo bianco orizzontale e una sfera bianca grande (la peonia) sul lato sinistro, dietro l'orecchio sinistro.
- Auto = box low-poly blu con fari emissivi bianchi e 4 dischi rosa-salmone, un solo terminale di scarico.
- Maxischermi = card emissive pastello. Lanterne = sfere emissive. Torre = traliccio wireframe bianco. Ombrello = cono nero.
- Pavimenti lucidi riflettenti.

**Niente testo nell'immagine.** Insegne come bagliori astratti, maxischermi con soli campi di colore (niente lettere, volti o persone), insegna del minimarket vuota, targhe bianche vuote, strumenti sfocati, nessuna bandiera.

## 4. Personaggio

Donna coreana adulta sui 25 anni, viso ovale, sguardo calmo. Capelli neri lucidi in uno chignon basso (jjokjin meori) con un lungo binyeo d'argento orizzontale e una grande peonia di seta avorio appuntata sul lato sinistro dello chignon, subito dietro l'orecchio sinistro: si vede di fronte e di spalle ed e' la firma del personaggio, come il grande fiore bianco del riferimento (shot 4, 8, 16, 17, 25). Due ciocche sottili libere ai lati del viso, servono per il gesto di S08b. Orecchini pendenti d'oro, bangle di giada al polso sinistro (il destro e' nudo).

Hanbok moderno:
- jeogori corto avorio con colletto bianco a Y e nastro otgoreum corallo;
- chima avorio a vita alta fino alla caviglia, con orlo a peonie in foglia d'oro;
- durumagi aperto in organza avorio trasparente con un grande medaglione a peonia corallo e oro tra le scapole (sostituisce il fiocco dell'obi del riferimento);
- norigae corallo e prugna;
- scarpe di raso avorio.

Occhiali cat-eye scuri solo in S05b e S09. Mai "geisha" o "gisaeng", eta' adulta sempre esplicita, nessuna sessualizzazione.

**Moduli di prompt.** Nei keyframe Seedream non si incolla piu' un unico blocco con donna e auto: prima la composizione (inquadratura, posa, luogo), poi solo i moduli di cio' che si vede. Un volto descritto dove non deve vedersi tende a comparire, e i dettagli del retro dell'auto in una vista frontale producono ibridi. Le negazioni con nomi propri ("not an AE86", "not a kimono") sono sostituite da descrizioni positive, perche' nominare un concetto lo richiama.

```text
W_FACE: THE WOMAN: an adult Korean woman in her mid-20s, oval face, soft cheekbones, calm dark-brown almond eyes, straight natural brows, muted coral-rose lips, minimal makeup, real skin texture with visible pores.

W_HAIR: Glossy jet-black hair parted in the center and swept into a low chignon at the nape, two fine loose strands framing her face, a long horizontal silver binyeo hairpin with jade tips through the knot, a large ivory silk peony pinned at the left side of the chignon just behind her left ear, long gold drop earrings.

W_FRONT: Modern Korean hanbok: short cropped ivory silk jeogori with a crisp white Y-shaped dongjeong collar and a long coral otgoreum ribbon bow on the chest; high-waisted, full, ankle-length ivory silk chima with a gold-leaf peony hem; a sheer ivory silk-organza durumagi worn open; a coral-and-plum norigae tassel at the ribbon; a slim jade bangle on her left wrist; ivory satin heels.

W_BACK: Seen from behind, her face never visible: the low black chignon with the horizontal silver binyeo and the large ivory peony, the sheer ivory organza durumagi with a large coral-and-gold embroidered peony medallion between the shoulder blades, the full ankle-length ivory chima with its gold-leaf hem.

W_COLLAR: Ivory silk jeogori with a crisp white Y-shaped dongjeong collar and a long coral otgoreum ribbon bow on the chest.

HANBOK_SIL: Authentic Korean hanbok silhouette: short jeogori, high-waisted chima, narrow curved sleeves.
```

| Keyframe | Moduli dopo la composizione |
|---|---|
| kf_S01 | C_FRONT |
| kf_S02 | W_FACE + W_HAIR + W_FRONT |
| kf_S03 | C_INT + manica avorio, organza e retro dello chignon con binyeo e peonia; mano destra nuda, bangle al polso sinistro fuori campo (niente W_FACE) |
| kf_S04 | W_FACE + W_HAIR + W_COLLAR |
| kf_S05a, kf_S08a | W_BACK + parte d'auto visibile (S05a: parafango e cofano) o C_REAR (S08a) |
| kf_S05b | W_FACE + W_HAIR + W_COLLAR, occhiali |
| kf_S06 | C_SIDE + W_FACE + W_HAIR + W_FRONT |
| kf_S07 | C_REAR |
| kf_S08b | W_FACE + W_HAIR + W_FRONT + parte d'auto visibile (cofano, parafango, parabrezza) |
| kf_S09 | C_FRONT + W_FACE + W_HAIR + W_FRONT, occhiali |
| kf_S10 | C_SIDE + chima con orlo in foglia d'oro e scarpe di raso (testa fuori campo) |
| kf_S11 | W_HAIR + W_FRONT, occhi bassi, lineamenti non distinguibili |
| lf_S02, lf_S08a | prompt di modifica dell'immagine 1 (il keyframe): cambia solo la posa |

Lunghezza dei prompt dei keyframe: da 1447 a 2312 caratteri (prima della revisione 2.130-3.370). I piu' lunghi sono quelli con donna e auto insieme (S06, S08b, S09), dove servono tutti i moduli.

Nei prompt Seedance si usano solo i lock brevi: `THE WOMAN (the same Korean woman in her mid-20s from the first frame)` e `Face, low chignon with silver binyeo and ivory peony, and ivory hanbok unchanged.`

## 5. Auto

Nissan Skyline R34 GT-R coupe in Bayside Blue, metallizzato lucido. Profilo squadrato a cuneo, passaruota gonfi, fari angolari fissi a proiettore, paraurti con intercooler a vista, cofano con presa in carbonio, alettone alto, quattro fanali tondi (la firma), un solo grande terminale di scarico (a destra sulla GT-R di serie: da verificare su foto prima di approvare ref_auto_retro), cerchi canna di fucile. Guida a destra, coerente in abitacolo (S03), portiera (S10) e blockout.

La R34 non ha fari a scomparsa: lo shot 12 diventa il doppio lampeggio degli abbaglianti. Targa bianca vuota, nessun badge leggibile.

```text
C_FRONT: THE CAR: one late-1990s Nissan Skyline R34 GT-R coupe in Bayside Blue, vivid metallic mid-blue with a deep glossy clearcoat; boxy wedge body, pumped arches, sharp angular fixed projector headlights (no pop-up headlights), wide mesh front intake showing the intercooler, carbon splitter and hood vent, tall rear wing visible above the roof, dark gunmetal wheels, blank white plate, no badges.

C_REAR: THE CAR from behind: one late-1990s Nissan Skyline R34 GT-R coupe in Bayside Blue; tall rear wing on two uprights, four round red taillights across the black rear panel, rear diffuser, a single large exhaust tip, blank white plate, no badges.

C_SIDE: THE CAR from the side: one late-1990s Nissan Skyline R34 GT-R coupe in Bayside Blue; boxy wedge profile, short overhangs, pumped arches, tall rear wing, dark gunmetal wheels, no badges.

C_INT: Inside the right-hand-drive R34 GT-R: black three-spoke steering wheel on the right, round analog gauges in a binnacle, a small display high on the center dash, six-speed shifter, black bucket seats; every gauge and screen soft and unreadable.
```

Lock Seedance: `THE CAR (the same Bayside Blue R34 GT-R coupe from the first frame)` e, secondo la vista:
- frontale (S01, S09): `Car shape, Bayside Blue paint, angular headlights and front intake unchanged, blank license plate.`
- da dietro (S07, S08a): `Car shape, Bayside Blue paint and four round taillights unchanged, blank license plate.`
- di fianco (S06, S10): `Car shape, Bayside Blue paint, rear wing and dark wheels unchanged, blank license plate.`
- solo una parte dell'auto (S05a, S08b): `Car shape and Bayside Blue paint unchanged.`

## 6. Dai luoghi del riferimento a Seoul

| Riferimento (Tokyo) | Seoul | Shot | Setup |
|---|---|---|---|
| vicolo di legno con lanterne | vicolo di hanok a Bukchon | 1, 12, 13, 18, 20 | S01, S09 |
| retro auto nel vicolo | retro auto sul viale davanti a Gwanghwamun | 10, 19 | S07 |
| stanza tatami | stanza hanok (hanji, ondol) | 2, 9, 17 | S02 |
| volante | volante con guida a destra | 3, 6, 14 | S03 |
| viso | viso, fondale di hanji | 4, 8 | S04 |
| Tokyo Tower | N Seoul Tower blu sul Namsan | 5, 22, 25 | S05a, S05b |
| incrocio di Shibuya | Gangnam-daero | 7, 11, 15, 16, 23, 24 | S06, S08a, S08b |
| portiera | portiera davanti al minimarket | 21 | S10 |
| corridoio verso la stanza | corridoio del palazzo (stile Gyeongbokgung) verso la stanza hanok | 26 | S11 |

## 7. Setup (13 clip Seedance)

| ID | Setup | Durata | Shot | Input Seedance | Volto visibile | Push in post |
|---|---|---|---|---|---|---|
| S01 | Vicolo di Bukchon: R34 quasi frontale, abbaglianti (rif. shot 1, 12, 13) | 6 s | 1, 12, 13 | first_frame | no | no |
| S02 | Stanza hanok: in piedi, seduta formale, profilo (rif. shot 2, 9, 17) | 7 s | 2, 9, 17 | first_frame+last_frame | si | si |
| S03 | Abitacolo con guida a destra: mani sul volante (rif. shot 3, 6, 14) | 5 s | 3, 6, 14 | first_frame | no | no |
| S04 | Primo piano beauty: clip ancora d'identita' (rif. shot 4, 8) | 5 s | 4, 8 | first_frame | si | si |
| S05a | Di spalle con la N Seoul Tower, immobile nella brezza (rif. shot 5, 22) | 5 s | 5, 22 | first_frame | no | si |
| S05b | Frontale dal basso con occhiali, torre a sinistra (rif. shot 25) | 4 s | 25 | first_frame | si | si |
| S06 | Gangnam-daero: campo largo con ombrello nero (rif. shot 7, 24) | 5 s | 7, 24 | first_frame | si | si |
| S07 | Retro della R34 davanti a Gwanghwamun: quattro fanali tondi e vapore (rif. shot 10, 19) | 5 s | 10, 19 | first_frame | no | si |
| S08a | Gangnam: cammina verso i fanali e si volta (rif. shot 11, 23) | 5 s | 11, 23 | first_frame | si | no |
| S08b | Gangnam: frontale accanto al cofano, mano ai capelli (rif. shot 15, 16) | 5 s | 15, 16 | first_frame | si | no |
| S09 | Davanti ai fari nel vicolo, occhiali da sole (rif. shot 18, 20) | 5 s | 18, 20 | first_frame | si | si |
| S10 | Portiera davanti al minimarket: i piedi scendono (rif. shot 21) | 5 s | 21 | first_frame | no | no |
| S11 | Corridoio del palazzo verso la stanza hanok: chiusura (rif. shot 26) | 5 s | 26 | first_frame | no | si |
| | **Totale** | **67 s** | 26 | | | |

Totale 67 s a 1080p: circa 3,26 M token, 226 CNY, 32 USD per una take. Ogni shot ha almeno 12 frame (0,5 s) di margine prima della fine del suo clip, per poter ri-temporizzare sui clip veri.

### S01 - Vicolo di Bukchon: R34 quasi frontale, abbaglianti (rif. shot 1, 12, 13)

- **Location.** Bukchon Hanok Village (Gahoe-dong), vicolo stretto in salita, notte dopo la pioggia: muri di pietra e intonaco, gronde di tegole nere ricurve, portoni di legno, lanterne di carta calde, lastricato bagnato. Stesso set di S09.
- **Camera.** 35mm ad altezza paraurti (60 cm). Il vicolo fugge dritto verso un punto di fuga appena a destra del centro; l'auto a ~6 m, quasi frontale (leggero 3/4, muso verso sinistra camera), occupa il centro-sinistra del quadro. Un solo movimento: dolly-in continuo e liscio con ease-in/out fino al dettaglio del faro piu' vicino (quello a destra del quadro, ~1,5 m), che a 5,0 s riempie circa due terzi del quadro; poi fermo.
- **Azione.** [0-2,3 s] auto ferma, anabbaglianti accesi, pioggia nei fasci. [2,4 s] gli abbaglianti lampeggiano due volte e restano accesi (sostituisce i fari a scomparsa dello shot 12, che la R34 non ha). [2,4-5,0 s] luce piena, la camera arriva sul faro (shot 13 nativo, senza crop). [5,0-6,0 s] fermo sul dettaglio.
- **Durata clip.** 6 s. **Shot.** 1, 12, 13.
- **Blockout.** Set VICOLO (riusato da S09): due pareti con zoccolo di pietra grigio, intonaco chiaro e fascia di gronda nera sporgente 0,6 m con estremita' rialzate; portoni = pannelli scuri incassati; lanterne = sfere emissive bianco-ambra (#FFB866, strength ~6) in fila verso il punto di fuga (appena a destra del centro); pavimento a lastre lucide (roughness 0,08-0,12). Auto proxy R34 (riusata in tutto lo spot): box smussato blu (#1F5FAE desaturato), cabina trapezoidale, alettone = piastra su due montanti, presa anteriore scura, ruote = cilindri neri; qui quasi frontale, muso verso sinistra camera, nel centro-sinistra. Fari = due rettangoli emissivi bianchi angolati: strength 8 fino al frame del lampeggio, poi 30/8/30/8 e fisso a 30 (copiare i frame esatti dal clip); indicatori = piccoli rettangoli ambra; due spot nei fari con volumetrica leggera per i fasci. Pioggia = card verticali sottili leggibili solo nei fasci. Camera 35mm, sensore 36 mm, 1920x1080, 24 fps, h 0,6 m; dolly in linea retta da A (~6 m) a B (faro destro del quadro, ~1,5 m) con le stesse curve del clip, arrivo a 5,0 s (clip come sfondo al 50%, verificare primo e ultimo frame). World navy scuro, EEVEE con ombre morbide, SSR e bloom leggero.

### S02 - Stanza hanok: in piedi, seduta formale, profilo (rif. shot 2, 9, 17)

- **Location.** Stanza di hanok di notte: porte a graticcio con carta hanji retroilluminata, pavimento ondol in carta oliata color miele lucido, trave scura, paravento basso con peonie sbiadite al bordo destro. E' la stessa stanza in fondo al corridoio di S11.
- **Camera.** 35mm ad altezza vita, frontale e perfettamente simmetrica, lei a figura intera nel terzo centrale. Camera fissa su treppiede (push digitale 1,00-1,03 in post). Shot 17 = crop 1,5x centrato su di lei seduta.
- **Azione.** [0-1,8 s] in piedi, mani giunte in vita, respira. [1,8-4,0 s] si inginocchia lentamente nella seduta formale, la chima si apre a cerchio sul pavimento (analogo del seiza dello shot 9). [4,0-5,2 s] immobile, sguardo in camera. [5,2-6,4 s] gira la testa alla sua destra (verso sinistra schermo) fino al profilo pulito, lo sguardo lungo la stanza (analogo della girata dello shot 17). [6,4-7,0 s] tiene il profilo. first_frame kf_S02 (in piedi) + last_frame lf_S02 (seduta, di profilo: modifica di kf_S02), che fa anche da keyframe di ripiego.
- **Durata clip.** 7 s. **Shot.** 2, 9, 17.
- **Blockout.** Set HANOK (riusato in fondo al corridoio di S11): scatola 4x4 m; parete di fondo = griglia di montanti scuri sottili (#3B2A1A) con pannelli emissivi caldi e deboli (#F3DDB0, strength 2-3) per la hanji retroilluminata; pavimento miele lucido (#B88E55, roughness ~0,25) con riflesso morbido; trave scura in alto; paravento = piano a due tinte. Manichino in argilla crema riggato (testa a uovo senza tratti, collo cilindrico), corpo a colonna che si allarga a campana per la chima; chignon = sfera nera bassa con bastoncino bianco orizzontale (binyeo) e una sfera bianca grande (peonia) sul lato sinistro, dietro l'orecchio sinistro; nastro corallo = card sul petto (#D9603B). Animazione sui frame del clip: in piedi -> inginocchiata (bacino che scende, la campana si schiaccia in un disco con shape key) -> testa ruotata di ~80 gradi alla sua destra (verso sinistra schermo). Camera 35mm frontale h ~1,0 m, fissa (il push 1,00-1,03 si fa in compositing su entrambi i pannelli). Luci: grande area light calda dietro la parete di carta + fill caldo da sinistra camera. Monocromo seppia identico al finale.

### S03 - Abitacolo con guida a destra: mani sul volante (rif. shot 3, 6, 14)

- **Location.** Dentro la R34 (guida a destra) che avanza piano nella pioggia notturna di Seoul; parabrezza con gocce, neon sfocati oltre il vetro.
- **Camera.** Over-the-shoulder dal sedile posteriore, dietro e a sinistra della spalla sinistra di lei (lei siede a destra): spalla avorio in primo piano a destra. 50mm, profondita' di campo minima, fuoco su mani e corona del volante. Camera solidale all'auto, ferma. Shot 14 = crop 1,4x sulle mani.
- **Azione.** [0-1,6 s] solo la mano destra appoggiata in cima al volante (ore 12), polso destro nudo. [1,6-3,2 s] la mano sinistra, con il bangle di giada al polso, entra in campo e afferra il volante a ore 9. [3,2-5,0 s] entrambe le mani stringono, le dita si flettono, piccola correzione di sterzo. Il bokeh dei neon scivola piano verso sinistra sul parabrezza. Volto fuori campo.
- **Durata clip.** 5 s. **Shot.** 3, 6, 14.
- **Blockout.** Set INTERNO: plancia = box scuro smussato (#141414) con cupola strumenti, due dischi emissivi bianco-ambra (#FF9A3C, strength ~3) e un piccolo rettangolo emissivo al centro (MFD, nessun numero). Volante = toro nero sottile + tre razze + mozzo, rotazione di pochi gradi copiata dal clip. Parabrezza = piano inclinato; dietro, una card emissiva grande con macchie sfocate magenta/ciano/ambra la cui UV scorre verso sinistra alla velocita' del clip. Spalla e braccio del manichino in argilla crema in primo piano a destra; mani semplificate (palmo a box, dita a capsule) riggate per la presa; bangle = toro verde sottile sul polso sinistro (il destro e' nudo). Camera 50mm imparentata a un empty dell'auto (noise di 1-2 mm per la vibrazione), DOF ~f/1.8 a fuoco sulla corona. Lato guida a destra, coerente con S10.

### S04 - Primo piano beauty: clip ancora d'identita' (rif. shot 4, 8)

- **Location.** Interno hanok: fondale di carta hanji beige caldo, completamente fuori fuoco.
- **Camera.** Primo piano frontale dal petto in su, centrato, 85mm ad altezza occhi, profondita' di campo minima. Camera fissa su treppiede (push digitale 1,00-1,03 in post).
- **Azione.** [0-2,0 s] sguardo leggermente in basso a sinistra. [2,0-3,0 s] alza gli occhi nell'obiettivo. [3,0-5,0 s] tiene lo sguardo, un battito di ciglia lento, accenno di sorriso, gli orecchini oscillano appena. Il test di moderazione dei volti si fa sulla voce separata S04_t480 (480p, 5 s, output S04_t480.mp4), che non tocca S04.mp4.
- **Durata clip.** 5 s. **Shot.** 4, 8.
- **Blockout.** Set RITRATTO: testa = ovoide crema senza tratti su collo cilindrico (come shot 4 e 8 del riferimento); colletto bianco a Y (due card incrociate) e fiocco corallo; chignon nero dietro la testa con il binyeo bianco che sporge ai lati e una sfera bianca grande (peonia) sul lato sinistro della testa (a destra nel quadro), dietro l'orecchio; orecchini = due capsule oro (#C9A24B) pendenti con oscillazione smorzata (noise). Fondale = piano beige caldo (#876E4D) con leggero gradiente. Il manichino non ha occhi: lo sguardo che sale si rende con un tilt della testa di ~5-8 gradi verso l'alto nei frame in cui lei alza gli occhi. Luce: grande area light morbida frontale + rim caldo debole. Camera 85mm ad altezza occhi, DOF f/1.8, fissa (push in compositing).

### S05a - Di spalle con la N Seoul Tower, immobile nella brezza (rif. shot 5, 22)

- **Location.** Strada panoramica in collina sopra Seoul, di notte. In lontananza la N Seoul Tower illuminata di blu sul Namsan, sopra il tappeto di luci della citta': il blu della torre fa rima con il Bayside Blue.
- **Camera.** 85mm ad altezza petto: il tele comprime e ingigantisce la torre. Lei di spalle a sinistra del centro dalla vita in su, torre al centro-destra, parafango e cofano blu in basso a sinistra. Camera fissa su treppiede (push digitale 1,00-1,03 in post).
- **Azione.** [0-5,0 s] di spalle, immobile, guarda la torre; la brezza solleva piano l'organza del durumagi (medaglione peonia sulla schiena) e muove le nappe del norigae; le luci della citta' tremolano. Non si gira mai: il volto resta nascosto. Niente occhiali in questo setup.
- **Durata clip.** 5 s. **Shot.** 5, 22.
- **Blockout.** Set TORRE: cielo = colore del mondo navy (#172435) con lieve gradiente; torre = traliccio wireframe bianco sottile (fusto conico, disco dell'osservatorio, antenna) con anello emissivo azzurro (#5DA9FF), al centro-destra e in grande scala come la torre del riferimento; skyline = blocchi neri bassi; luci della citta' = migliaia di sferette emissive calde (instancing) sfocate dal DOF. Auto proxy: porzione di box blu smussato in basso a sinistra. Manichino di spalle: durumagi = guscio a campana semitrasparente (alpha ~0,4) con disco corallo sulla schiena (medaglione); chignon nero + binyeo bianco orizzontale + sfera bianca grande sul lato sinistro; nappe del norigae e orlo del guscio con leggero cloth o shape key mossi dalla brezza. Nessuna rotazione del manichino. Camera 85mm h 1,4 m, DOF moderato (f/2.8), fissa (push in compositing). Rim freddo dal lato della torre.

### S05b - Frontale dal basso con occhiali, torre a sinistra (rif. shot 25)

- **Location.** La stessa strada panoramica di S05a: N Seoul Tower blu a sinistra del quadro, sfocata, cielo navy, luci della citta' sfocate in basso.
- **Camera.** Mezzo primo piano frontale dal petto in su, dal basso (85mm sotto l'altezza del petto, inclinato verso l'alto), lei centrata; torre a sinistra, morbida. Camera fissa su treppiede (push digitale 1,00-1,03 in post). Shot 25 nativo, senza crop.
- **Azione.** [0-2,0 s] ferma, rivolta all'obiettivo con gli occhiali cat-eye scuri; la brezza muove le ciocche libere e gli orecchini d'oro. [2,0-4,0 s] alza appena il mento, sorriso appena percettibile; la torre blu resta accesa dietro di lei.
- **Durata clip.** 4 s. **Shot.** 25.
- **Blockout.** Riusa il set TORRE di S05a con nuova camera dal basso: torre wireframe con anello azzurro a sinistra del quadro, fuori fuoco (f/2), luci della citta' sfocate in basso. Manichino crema frontale dal petto in su: colletto bianco a Y e fiocco corallo, chignon con binyeo bianco e sfera bianca grande sul lato sinistro della testa (a destra nel quadro), occhiali = rettangolo grigio scuro; orecchini = capsule oro con oscillazione smorzata. Animazione: tilt della testa di pochi gradi verso l'alto nei frame del clip. Camera 85mm h ~1,2 m inclinata verso l'alto, fissa (push in compositing). Rim freddo dal lato della torre, bounce caldo dal basso.

### S06 - Gangnam-daero: campo largo con ombrello nero (rif. shot 7, 24)

- **Location.** Gangnam-daero di notte sotto la pioggia: viale largo, torri di vetro, maxischermi LED con soli campi di colore astratti (niente lettere, niente volti, niente persone), insegne al neon illeggibili, strisce pedonali, asfalto bagnato a specchio.
- **Camera.** Campo largo ad altezza ginocchio (~50 cm), 35mm, profondita' di campo moderata: auto e ragazza nitide, torri e maxischermi dietro morbidamente fuori fuoco; orizzonte in bolla. Auto di profilo con il muso a sinistra, al centro-basso; lei in piedi accanto al parafango anteriore con un ombrello nero (come lo shot 7 del riferimento). Camera fissa su treppiede (push digitale 1,00-1,03 in post). Shot 24: whip pan fatto in post (blur direzionale + scie per ~5 frame) che si risolve su questo campo largo.
- **Azione.** [0-2,5 s] pioggia fitta, gocce che rimbalzano, i maxischermi cambiano lentamente campi di colore, scie di traffico lontane. [2,5-5,0 s] lei inclina l'ombrello all'indietro e gira il viso verso camera.
- **Durata clip.** 5 s. **Shot.** 7, 24.
- **Blockout.** Set GANGNAM (stesso linguaggio dello Shibuya del riferimento, riusato da S08a e S08b): blocchi neri alti (#0B0D10) con card emissive pastello (menta #CDE4DD, rosa #F2B8CF, lavanda #CBB8F0, bianco) al posto dei maxischermi, con color ramp animata per il cambio colore, sfocate dal DOF; strisce emissive sottili per le insegne; suolo nero lucidissimo (roughness ~0,05) che riflette tutto; strisce pedonali = card bianche opache. Auto proxy di profilo con alettone e fari emissivi. Manichino crema in piedi (gonna a cono); ombrello = cono nero opaco su asta, inclinato di ~15 gradi, e testa che gira nei frame del clip. Pioggia = card verticali sottili. Camera 35mm h 0,5 m, DOF moderato, fissa (push in compositing). Shot 24: il whip si applica in compositing identico ai due pannelli.

### S07 - Retro della R34 davanti a Gwanghwamun: quattro fanali tondi e vapore (rif. shot 10, 19)

- **Location.** Viale largo e vuoto nel centro di Seoul (asse di Sejong-daero) di notte dopo la pioggia, dritto verso la porta Gwanghwamun del Gyeongbokgung illuminata: basamento in pietra con tre archi, tetti ricurvi a due livelli illuminati d'oro dal basso, dancheong sotto le gronde, montagna scura dietro. Asfalto a specchio, foschia. (Innesto dal trattamento 'cinema'.)
- **Camera.** 50mm statica, centrata sull'asse del viale, a 70 cm di altezza, circa 4 m dietro l'auto; simmetria perfetta a un punto di fuga; auto ferma nella meta' inferiore, porta dorata che emerge sopra il tetto. Camera fissa su treppiede (push digitale 1,00-1,03 in post). Shot 19 = crop 1,6x in basso a destra su fanali destri, terminale di scarico e vapore (la GT-R R34 di serie ha un solo terminale, a destra: verificare su foto prima del keyframe).
- **Azione.** [0-1,5 s] quattro fanali tondi accesi, un filo di vapore dallo scarico. [1,5 s] i freni si accendono piu' forti: fiammata rossa sull'asfalto bagnato. [1,5-5,0 s] uno sbuffo di vapore sale e si apre nella luce rossa; foschia leggera, riflessi oro e rossi che tremano.
- **Durata clip.** 5 s. **Shot.** 10, 19.
- **Blockout.** Set PALAZZO: strada = lungo piano nero lucido (roughness ~0,08) con linee di corsia tenui; porta = basamento a box con 3 archi (boolean) + due livelli di tetto (lastre scure con angoli rialzati), strisce emissive oro (#E8A84A, strength ~8) sotto le gronde + 3 area light dal basso; montagna = silhouette scura low-poly contro cielo navy (#172435); foschia = volume scatter a bassa densita'. Retro dell'auto proxy: alettone = piastra su due montanti; 4 dischi emissivi rosa-salmone (#FF8A80; 2 grandi esterni, 2 piccoli interni), strength da 6 a 18 nel frame della frenata; targa = rettangolo bianco vuoto; diffusore = box scuro; un solo terminale di scarico (cilindro) a destra; vapore = volume con noise a bassa densita' (o card morbida) che sale dallo scarico. Camera 50mm h 0,7 m centrata, ~4 m dietro l'auto, fissa (push in compositing); lo shot 19 applica lo stesso crop 1,6x al render.

### S08a - Gangnam: cammina verso i fanali e si volta (rif. shot 11, 23)

- **Location.** Strada di Gangnam sotto la pioggia, accanto all'auto ferma; dietro, maxischermi e neon in bokeh.
- **Camera.** 50mm ad altezza petto, camera fissa alle spalle di lei (~2,5 m all'inizio), profondita' di campo ridotta. Auto qualche metro davanti, leggermente a destra, di 3/4 posteriore con i 4 fanali tondi accesi. Lei si allontana e rimpicciolisce nel quadro (da ginocchia in su a meta' stinco in su): niente zoom.
- **Azione.** [0-2,5 s] di spalle cammina lentamente verso il retro dell'auto, l'organza ondeggia, medaglione peonia sulla schiena (shot 23). [2,5-3,5 s] si ferma subito dietro l'auto, tra i fanali. [3,5-5,0 s] gira la testa sopra la spalla sinistra e guarda in camera, corpo ancora di spalle, mani rilassate lungo i fianchi (shot 11). Solo first_frame: se il volto inventato nella girata non coincide con S04, last_frame opzionale lf_S08a (modifica di kf_S08a) oppure S08a_omni.
- **Durata clip.** 5 s. **Shot.** 11, 23.
- **Blockout.** Riusa il set GANGNAM di S06 (blocchi neri con card emissive pastello sfocate dal DOF, suolo nero lucido). Auto proxy di 3/4 posteriore con 4 dischi emissivi rosa-salmone. Manichino crema di spalle con guscio durumagi semitrasparente e disco corallo sulla schiena; sfera bianca grande (peonia) sul lato sinistro dello chignon. La chima lunga nasconde le gambe: la camminata e' una traslazione lungo il percorso del clip con leggero bob verticale e oscillazione della gonna (shape key) - niente walk cycle. Poi rotazione della testa di ~120 gradi sopra la spalla sinistra (empty), tutto sui frame del clip. Camera 50mm fissa h 1,4 m, DOF ~f/2.

### S08b - Gangnam: frontale accanto al cofano, mano ai capelli (rif. shot 15, 16)

- **Location.** La stessa strada di Gangnam di S08a, davanti all'auto: cofano blu bagnato in primo piano a sinistra, neon in bokeh dietro.
- **Camera.** 50mm ad altezza petto, lei frontale accanto al parafango anteriore, nel terzo destro, dalla vita in su; cofano e bordo del parabrezza bagnati in primo piano a sinistra (come shot 15 e 16 del riferimento); profondita' di campo ridotta. Camera fissa. Shot 15 = crop 1,2x, shot 16 = crop 1,3x.
- **Azione.** [0-1,5 s] guarda fuori campo a destra. [1,5-3,5 s] alza la mano sinistra, si sistema una ciocca dietro l'orecchio sinistro con dita sottili e naturali, poi abbassa la mano (shot 15). [3,5-5,0 s] guarda in camera con un accenno di sorriso (shot 16).
- **Durata clip.** 5 s. **Shot.** 15, 16.
- **Blockout.** Riusa il set GANGNAM di S06 (card emissive pastello sfocate dal DOF). Auto proxy: cofano e parafango anteriore blu in primo piano a sinistra, con parabrezza = piano scuro lucido. Manichino crema frontale dalla vita in su nel terzo destro: colletto a Y, fiocco corallo, guscio durumagi semitrasparente, chignon con binyeo e sfera bianca grande sul lato sinistro della testa (a destra nel quadro). Braccio sinistro riggato che sale all'orecchio e torna giu'; tilt della testa da destra verso camera nei frame del clip. Camera 50mm fissa h 1,4 m, DOF ~f/2. Shot 15 e 16: stessi crop 1,2x e 1,3x del pannello Seedance.

### S09 - Davanti ai fari nel vicolo, occhiali da sole (rif. shot 18, 20)

- **Location.** Lo stesso vicolo di Bukchon di S01, con l'auto frontale e i fari accesi.
- **Camera.** 35mm ad altezza vita, frontale e simmetrica. Auto centrata con il muso verso camera; lei subito davanti al cofano, tra i due fari, dalle ginocchia in su. Camera fissa su treppiede (push digitale 1,00-1,03 in post).
- **Azione.** [0-2,5 s] immobile davanti ai fari, in controluce, con gli occhiali cat-eye gia' indossati; pioggia luminosa nei fasci, le nappe del norigae oscillano. [2,6-4,0 s] alza la mano destra, tocca la stanghetta degli occhiali e li sistema, riabbassa la mano (innesto 'fattibile': niente occhiali da infilare, interazione mano-oggetto minima). [4,0-5,0 s] immobile, rivolta all'obiettivo.
- **Durata clip.** 5 s. **Shot.** 18, 20.
- **Blockout.** Riusa il set VICOLO di S01 con l'auto frontale e nuova camera assiale (35mm, h 1,0 m). Fari emissivi molto forti + due spot puntati verso camera per il controluce e il bloom, pioggia volumetrica nei fasci (come shot 18 del riferimento). Manichino crema in piedi centrato davanti al muso (colonna + campana), braccia cilindriche riggate, sfera bianca grande (peonia) sul lato sinistro della testa; occhiali = rettangolo grigio scuro sul volto; la mano destra sale alla tempia e torna giu' nei frame del clip. Lanterne sferiche emissive a muro. Camera fissa (push in compositing).

### S10 - Portiera davanti al minimarket: i piedi scendono (rif. shot 21)

- **Location.** Marciapiede di una via laterale di Seoul davanti a un piccolo minimarket d'angolo senza marchi: luce fluorescente bianca fredda dalla vetrina, frigoriferi sfocati, tavolini e sedie di plastica verdi, ombrellone chiuso, insegna = pannello luminoso bianco vuoto, pozzanghere.
- **Camera.** Bassa, in strada, all'altezza della soglia (~40 cm), 35mm. Vista di 3/4 posteriore del fianco destro dell'auto (lato guida, guida a destra) con la portiera del guidatore aperta verso camera; il minimarket illuminato dietro l'auto, oltre lo stretto marciapiede. Il bordo alto del quadro taglia sulla linea del finestrino: testa e spalle di lei restano fuori campo. Camera fissa.
- **Azione.** [0-1,5 s] portiera aperta, abitacolo buio con un debole bagliore caldo nel vano piedi; si vede solo la meta' inferiore di lei, seduta di lato, una mano che raccoglie la chima. [1,5-3,5 s] esce con i piedi uno dopo l'altro: le scarpe di raso avorio si posano sull'asfalto bagnato, piccola increspatura in una pozzanghera. [3,5-5,0 s] entrambi i tacchi poggiano sull'asfalto, l'orlo della chima si assesta; resta seduta e la testa non entra mai in campo (niente volto: nessun rischio di moderazione). Elegante, nessuna sessualizzazione.
- **Durata clip.** 5 s. **Shot.** 21.
- **Blockout.** Set MINIMARKET: box negozio con grande vetrina = piano emissivo bianco freddo (#EAF4FF, strength ~10); frigoriferi = rettangoli emissivi piu' tenui all'interno; insegna = striscia emissiva bianca vuota; 3 tavolini e sedie verdi (#2E8B57) = cilindri e box; ombrellone chiuso = cono; marciapiede stretto = box con cordolo; strada = piano nero lucido con pozzanghere (roughness variabile). Auto proxy di 3/4 posteriore, fianco destro verso camera, portiera del guidatore come oggetto separato incernierato, aperta a ~70 gradi verso camera; interno scuro con un debole bagliore emissivo caldo nel vano piedi. Bacino, gambe e piedi = capsule crema con scarpe a cuneo avorio animate in uscita; orlo della gonna = guscio a campana avorio; nessuna testa in campo. Camera 35mm h 0,4 m, fissa, bordo alto del quadro sulla linea del finestrino.

### S11 - Corridoio del palazzo verso la stanza hanok: chiusura (rif. shot 26)

- **Location.** Corridoio coperto di un palazzo nello stile del Gyeongbokgung: colonne di legno laccate di rosso, travi dipinte dancheong (verde, rosso, blu), lanterne di carta a coppie, pietra bagnata. In fondo si apre la stanza hanok di S02 con lei seduta al centro.
- **Camera.** 24mm ad altezza occhi, prospettiva centrale perfettamente simmetrica, profondita' di campo ampia. Camera fissa su treppiede (push digitale 1,00-1,03 in post): chiusura calma.
- **Azione.** Lei resta immobile, seduta in posa formale al centro della stanza in fondo, occhi bassi, lineamenti non distinguibili a quella distanza. Le lanterne oscillano appena, gocce cadono dalle gronde ai lati, foschia leggera sul pavimento. Nessun altro movimento.
- **Durata clip.** 5 s. **Shot.** 26.
- **Blockout.** Corridoio: due file di colonne cilindriche rosso scuro, travi a box con fasce di colore piatte (dancheong semplificato), soffitto scuro; lanterne = coppie di sfere emissive bianco-calde (#FFE2B0) appese con leggera oscillazione (driver sinusoidale); pavimento scuro lucido con soglia in pietra in primo piano. In fondo la stanza di S02 riusata tale e quale (parete a griglia emissiva calda, pavimento miele) con il manichino seduto (disco della gonna). Camera 24mm simmetrica h 1,2 m, fissa (push in compositing). Palette marrone e ambra come lo shot 26 del riferimento.

I prompt esatti (keyframe Seedream e clip Seedance) sono in `seedream.json`, `seedance_manifest.json` e `seedance_manifest_omni.json`.

## 8. I 26 shot

Durate in frame identiche al riferimento. "Inizio" e' il tempo nel montaggio, "momento" l'istante nel clip del setup (frame 0 = keyframe). Stesso istante sopra (Blender) e sotto (Seedance).

| n | Frame | Inizio (s) | Setup | Momento nel clip | Descrizione |
|---|---|---|---|---|---|
| 1 | 8 | 0,00 | S01 | 1,00-1,29 s: Inizio del dolly: campo largo, R34 quasi frontale nel vicolo di Bukchon, anabbaglianti accesi, pioggia nei fasci. | Apertura: la R34 Bayside Blue ferma nel vicolo di hanok bagnato, lanterne calde, i fari come luce chiave. |
| 2 | 6 | 0,33 | S02 | 1,00-1,21 s: Lei in piedi, ferma, mani giunte (prima di inginocchiarsi). | In piedi a figura intera al centro della stanza hanok, porte di carta hanji luminose dietro. |
| 3 | 6 | 0,58 | S03 | 1,00-1,21 s: Solo la mano destra appoggiata in cima al volante, polso destro nudo. | Abitacolo con guida a destra: mano sul volante, strumenti accesi, bokeh di neon oltre il parabrezza bagnato. |
| 4 | 6 | 0,83 | S04 | 2,29-2,50 s: Gli occhi salgono verso l'obiettivo (6 frame di micro-movimento). | Primo piano beauty: alza lo sguardo in camera, orecchini d'oro, fondale di carta calda. |
| 5 | 14 | 1,08 | S05a | 1,00-1,54 s: Di spalle, ferma, l'organza mossa dalla brezza. | Di spalle con il medaglione peonia, la N Seoul Tower blu compressa dal tele, il parafango blu in basso a sinistra. |
| 6 | 18 | 1,67 | S03 | 2,21-2,92 s: La mano sinistra, con il bangle di giada, entra e afferra il volante a ore 9. | Due mani sul volante, cruscotto acceso: torna il motivo del volante. |
| 7 | 19 | 2,42 | S06 | 1,00-1,75 s: Lei ferma con l'ombrello nero, i maxischermi cambiano campi di colore. | Campo largo su Gangnam-daero bagnato: auto di profilo, lei accanto con l'ombrello nero, maxischermi astratti. |
| 8 | 10 | 3,21 | S04 | 3,58-3,96 s: Sguardo fisso in camera, battito di ciglia, accenno di sorriso. | Ritorno al viso: contatto visivo pieno. |
| 9 | 14 | 3,62 | S02 | 4,17-4,71 s: Appena seduta in posa formale, frontale, chima aperta a cerchio, ferma. | Seduta formale al centro della stanza, simmetria totale (analogo del seiza). |
| 10 | 10 | 4,21 | S07 | 0,83-1,21 s: Quattro fanali tondi accesi, prima della frenata (che parte a 1,5 s). | Retro della R34 centrato sul viale, la porta Gwanghwamun dorata in fondo: i quattro fanali tondi, firma dell'auto. |
| 11 | 11 | 4,62 | S08a | 4,00-4,42 s: Ferma dietro l'auto, tra i fanali: la testa ruota sopra la spalla sinistra verso camera. | Gangnam: accanto ai fanali posteriori si volta e guarda in camera sopra la spalla. |
| 12 | 15 | 5,08 | S01 | 2,25-2,83 s: Dolly a meta': il doppio lampeggio degli abbaglianti cade ~4 frame dopo il taglio (f125,6 del montaggio, beat 10 a f125,9). | Gli abbaglianti lampeggiano nella pioggia: l'evento che sostituisce i fari a scomparsa. |
| 13 | 11 | 5,71 | S01 | 5,00-5,42 s: Fine del dolly: il faro riempie due terzi del quadro, abbagliante fisso, pioggia in controluce. | Dettaglio del faro acceso, gocce nel fascio. |
| 14 | 14 | 6,17 | S03 | 3,92-4,46 s: Crop 1,4x sulle mani che stringono il volante e flettono le dita. | Stretto sulle mani: le dita stringono la corona, il bangle di giada al polso sinistro. |
| 15 | 13 | 6,75 | S08b | 2,08-2,58 s: Crop 1,2x: la mano sinistra sistema la ciocca dietro l'orecchio sinistro. | Accanto al cofano bagnato alza la mano e si sistema la ciocca dietro l'orecchio, neon in bokeh. |
| 16 | 10 | 7,29 | S08b | 3,58-3,96 s: Crop 1,3x: la ciocca appena sistemata, guarda in camera con un accenno di sorriso. | Piu' stretto: lo sguardo arriva in camera, sorriso appena accennato. |
| 17 | 17 | 7,71 | S02 | 5,29-5,96 s: Crop 1,5x: da seduta gira la testa alla sua destra fino al profilo. | Nella stanza hanok gira il viso di profilo, lo sguardo lungo la stanza. |
| 18 | 10 | 8,42 | S09 | 1,00-1,38 s: Immobile davanti ai fari, in controluce, occhiali scuri. | Davanti al muso della R34, tra i due fari, in controluce con la pioggia luminosa: simmetria. |
| 19 | 11 | 8,83 | S07 | 3,00-3,42 s: Crop 1,6x in basso a destra: fanali destri in frenata e sbuffo di vapore dal terminale di scarico. | Dettaglio basso: fanali rossi e vapore di scarico nella luce rossa, riflessi oro sull'asfalto. |
| 20 | 11 | 9,29 | S09 | 3,00-3,42 s: La mano destra tocca la stanghetta degli occhiali e li sistema. | Si sistema gli occhiali da sole davanti ai fari. |
| 21 | 7 | 9,75 | S10 | 2,21-2,46 s: Le scarpe di raso avorio toccano l'asfalto bagnato. | Portiera aperta davanti al minimarket bianco: i piedi scendono sul bagnato. |
| 22 | 20 | 10,04 | S05a | 3,00-3,79 s: Ancora di spalle, immobile: la brezza solleva l'organza e le nappe, la torre ferma in fondo. | Ritorno al motivo della torre: di spalle verso la N Seoul Tower. |
| 23 | 15 | 10,88 | S08a | 1,00-1,58 s: Cammina di spalle verso i fanali posteriori. | Cammina di spalle verso il retro della R34, medaglione peonia e organza che ondeggia. |
| 24 | 13 | 11,50 | S06 | 3,79-4,29 s: I primi ~5 frame coperti dal whip in post (blur direzionale + scie), poi il campo largo: ombrello inclinato, viso verso camera. | Whip pan che si risolve sul campo largo di Gangnam: auto e ragazza sotto la pioggia. |
| 25 | 25 | 12,04 | S05b | 1,00-2,00 s: Frontale dal basso con gli occhiali cat-eye, torre blu a sinistra, la brezza muove ciocche e orecchini. | Frontale dal basso con gli occhiali e la N Seoul Tower a sinistra: lo shot piu' lungo prima della chiusura. |
| 26 | 22 | 13,08 | S11 | 1,50-2,38 s: Immobile, lanterne che oscillano appena (push digitale in post). | Chiusura: il corridoio del palazzo porta alla stanza hanok, lei seduta al centro in fondo. Calma e simmetria. |
| | **336** | 14,00 | | | |

Controlli fatti dallo script di generazione:
- la somma e' 336 frame;
- ogni istante sta dentro la durata del suo clip;
- ogni setup copre esattamente gli shot dichiarati;
- ogni crop, moltiplicato per il push digitale dove c'e', resta dentro il quadro.

Crop in post, identici sui due pannelli: 14 (1,4x), 15 (1,2x), 16 (1,3x), 17 (1,5x), 19 (1,6x). Lo shot 25 ora e' nativo (S05b e' gia' un mezzo primo piano). Lo shot 24 ha il whip in post sui primi 5 frame.

## 9. Musica (Suno su ePhone)

**Genere.** City pop coreano moderno incontra nu-disco notturno, a 115 BPM nativi: cassa dritta, clap sul 2 e sul 4, basso slap, Rhodes, lead synth lucido, stab sincopati, un accenno di gayageum sintetico. E' un groove pieno dal primo secondo e senza build lungo, come il brano del riferimento (misurato a 115,0 BPM, pieno da ~0,5 s).

**Generazione** (`suno.json`):
- `suno/music`, chirp-v6, strumentale, `custom:false` con `gpt_description_prompt`, durata 40 s, wav;
- seconda chiamata in modalita' custom: soli meta-tag, `max_mode` (0,16 USD), 50 s;
- un eventuale run con chirp-v6-wild.

Ogni chiamata restituisce 2 take. Tutti i campi usati (`title`, `custom`, `prompt`, `max_mode` compresi) sono nello schema ePhone di `suno/music` (vedi `_schema` in `suno.json`).

**Il brano non deve finire nella finestra.** La finestra di 14 s finisce al beat 26,8, a meta' della battuta 7, e i momenti forti della chiusura (f289, f314) non cadono su downbeat. Per questo il prompt chiede un groove continuo, senza break e senza finale prima di 30 s; sub impact, accordo finale, passa-basso e fade si aggiungono in post con `suno/sounds`.

**BPM e finestra.**
- Misurare il BPM di ogni take (autocorrelazione dello spectral flux o librosa).
- Correggere con `suno/adjust-speed`: speed_multiplier = 115 / BPM misurato, keep_pitch.
- Tagliare 14,00 s che partano sul downbeat di una frase di 4 battute, con quel downbeat a ~0,03 s del video.
- Con questo allineamento 13 tagli su 25 cadono sul beat entro +-1,6 frame. Degli altri 12, 3 cadono sugli ottavi (f8, f20, f58) e 9 sono fuori griglia (f40, 111, 122, 148, 185, 223, 234, 241, 261).

Griglia: 1 beat = 12,52 frame, 1 battuta = 50,1 frame. Beat 0 = downbeat; i clap (sul 2 e sul 4) sono i beat 1 e 3 di ogni battuta.

| Frame video | Tempo | Shot | Beat | Accento |
|---|---|---|---|---|
| 0 | 0,00 s | 1 (vicolo) | 0, downbeat battuta 1 | crash + kick |
| 14 | 0,58 s | 3 | 1 (tempo 2, beat a 0,55 s) | clap + stab, comparsa del titolo |
| 26 | 1,08 s | 5 (prima torre) | 2 (tempo 3) | kick |
| 101 | 4,21 s | 10 (fanali e porta dorata) | 8, downbeat battuta 3 | kick + crash |
| 125,6 | 5,23 s | dentro il 12 | 10 (a f125,9) | doppio stab sul lampeggio degli abbaglianti |
| 202 | 8,42 s | 18 (lei nei fari) | 16, downbeat battuta 5 | crash + bass drop, l'accento piu' forte |
| 262-276 | 10,9-11,5 s | 23 -> 24 | 21-22 | riser / reverse cymbal |
| 276 | 11,50 s | 24 (whip) | 22 | picco del whoosh (suno/sounds) |
| 289 | 12,04 s | 25 (frontale con la torre) | 23 (tempo 4 della battuta 6) | sub impact (suno/sounds) |
| 314 | 13,08 s | 26 (corridoio) | 25 (tempo 2 della battuta 7) | accordo finale (suno/sounds) + passa-basso e fade sul groove, coda fino a 14,00 s |

Le durate degli shot non si toccano: si sposta solo l'offset del brano (`audio.offset_s` nell'EDL; valore positivo = salta l'inizio del file).

Alternativa da valutare sul take scelto: downbeat a 0,552 s (`audio.offset_s` = istante del downbeat - 0,552). Restano 13 tagli sul beat e i downbeat cadono su f14, f163, f213 e f314, quindi l'accordo finale cade sul downbeat della battuta 7. Il prezzo: la tabella va rinumerata e l'accento piu' forte (crash + bass drop) passa dallo shot 18 (f202) allo shot 19 (f213).

## 10. Ordine di produzione e costi

1. **Riferimenti Seedream** (`seedream.json`, primi 8 job): ref_ragazza (W1, volto), ref_ragazza_figura (W3), ref_ragazza_schiena (W4), ref_ragazza_costume (W5, hanbok tagliato alla clavicola, senza volto), ref_auto (C1), ref_auto_retro (C2), ref_auto_profilo (C3, fianco sinistro), ref_auto_interno (C4). Parametri: 2K, png, watermark false, seed fisso. Si approvano a vista: silhouette coreana dell'hanbok, R34 con fari angolari fissi e un solo terminale.
   - Lancio di un job: `J=pubblicita/progetti/seoul_neon/seedream.json; ID=kf_S01; python3 -m pubblicita.ephone image --id $ID --prompt "$(jq -r --arg id $ID '.jobs[]|select(.id==$id).prompt' $J)" --aspect-ratio "$(jq -r --arg id $ID '.jobs[]|select(.id==$id).aspect_ratio' $J)" $(jq -r --arg id $ID '.jobs[]|select(.id==$id).images[]|"--ref "+.' $J) --size 2K --seed 34115 --yes`, dalla radice del repo. Il comando `batch` non legge `seedream.json`; il comando `image` usa 16:9 se non gli si passa il rapporto, e le virgolette di jq evitano che gli apostrofi dei prompt rompano la shell.
2. **Keyframe.** kf_S01 diventa il riferimento NOTTE, kf_S02 il riferimento CALDO; chi li usa per il grade ha la frase "color grade only: ignore its subject, car, location and composition". Poi gli altri keyframe (kf_S05b dopo kf_S05a, kf_S08b dopo kf_S08a) e il last_frame lf_S02.
   - Ogni last_frame e' una modifica del suo keyframe (immagine 1: "Edit image 1. Keep everything in image 1 exactly as it is ... Change only THE WOMAN"). Prima di usarlo, confrontare kf e lf fuori dalla sagoma di lei: se sfondo, auto o luci si sono mossi, niente last_frame.
3. **Test di moderazione dei volti**: voce `S04_t480` del manifest (480p, 5 s, ~0,43 USD), lanciata da sola con `--only S04_t480`. Scrive `S04_t480.mp4` e non tocca `S04.mp4`; il batch completo poi la salta.
   - (a) keyframe passato come file;
   - (b) se rifiutato (400, non addebitato): `ephone asset upload` e `asset://ID`;
   - (c) se rifiutato anche cosi': `S04_testo` (solo testo, output Seedance = canale fidato) dal manifest omni, caricato come asset e usato come riferimento di volto (piano C).
4. **Setup senza volto**, subito a 1080p: S01, S07, S03, S10, S11, S05a.
5. **S04 e i setup con volto**: S02, S06, S09, S05b, S08a, S08b. S02 con first_frame + last_frame. S08a ha il volto solo nel clip (parte di spalle): va dopo S04 per confrontarlo; se il volto inventato nella girata (shot 11) non coincide, lf_S08a (job opzionale) come last_frame, oppure S08a_omni.
6. **Controllo dei clip**: nel sidecar `<id>.json` accanto a ogni clip larghezza e altezza devono essere 1920x1080 (aspect_ratio e' `adaptive`, come chiede ePhone per i first_frame). Se no, rigenerare: `montaggio/render.py` adatterebbe il clip in silenzio e crop e camera Blender non tornerebbero.
7. **Blockout Blender** su ogni clip:
   - camera match con fSpy sul primo frame (le camere sono tutte fisse, tranne il dolly di S01), oppure clip come sfondo al 50%;
   - sensore 36 mm, 1920x1080, 24 fps;
   - animazioni sui frame reali del clip;
   - set riusati: vicolo (S01, S09), torre (S05a, S05b), Gangnam (S06, S08a, S08b), hanok (S02, S11), auto proxy unica.
8. **Musica**: Suno, misura del BPM, adjust-speed, finestra da 14 s, rinforzi con `suno/sounds`.
9. **Montaggio** (`edl_bozza.json`): rifinire gli `in` sui clip veri (+-0,5 s), crop, push e whip identici sopra e sotto. `montaggio/render.py` oggi ignora `crop` e `fx`, che vanno ancora implementati. Se un setup passa all'omni cambia solo `bottom.src` (`seedance/<setup>_omni.mp4`).
10. **Impaginazione** 1080x1920: header "Opus 5.5", pillole "Blender" e "Seedance 2.5".

| Voce | Stima |
|---|---|
| Seedance 2.5, 67 s a 1080p (una take per setup) | ~3,26 M token, ~226 CNY, **~32 USD** |
| Retake (Seedance 2.5 non accetta seed) | +50-100% -> 48-65 USD |
| Test 480p / 5 s (S04_t480, S03_omni_t480) | ~0,43 USD a tentativo |
| Seedream 5.0 Pro, 22 immagini 2K (+1 opzionale) | ~2 USD |
| Suno, 2-3 chiamate | ~0,2-0,4 USD |

## 11. Rischi e ripieghi

| Rischio | Dove | Ripiego |
|---|---|---|
| Volto rifiutato in input | S04, S02, S06, S09, S05b, S08b (S08a solo con lf_S08a) | asset:// -> omni-reference (id `<setup>_omni`) -> ancora S04_testo da testo (piano C) |
| Volto inventato nella girata | S08a (shot 11) | lf_S08a come last_frame (modifica di kf_S08a), oppure S08a_omni con ref_ragazza |
| La chima "morpha" mentre si inginocchia | S02 | last_frame lf_S02 gia' previsto; altrimenti lf_S02 come first_frame (gia' seduta): lo shot 2 usa il campo largo seduto, 9 e 17 restano |
| Il last_frame sposta lo sfondo | S02 (e lf_S08a) | lf generato come modifica del keyframe; se la differenza fuori dalla sagoma non e' nulla, niente last_frame |
| Mano ai capelli deformata | S08b (15, 16) | togliere il gesto dal prompt: 15 diventa lo sguardo fuori campo, 16 lo sguardo in camera |
| Mani sul volante | S03 | lock "five fingers"; ripiego: una sola mano (versione "fattibile") |
| Volto che entra in campo | S10, S11 | S10 taglia sulla linea del finestrino e lei non si alza; S11 occhi bassi e figura piccola |
| Testo, volti o loghi nei maxischermi | Gangnam, minimarket, palazzo | maxischermi a soli campi di colore e fuori fuoco, insegne illeggibili, targa vuota; nel caso, sfocatura in post sul solo pannello inferiore |
| Auto che diventa un ibrido | tutti | ref_auto approvato come master, moduli per vista (niente fanali tondi nelle viste frontali), lock per vista; rifiutare ogni keyframe sbagliato |
| Clip non 1920x1080 | tutti (aspect_ratio adaptive) | controllo del sidecar prima del blockout; rigenerare |
| Ruoli @imageN ignorati | manifest omni | test S03_omni_t480; se serve, forma "image 1", "image 2" |
| Tempi d'azione non rispettati al frame | tutti | gli `in` dell'EDL si ricalcolano sui clip veri (margine minimo 12 frame); il blockout segue il clip, non il prompt |

## 12. File del progetto

| File | Contenuto |
|---|---|
| `TRATTAMENTO.md` | questo documento |
| `shotlist.json` | personaggio, auto, moduli di prompt e lock, 13 setup (con note di blockout e push), 26 shot con start_frame, istante nel clip e crop |
| `seedream.json` | 22 job Seedream 5.0 Pro in ordine di dipendenza (8 riferimenti, 13 keyframe, 1 last_frame) + lf_S08a opzionale, con il comando di lancio |
| `seedance_manifest.json` | test S04_t480 + 13 clip Seedance 2.5 in modalita' first_frame (S02 anche con last_frame), da lanciare cosi' com'e' con `python3 -m pubblicita.ephone batch` |
| `seedance_manifest_omni.json` | test S03_omni_t480 + gli stessi 13 setup in modalita' reference_images con id `<setup>_omni` + S04_testo (piano C); sempre con `--only` |
| `suno.json` | brano strumentale a 115 BPM: chiamata principale, alternativa custom, schema verificato, procedura BPM, finestra e accenti |
| `edl_bozza.json` | EDL dei 26 tagli (sopra blender/<setup>.mp4, sotto seedance/<setup>.mp4, stesso `in`), con crop, push e whip annotati |

Percorsi: nei due manifest le immagini sono relative alla cartella del manifest (`../../output/seedream/<id>.png`), come le risolve `ephone batch`; in `seedream.json` sono relative alla radice del repo, perche' si lanciano con il comando `image` da li'. Gli output vanno sempre in `pubblicita/output/`.

## 13. Revisione 2: cosa e' cambiato

- **S05 diviso** in S05a (5 s, di spalle e immobile: shot 5 e 22) e S05b (4 s, nuovo keyframe frontale dal basso con occhiali e torre a sinistra: shot 25 nativo a 1,00-2,00 s). Niente piu' girata di 180 gradi in gonna e organza; lf_S05 eliminato.
- **S08 diviso** in S08a (5 s: cammina, si ferma tra i fanali, si volta: shot 23 e 11) e S08b (5 s, nuovo keyframe frontale accanto al cofano: shot 15 e 16 con crop 1,2x e 1,3x). lf_S08 eliminato; lf_S08a resta come opzione, ma come modifica del keyframe.
- **S02 a 7 s** con first_frame + last_frame lf_S02 (seduta di profilo, modifica di kf_S02, anche ripiego). Shot 9 a 100, shot 17 a 127; la girata va alla sua destra (sinistra schermo), lungo la stanza.
- **Margini**: ogni shot ha almeno 12 frame prima della fine del clip. Shot 13 a 120 (fine del dolly a 5,0 s), shot 10 a 20 (prima della frenata), shot 12 a 54 (lampeggio sul beat 10).
- **Camera fissa ovunque** tranne il dolly di S01; micro push-in sostituito dal push digitale 1,00-1,03 nell'EDL.
- **Prompt Seedream a moduli** (composizione prima), peonia grande dietro l'orecchio sinistro, negazioni con nomi propri sostituite, riferimenti di grade che dichiarano di ignorare soggetto e composizione, ref_ragazza come scatto singolo.
- **Geometria e dettagli**: S01 con vicolo che fugge verso il centro e auto quasi frontale; S03 con il bangle sul polso sinistro; S06 con ombrello nero, profondita' di campo moderata e maxischermi astratti; S07 a 4 m e 70 cm, un solo terminale di scarico, crop dello shot 19 in basso a destra; S10 con testa fuori campo e lei che resta seduta; S11 occhi bassi.
- **Manifest**: percorsi relativi alla cartella del manifest (si lanciano cosi' come sono), test con id propri (S04_t480, S03_omni_t480), id omni `<setup>_omni`, piano C come voce vera (S04_testo), riferimenti senza volto per i setup senza volto (ref_ragazza_costume, ref_ragazza_schiena), lock dell'auto per vista.
- **Musica**: niente finale chiesto a Suno (la finestra finisce a meta' battuta); chiusura e impatti in post; corrette le affermazioni sulla griglia (ottavi, clap, beat 1 a 0,55 s).
