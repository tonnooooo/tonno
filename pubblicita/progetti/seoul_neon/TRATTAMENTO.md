# Seoul neon: trattamento finale

Spot verticale 1080x1920 nel formato del reel @themira.creators ("26 shots, cut to 115 BPM / Blender blockout + one prompt"): due pannelli 16:9 sincronizzati, sopra il blockout Blender, sotto il render fotorealistico. Header "Opus 5.5", etichette a pillola "Blender" (sopra) e "Seedance 2.5" (sotto, al posto di "Mira AI x After Effects" del riferimento). 26 shot con le durate esatte del riferimento: 336 frame, 14,0 s a 24 fps, musica a 115 BPM.

Pipeline: keyframe Seedream 5.0 Pro, poi clip Seedance 2.5 (1080p, muti, uno per setup), poi blockout Blender costruiti sopra ogni clip (stessa camera e stesso movimento), poi montaggio sincrono dei due pannelli e impaginazione.

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

**A "fedele".** Pro: mappa 1:1 dei 26 shot sui setup del riferimento, con gli stessi riusi (vicolo 1/12/13, stanza 2/9/17, volante 3/6/14, viso 4/8, torre 5/22/25, citta' 7/11/15/16/23/24). Il dolly unico di S01 da' campo largo, medio e dettaglio del faro nativi, senza crop. Mappa degli accenti musicali precisa. Contro: azioni rischiose per Seedance (girata di 180 gradi in S05, inginocchiarsi in chima in S02, infilarsi gli occhiali con due mani in S09, tre azioni in 8 s in S08). Il palazzo compare solo come corridoio, il vicolo in 7 shot su 26.

**B "cinema".** Pro: arco narrativo arrivo / incontro / partenza, immagini forti (silhouette nei fari, ramyeon al minimarket, quattro punti rossi sotto Gwanghwamun). Contro: l'ordine e il ruolo dei setup si allontanano dal riferimento (shot 2 volante, shot 3 portiera, chiusura sull'auto invece che sul corridoio). Il passaggio ad alta velocita' generato (S11) rischia lo smear, il ramyeon mette insieme mani, bicchiere e vapore, ci sono due dolly lunghi da ricostruire.

**C "fattibile".** Pro: grammatica di camera minima (fissa o un solo dolly), mani quasi sempre nascoste, girate di testa al posto dei gesti con oggetti, blockout semplice (gonna a cono, camminata come traslazione), set condivisi, Gwanghwamun come campo largo. Contro: i gesti del riferimento (capelli, occhiali) diventano sguardi e lo spot perde vita; gli shot 15/16 passano al palazzo e al viso; il whip si risolve sul minimarket invece che sul campo largo cittadino.

**Scelta: A come base**, perche' e' l'unico che rifa' davvero lo spot inquadratura per inquadratura. Innesti:

- **Da C (fattibilita').**
  - S09: gli occhiali sono gia' indossati e una mano li sistema alla stanghetta. Niente occhiali da infilare con due mani.
  - S10: testa e spalle restano nell'ombra dell'abitacolo. Il volto non si vede, quindi niente rischio di moderazione.
  - In ogni clip con mani: lock "natural hands, five fingers". Camera fissa o un solo dolly lineare.
  - Ripieghi dichiarati: S05 con la sola girata della testa, S08 senza il gesto della mano, S02 gia' seduta.
  - Blockout semplificato: gonna a cono, camminata come traslazione con bob, girate come rotazioni su un empty.
  - I crop in post si applicano identici al render Blender. I momenti si ri-temporizzano di +-0,5 s sui clip veri.
  - Lo shot 12 parte 3 frame prima del lampeggio, che cade cosi' sul beat 10.
- **Da B (impatto).**
  - S07, il retro della R34 con i quattro fanali tondi (shot 10, 19), si sposta dal vicolo al viale davanti alla porta Gwanghwamun illuminata d'oro. Il palazzo diventa un esterno iconico, oltre al corridoio di chiusura, e il vicolo scende da 7 a 5 shot.
  - Coloritura di gayageum nella musica.
  - La lettura dello sguardo che cresce lungo lo spot.

## 3. Look e palette

**Formato.**
- Fondo off-white con onde sottili verde acqua.
- Header: logo e "Opus 5.5". "Opus" compare a ~0,5 s, "5.5" entro 0,75 s, sullo stab del beat a 0,58 s.
- Due pannelli 16:9 larghi ~1048 px, angoli arrotondati, ombra morbida, pillola in alto a sinistra: "Blender" sopra, "Seedance 2.5" sotto.
- Clip a 1080p: i crop arrivano al massimo a 1,6x (1200 px nativi per un pannello da ~1048 px), senza upscale.

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
- 50mm: abitacolo, Gangnam stretto, retro davanti al palazzo.
- 85mm: viso e torre (compressione).
- Camera bassa per l'auto (40-60 cm), altezza occhi per i ritratti.

**Composizione e movimento.** Simmetrie a un punto di fuga (fari, stanza, retro con la porta, corridoio), terzi con la torre, diagonali nei 3/4 dell'auto. Camera quasi sempre ferma con micro push-in; l'unico movimento vero e' il dolly di S01. Il resto lo fanno soggetto, luci, pioggia e montaggio. L'unico whip (shot 24) si fa in post, identico nei due pannelli.

**Pannello superiore (Blender).** EEVEE con la stessa palette del clip (navy di notte, beige negli interni), ombre morbide, riflessi in screen space, bloom leggero.
- Manichino in argilla crema senza volto. Chignon = sfera nera con binyeo bianco orizzontale e piccola sfera bianca.
- Auto = box low-poly blu con fari emissivi bianchi e 4 dischi rosa-salmone.
- Maxischermi = card emissive pastello. Lanterne = sfere emissive. Torre = traliccio wireframe bianco.
- Pavimenti lucidi riflettenti.

**Niente testo nell'immagine.** Insegne come bagliori astratti, insegna del minimarket vuota, targhe bianche vuote, strumenti sfocati, nessuna bandiera.

## 4. Personaggio

Donna coreana adulta sui 25 anni, viso ovale, sguardo calmo. Capelli neri lucidi in uno chignon basso (jjokjin meori) con un lungo binyeo d'argento orizzontale e una piccola peonia di seta avorio; due ciocche sottili libere ai lati del viso, servono per il gesto di S08. Orecchini pendenti d'oro, bangle di giada.

Hanbok moderno:
- jeogori corto avorio con colletto bianco a Y e nastro otgoreum corallo;
- chima avorio a vita alta fino alla caviglia, con orlo a peonie in foglia d'oro;
- durumagi aperto in organza avorio trasparente con un grande medaglione a peonia corallo e oro tra le scapole (sostituisce il fiocco dell'obi del riferimento);
- norigae corallo e prugna;
- scarpe di raso avorio.

Occhiali cat-eye scuri solo in S05 e S09. Mai "geisha" o "gisaeng", eta' adulta sempre esplicita, nessuna sessualizzazione.

Testo canonico, da incollare identico in ogni keyframe Seedream:

```text
THE WOMAN: an adult Korean woman in her mid-20s, slim and poised, oval face with soft cheekbones, calm dark-brown almond eyes, straight natural brows, real skin texture, muted coral-rose lips, minimal makeup. Glossy jet-black hair parted in the center and gathered into a low chignon at the nape, two fine loose strands framing her face, one long horizontal silver binyeo hairpin with jade tips through the knot and a small ivory silk peony tucked beside it. Long gold drop earrings, a slim green jade bangle on her left wrist. She wears a modern Korean hanbok: a short cropped ivory silk jeogori jacket with a crisp white dongjeong collar crossing in a Y, gently curved sleeves and a long coral otgoreum ribbon tied in a bow on the chest; a high-waisted, full, ankle-length ivory silk chima skirt with a fine gold-leaf peony pattern along the hem; a sheer ivory silk-organza durumagi overcoat worn open, with a large coral-and-gold embroidered peony medallion between the shoulder blades; a coral-and-plum norigae tassel hanging from the ribbon; ivory satin heels. Korean hanbok, not a kimono: no obi belt, no wide kimono sleeves.
```

Nei prompt Seedance si usano solo i lock brevi: `THE WOMAN (the same Korean woman in her mid-20s from the first frame)` e `Face, low chignon with silver binyeo and ivory hanbok unchanged.`

## 5. Auto

Nissan Skyline R34 GT-R coupe in Bayside Blue, metallizzato lucido. Profilo squadrato a cuneo, passaruota gonfi, fari angolari a proiettore, paraurti con intercooler a vista, cofano con presa in carbonio, alettone alto, quattro fanali tondi (la firma), cerchi canna di fucile. Guida a destra, coerente in abitacolo (S03), portiera (S10) e blockout.

La R34 non ha fari a scomparsa: lo shot 12 diventa il doppio lampeggio degli abbaglianti. Targa bianca vuota, nessun badge leggibile.

```text
THE CAR: one single late-1990s Nissan Skyline R34 GT-R two-door coupe in Bayside Blue, a vivid metallic mid-blue with a deep glossy clearcoat that mirrors every light. Boxy wedge-shaped body, short overhangs, pumped wheel arches, sharp angular projector headlights, aggressive front bumper with a wide mesh intake showing the intercooler, carbon front splitter and carbon hood vent; tall adjustable rear wing, four round taillights (two large outer, two smaller inner), rear diffuser; dark gunmetal multi-spoke 18-inch wheels. Right-hand-drive interior: black three-spoke steering wheel, analog gauges, small central multi-function display, six-speed shifter. Blank white license plate, no badges, no readable lettering. Not an AE86, not a Supra, not an R35.
```

Lock Seedance: `THE CAR (the same Bayside Blue R34 GT-R coupe from the first frame)` e `Car shape, Bayside Blue paint and four round taillights unchanged, blank license plate.`

## 6. Dai luoghi del riferimento a Seoul

| Riferimento (Tokyo) | Seoul | Shot | Setup |
|---|---|---|---|
| vicolo di legno con lanterne | vicolo di hanok a Bukchon | 1, 12, 13, 18, 20 | S01, S09 |
| retro auto nel vicolo | retro auto sul viale davanti a Gwanghwamun | 10, 19 | S07 |
| stanza tatami | stanza hanok (hanji, ondol) | 2, 9, 17 | S02 |
| volante | volante con guida a destra | 3, 6, 14 | S03 |
| viso | viso, fondale di hanji | 4, 8 | S04 |
| Tokyo Tower | N Seoul Tower blu sul Namsan | 5, 22, 25 | S05 |
| incrocio di Shibuya | Gangnam-daero | 7, 11, 15, 16, 23, 24 | S06, S08 |
| portiera | portiera davanti al minimarket | 21 | S10 |
| corridoio verso la stanza | corridoio del palazzo (stile Gyeongbokgung) verso la stanza hanok | 26 | S11 |

## 7. Setup (11 clip Seedance)

| ID | Setup | Durata | Shot | Input Seedance | Volto visibile |
|---|---|---|---|---|---|
| S01 | Vicolo di Bukchon: R34 3/4 frontale, abbaglianti (rif. shot 1, 12, 13) | 6 s | 1, 12, 13 | first_frame | no |
| S02 | Stanza hanok: in piedi, seduta formale, profilo (rif. shot 2, 9, 17) | 6 s | 2, 9, 17 | first_frame | si |
| S03 | Abitacolo con guida a destra: mani sul volante (rif. shot 3, 6, 14) | 5 s | 3, 6, 14 | first_frame | no |
| S04 | Primo piano beauty: clip ancora d'identita' (rif. shot 4, 8) | 5 s | 4, 8 | first_frame | si |
| S05 | Di spalle con la N Seoul Tower, poi si gira con gli occhiali (rif. shot 5, 22, 25) | 7 s | 5, 22, 25 | first_frame+last_frame | si |
| S06 | Gangnam-daero: campo largo con ombrello trasparente (rif. shot 7, 24) | 5 s | 7, 24 | first_frame | si |
| S07 | Retro della R34 davanti a Gwanghwamun: quattro fanali tondi e vapore (rif. shot 10, 19) | 5 s | 10, 19 | first_frame | no |
| S08 | Gangnam: cammina verso i fanali, si volta, mano ai capelli (rif. shot 11, 15, 16, 23) | 8 s | 11, 15, 16, 23 | first_frame+last_frame | si |
| S09 | Davanti ai fari nel vicolo, occhiali da sole (rif. shot 18, 20) | 5 s | 18, 20 | first_frame | si |
| S10 | Portiera davanti al minimarket: i piedi scendono (rif. shot 21) | 5 s | 21 | first_frame | no |
| S11 | Corridoio del palazzo verso la stanza hanok: chiusura (rif. shot 26) | 5 s | 26 | first_frame | no |
| | **Totale** | **62 s** | 26 | | |

### S01 - Vicolo di Bukchon: R34 3/4 frontale, abbaglianti (rif. shot 1, 12, 13)

- **Location.** Bukchon Hanok Village (Gahoe-dong), vicolo stretto in salita, notte dopo la pioggia: muri di pietra e intonaco, gronde di tegole nere ricurve, portoni di legno, lanterne di carta calde, lastricato bagnato. Stesso set di S09.
- **Camera.** 35mm ad altezza paraurti (60 cm). Un solo movimento: dolly-in continuo e liscio con ease-in/out in 6 s, dal 3/4 frontale largo (~6 m, auto nella meta' centro-destra, vicolo che fugge a sinistra) al dettaglio del faro piu' vicino (~1,5 m).
- **Azione.** [0-2,3 s] auto ferma, anabbaglianti accesi, pioggia nei fasci. [2,4 s] gli abbaglianti lampeggiano due volte e restano accesi (sostituisce i fari a scomparsa dello shot 12, che la R34 non ha). [3-6 s] luce piena, la camera arriva sul faro (shot 13 nativo, senza crop).
- **Durata clip.** 6 s. **Shot.** 1, 12, 13.
- **Blockout.** Set VICOLO (riusato da S09): due pareti con zoccolo di pietra grigio, intonaco chiaro e fascia di gronda nera sporgente 0,6 m con estremita' rialzate; portoni = pannelli scuri incassati; lanterne = sfere emissive bianco-ambra (#FFB866, strength ~6) in fila verso il punto di fuga; pavimento a lastre lucide (roughness 0,08-0,12). Auto proxy R34 (riusata in tutto lo spot): box smussato blu (#1F5FAE desaturato), cabina trapezoidale, alettone = piastra su due montanti, presa anteriore scura, ruote = cilindri neri. Fari = due rettangoli emissivi bianchi angolati: strength 8 fino al frame del lampeggio, poi 30/8/30/8 e fisso a 30 (copiare i frame esatti dal clip); indicatori = piccoli rettangoli ambra; due spot nei fari con volumetrica leggera per i fasci. Pioggia = card verticali sottili leggibili solo nei fasci. Camera 35mm, sensore 36 mm, 1920x1080, 24 fps, h 0,6 m; dolly in linea retta da A a B con le stesse curve del clip (clip come sfondo al 50%, verificare primo e ultimo frame). World navy scuro, EEVEE con ombre morbide, SSR e bloom leggero.

### S02 - Stanza hanok: in piedi, seduta formale, profilo (rif. shot 2, 9, 17)

- **Location.** Stanza di hanok di notte: porte a graticcio con carta hanji retroilluminata, pavimento ondol in carta oliata color miele lucido, trave scura, paravento basso con peonie sbiadite al bordo destro. E' la stessa stanza in fondo al corridoio di S11.
- **Camera.** 35mm ad altezza vita, frontale e perfettamente simmetrica, lei a figura intera nel terzo centrale. Camera fissa con push-in minimo (pochi cm). Shot 17 = crop 1,5x centrato su di lei seduta.
- **Azione.** [0-1,8 s] in piedi, mani giunte in vita, respira. [1,8-4,0 s] si inginocchia lentamente nella seduta formale, la chima si apre a cerchio sul pavimento (analogo del seiza dello shot 9). [4,0-4,8 s] immobile, sguardo in camera. [4,8-6,0 s] gira la testa a destra fino al profilo, verso la porta di carta (analogo della girata dello shot 17).
- **Durata clip.** 6 s. **Shot.** 2, 9, 17.
- **Blockout.** Set HANOK (riusato in fondo al corridoio di S11): scatola 4x4 m; parete di fondo = griglia di montanti scuri sottili (#3B2A1A) con pannelli emissivi caldi e deboli (#F3DDB0, strength 2-3) per la hanji retroilluminata; pavimento miele lucido (#B88E55, roughness ~0,25) con riflesso morbido; trave scura in alto; paravento = piano a due tinte. Manichino in argilla crema riggato (testa a uovo senza tratti, collo cilindrico), corpo a colonna che si allarga a campana per la chima; chignon = sfera nera bassa con bastoncino bianco orizzontale (binyeo) e piccola sfera bianca (peonia); nastro corallo = card sul petto (#D9603B). Animazione sui frame del clip: in piedi -> inginocchiata (bacino che scende, la campana si schiaccia in un disco con shape key) -> testa ruotata di ~80 gradi a destra. Camera 35mm frontale h ~1,0 m, micro push-in. Luci: grande area light calda dietro la parete di carta + fill caldo da sinistra camera. Monocromo seppia identico al finale.

### S03 - Abitacolo con guida a destra: mani sul volante (rif. shot 3, 6, 14)

- **Location.** Dentro la R34 (guida a destra) che avanza piano nella pioggia notturna di Seoul; parabrezza con gocce, neon sfocati oltre il vetro.
- **Camera.** Over-the-shoulder dal sedile posteriore, dietro e a sinistra della spalla sinistra di lei (lei siede a destra): spalla avorio in primo piano a destra. 50mm, profondita' di campo minima, fuoco su mani e corona del volante. Camera solidale all'auto, ferma. Shot 14 = crop 1,4x sulle mani.
- **Azione.** [0-1,6 s] mano destra appoggiata in cima al volante (ore 12). [1,6-3,2 s] la mano sinistra sale e afferra il volante a ore 9. [3,2-5,0 s] entrambe le mani stringono, le dita si flettono, piccola correzione di sterzo. Il bokeh dei neon scivola piano verso sinistra sul parabrezza. Volto fuori campo.
- **Durata clip.** 5 s. **Shot.** 3, 6, 14.
- **Blockout.** Set INTERNO: plancia = box scuro smussato (#141414) con cupola strumenti, due dischi emissivi bianco-ambra (#FF9A3C, strength ~3) e un piccolo rettangolo emissivo al centro (MFD, nessun numero). Volante = toro nero sottile + tre razze + mozzo, rotazione di pochi gradi copiata dal clip. Parabrezza = piano inclinato; dietro, una card emissiva grande con macchie sfocate magenta/ciano/ambra la cui UV scorre verso sinistra alla velocita' del clip. Spalla e braccio del manichino in argilla crema in primo piano a destra; mani semplificate (palmo a box, dita a capsule) riggate per la presa; bangle = toro verde sottile. Camera 50mm imparentata a un empty dell'auto (noise di 1-2 mm per la vibrazione), DOF ~f/1.8 a fuoco sulla corona. Lato guida a destra, coerente con S10.

### S04 - Primo piano beauty: clip ancora d'identita' (rif. shot 4, 8)

- **Location.** Interno hanok: fondale di carta hanji beige caldo, completamente fuori fuoco.
- **Camera.** Primo piano frontale dal petto in su, centrato, 85mm ad altezza occhi, profondita' di campo minima. Camera fissa con push-in di pochi cm.
- **Azione.** [0-2,0 s] sguardo leggermente in basso a sinistra. [2,0-3,0 s] alza gli occhi nell'obiettivo. [3,0-5,0 s] tiene lo sguardo, un battito di ciglia lento, accenno di sorriso, gli orecchini oscillano appena. E' il clip del test di moderazione dei volti: si genera per primo (480p/4 s).
- **Durata clip.** 5 s. **Shot.** 4, 8.
- **Blockout.** Set RITRATTO: testa = ovoide crema senza tratti su collo cilindrico (come shot 4 e 8 del riferimento); colletto bianco a Y (due card incrociate) e fiocco corallo; chignon nero dietro la testa con il binyeo bianco che sporge ai lati e una piccola sfera bianca (peonia); orecchini = due capsule oro (#C9A24B) pendenti con oscillazione smorzata (noise). Fondale = piano beige caldo (#876E4D) con leggero gradiente. Il manichino non ha occhi: lo sguardo che sale si rende con un tilt della testa di ~5-8 gradi verso l'alto nei frame in cui lei alza gli occhi. Luce: grande area light morbida frontale + rim caldo debole. Camera 85mm ad altezza occhi, DOF f/1.8, micro push-in di 3-5 cm.

### S05 - Di spalle con la N Seoul Tower, poi si gira con gli occhiali (rif. shot 5, 22, 25)

- **Location.** Strada panoramica in collina sopra Seoul, di notte. In lontananza la N Seoul Tower illuminata di blu sul Namsan, sopra il tappeto di luci della citta': il blu della torre fa rima con il Bayside Blue.
- **Camera.** 85mm ad altezza petto: il tele comprime e ingigantisce la torre. Lei a sinistra del centro dalla vita in su, torre al centro-destra, parafango e cofano blu in basso a sinistra. Camera fissa con micro push-in. Shot 25 = crop 1,3x su viso e busto con la torre nel quadro.
- **Azione.** [0-2,8 s] di spalle guarda la torre; la brezza muove l'organza del durumagi (medaglione peonia sulla schiena) e le nappe del norigae. [2,8-5,2 s] si gira lentamente verso camera; porta gia' gli occhiali da sole cat-eye scuri (di spalle se ne vedono solo le stanghette). [5,2-7,0 s] frontale e immobile, mento appena alzato, torre blu dietro. first_frame + last_frame per fissare il volto dopo la girata. Ripiego: solo girata della testa sopra la spalla destra (versione 'fattibile').
- **Durata clip.** 7 s. **Shot.** 5, 22, 25.
- **Blockout.** Set TORRE: cielo = colore del mondo navy (#172435) con lieve gradiente; torre = traliccio wireframe bianco sottile (fusto conico, disco dell'osservatorio, antenna) con anello emissivo azzurro (#5DA9FF), a destra e in grande scala come la torre del riferimento; skyline = blocchi neri bassi; luci della citta' = migliaia di sferette emissive calde (instancing) sfocate dal DOF. Auto proxy: porzione di box blu smussato in basso a sinistra. Manichino di spalle: durumagi = guscio a campana semitrasparente (alpha ~0,4) con disco corallo sulla schiena (medaglione); chignon nero + binyeo bianco orizzontale + sfera bianca; occhiali = rettangolo grigio scuro, visibile dopo la girata; nappe del norigae con leggero cloth o shape key. Animazione: rotazione del manichino di 180 gradi sul proprio asse nei frame della girata del clip. Camera 85mm h 1,4 m, DOF moderato (f/2.8), micro push-in. Rim freddo dal lato della torre.

### S06 - Gangnam-daero: campo largo con ombrello trasparente (rif. shot 7, 24)

- **Location.** Gangnam-daero di notte sotto la pioggia: viale largo, torri di vetro, maxischermi LED con forme astratte, insegne al neon illeggibili, strisce pedonali, asfalto bagnato a specchio.
- **Camera.** Campo largo ad altezza ginocchio (~50 cm), 35mm, profondita' di campo ampia, orizzonte in bolla. Auto di profilo con il muso a sinistra, al centro-basso; lei in piedi accanto al parafango anteriore. Camera fissa con micro push-in. Shot 24: whip pan fatto in post (blur direzionale + scie per ~5 frame) che si risolve su questo campo largo.
- **Azione.** [0-2,5 s] pioggia fitta, gocce che rimbalzano, i maxischermi cambiano colore lentamente, scie di traffico lontane. [2,5-5,0 s] lei inclina l'ombrello all'indietro e gira il viso verso camera.
- **Durata clip.** 5 s. **Shot.** 7, 24.
- **Blockout.** Set GANGNAM (stesso linguaggio dello Shibuya del riferimento, riusato da S08): blocchi neri alti (#0B0D10) con card emissive pastello (menta #CDE4DD, rosa #F2B8CF, lavanda #CBB8F0, bianco) al posto dei maxischermi, con color ramp animata per il cambio colore; strisce emissive sottili per le insegne; suolo nero lucidissimo (roughness ~0,05) che riflette tutto; strisce pedonali = card bianche opache. Auto proxy di profilo con alettone e fari emissivi. Manichino crema in piedi (gonna a cono); ombrello = cono semitrasparente (vetro, alpha ~0,3) su asta, inclinato di ~15 gradi e testa che gira nei frame del clip. Pioggia = card verticali sottili. Camera 35mm h 0,5 m, micro push-in. Shot 24: il whip si applica in compositing identico ai due pannelli.

### S07 - Retro della R34 davanti a Gwanghwamun: quattro fanali tondi e vapore (rif. shot 10, 19)

- **Location.** Viale largo e vuoto nel centro di Seoul (asse di Sejong-daero) di notte dopo la pioggia, dritto verso la porta Gwanghwamun del Gyeongbokgung illuminata: basamento in pietra con tre archi, tetti ricurvi a due livelli illuminati d'oro dal basso, dancheong sotto le gronde, montagna scura dietro. Asfalto a specchio, foschia. (Innesto dal trattamento 'cinema'.)
- **Camera.** 50mm ad altezza vita (~1,0 m), centrata sull'asse del viale, simmetria perfetta a un punto di fuga; auto ferma a ~6 m nella meta' inferiore, porta dorata che emerge sopra il tetto. Camera fissa con micro push-in. Shot 19 = crop 1,6x in basso a sinistra su fanali sinistri, scarico e vapore.
- **Azione.** [0-1,5 s] quattro fanali tondi accesi, un filo di vapore dallo scarico. [1,5 s] i freni si accendono piu' forti: fiammata rossa sull'asfalto bagnato. [1,5-5,0 s] uno sbuffo di vapore sale e si apre nella luce rossa; foschia leggera, riflessi oro e rossi che tremano.
- **Durata clip.** 5 s. **Shot.** 10, 19.
- **Blockout.** Set PALAZZO: strada = lungo piano nero lucido (roughness ~0,08) con linee di corsia tenui; porta = basamento a box con 3 archi (boolean) + due livelli di tetto (lastre scure con angoli rialzati), strisce emissive oro (#E8A84A, strength ~8) sotto le gronde + 3 area light dal basso; montagna = silhouette scura low-poly contro cielo navy (#172435); foschia = volume scatter a bassa densita'. Retro dell'auto proxy: alettone = piastra su due montanti; 4 dischi emissivi rosa-salmone (#FF8A80; 2 grandi esterni, 2 piccoli interni), strength da 6 a 18 nel frame della frenata; targa = rettangolo bianco vuoto; diffusore = box scuro; vapore = volume con noise a bassa densita' (o card morbida) che sale dallo scarico. Camera 50mm h 1,0 m centrata, micro push-in; lo shot 19 applica lo stesso crop 1,6x al render.

### S08 - Gangnam: cammina verso i fanali, si volta, mano ai capelli (rif. shot 11, 15, 16, 23)

- **Location.** Marciapiede di Gangnam sotto la pioggia, accanto all'auto ferma; dietro, maxischermi e neon in bokeh.
- **Camera.** 50mm ad altezza petto, camera fissa alle spalle di lei (~2,5 m), profondita' di campo ridotta. Auto qualche metro davanti, leggermente a destra, di 3/4 posteriore con i 4 fanali tondi accesi. Shot 15 = crop 1,3x, shot 16 = crop 1,6x su testa e mano.
- **Azione.** [0-2,6 s] di spalle cammina lentamente verso il retro dell'auto (due passi), l'organza ondeggia, medaglione peonia sulla schiena (shot 23). [2,8-4,2 s] si ferma accanto al parafango posteriore e gira la testa sopra la spalla sinistra guardando in camera (shot 11). [4,6-7,0 s] alza la mano sinistra e si sistema una ciocca dietro l'orecchio, accenno di sorriso (shot 15, 16). [7,0-8,0 s] tiene la posa. first_frame + last_frame. Ripiego se la mano deforma: per 15/16 si usano istanti della girata con gli stessi crop (versione 'fattibile').
- **Durata clip.** 8 s. **Shot.** 11, 15, 16, 23.
- **Blockout.** Riusa il set GANGNAM di S06 (blocchi neri con card emissive pastello sfocate dal DOF, suolo nero lucido). Auto proxy di 3/4 posteriore con 4 dischi emissivi rosa-salmone. Manichino crema di spalle con guscio durumagi semitrasparente e disco corallo sulla schiena. La chima lunga nasconde le gambe: la camminata e' una traslazione lungo il percorso del clip con leggero bob verticale e oscillazione della gonna (shape key) - niente walk cycle. Poi rotazione della testa di ~120 gradi sopra la spalla sinistra (empty) e braccio sinistro che sale alla testa, tutto sui frame del clip. Camera 50mm fissa h 1,4 m, DOF ~f/2. Shot 15 e 16: stessi crop 1,3x e 1,6x del pannello Seedance.

### S09 - Davanti ai fari nel vicolo, occhiali da sole (rif. shot 18, 20)

- **Location.** Lo stesso vicolo di Bukchon di S01, con l'auto frontale e i fari accesi.
- **Camera.** 35mm ad altezza vita, frontale e simmetrica. Auto centrata con il muso verso camera; lei subito davanti al cofano, tra i due fari, dalle ginocchia in su. Camera fissa con micro push-in.
- **Azione.** [0-2,5 s] immobile davanti ai fari, in controluce, con gli occhiali cat-eye gia' indossati; pioggia luminosa nei fasci, le nappe del norigae oscillano. [2,6-4,0 s] alza la mano destra, tocca la stanghetta degli occhiali e li sistema, riabbassa la mano (innesto 'fattibile': niente occhiali da infilare, interazione mano-oggetto minima). [4,0-5,0 s] immobile, rivolta all'obiettivo.
- **Durata clip.** 5 s. **Shot.** 18, 20.
- **Blockout.** Riusa il set VICOLO di S01 con l'auto frontale e nuova camera assiale (35mm, h 1,0 m). Fari emissivi molto forti + due spot puntati verso camera per il controluce e il bloom, pioggia volumetrica nei fasci (come shot 18 del riferimento). Manichino crema in piedi centrato davanti al muso (colonna + campana), braccia cilindriche riggate; occhiali = rettangolo grigio scuro sul volto; la mano destra sale alla tempia e torna giu' nei frame del clip. Lanterne sferiche emissive a muro. Micro push-in.

### S10 - Portiera davanti al minimarket: i piedi scendono (rif. shot 21)

- **Location.** Marciapiede di una via laterale di Seoul davanti a un piccolo minimarket d'angolo senza marchi: luce fluorescente bianca fredda dalla vetrina, frigoriferi sfocati, tavolini e sedie di plastica verdi, ombrellone chiuso, insegna = pannello luminoso bianco vuoto, pozzanghere.
- **Camera.** Bassa, all'altezza della soglia (~40 cm), 35mm. Vista di 3/4 del fianco destro dell'auto (lato guida, guida a destra) con la portiera aperta; il minimarket illuminato dietro l'auto. Camera fissa.
- **Azione.** [0-1,5 s] portiera aperta, abitacolo illuminato, la mano di lei sul montante; testa e spalle restano nell'ombra dell'abitacolo (niente volto: nessun rischio di moderazione). [1,5-3,5 s] raccoglie l'orlo della chima ed esce con i piedi uno dopo l'altro: le scarpe di raso avorio si posano sul marciapiede bagnato, piccola increspatura in una pozzanghera. [3,5-5,0 s] comincia ad alzarsi sporgendosi dalla portiera. Elegante, nessuna sessualizzazione.
- **Durata clip.** 5 s. **Shot.** 21.
- **Blockout.** Set MINIMARKET: box negozio con grande vetrina = piano emissivo bianco freddo (#EAF4FF, strength ~10); frigoriferi = rettangoli emissivi piu' tenui all'interno; insegna = striscia emissiva bianca vuota; 3 tavolini e sedie verdi (#2E8B57) = cilindri e box; ombrellone chiuso = cono; marciapiede = box con cordolo; strada = piano nero lucido con pozzanghere (roughness variabile). Auto proxy di fianco con portiera come oggetto separato incernierato, aperta a ~70 gradi; interno scuro con luce di cortesia emissiva calda. Piedi = due capsule crema con scarpe a cuneo avorio animate in uscita; orlo della gonna = guscio a campana avorio. Camera 35mm h 0,4 m, fissa.

### S11 - Corridoio del palazzo verso la stanza hanok: chiusura (rif. shot 26)

- **Location.** Corridoio coperto di un palazzo nello stile del Gyeongbokgung: colonne di legno laccate di rosso, travi dipinte dancheong (verde, rosso, blu), lanterne di carta a coppie, pietra bagnata. In fondo si apre la stanza hanok di S02 con lei seduta al centro.
- **Camera.** 24mm ad altezza occhi, prospettiva centrale perfettamente simmetrica, profondita' di campo ampia. Push-in lentissimo di pochi cm: chiusura calma.
- **Azione.** Lei resta immobile, seduta in posa formale al centro della stanza in fondo. Le lanterne oscillano appena, gocce cadono dalle gronde ai lati, foschia leggera sul pavimento. Nessun altro movimento.
- **Durata clip.** 5 s. **Shot.** 26.
- **Blockout.** Corridoio: due file di colonne cilindriche rosso scuro, travi a box con fasce di colore piatte (dancheong semplificato), soffitto scuro; lanterne = coppie di sfere emissive bianco-calde (#FFE2B0) appese con leggera oscillazione (driver sinusoidale); pavimento scuro lucido con soglia in pietra in primo piano. In fondo la stanza di S02 riusata tale e quale (parete a griglia emissiva calda, pavimento miele) con il manichino seduto (disco della gonna). Camera 24mm simmetrica h 1,2 m, push-in lentissimo. Palette marrone e ambra come lo shot 26 del riferimento.

I prompt esatti (keyframe Seedream e clip Seedance) sono in `seedream.json`, `seedance_manifest.json` e `seedance_manifest_omni.json`.

## 8. I 26 shot

Durate in frame identiche al riferimento. "Inizio" e' il tempo nel montaggio, "momento" l'istante nel clip del setup (frame 0 = keyframe). Stesso istante sopra (Blender) e sotto (Seedance).

| n | Frame | Inizio (s) | Setup | Momento nel clip | Descrizione |
|---|---|---|---|---|---|
| 1 | 8 | 0,00 | S01 | 1,00-1,29 s: Inizio del dolly: campo largo 3/4 frontale nel vicolo di Bukchon, anabbaglianti accesi, pioggia nei fasci. | Apertura: la R34 Bayside Blue ferma nel vicolo di hanok bagnato, lanterne calde, i fari come luce chiave. |
| 2 | 6 | 0,33 | S02 | 1,00-1,21 s: Lei in piedi, ferma, mani giunte (prima di inginocchiarsi). | In piedi a figura intera al centro della stanza hanok, porte di carta hanji luminose dietro. |
| 3 | 6 | 0,58 | S03 | 1,00-1,21 s: Solo la mano destra appoggiata in cima al volante. | Abitacolo con guida a destra: mano sul volante, strumenti accesi, bokeh di neon oltre il parabrezza bagnato. |
| 4 | 6 | 0,83 | S04 | 2,29-2,50 s: Gli occhi salgono verso l'obiettivo (6 frame di micro-movimento). | Primo piano beauty: alza lo sguardo in camera, orecchini d'oro, fondale di carta calda. |
| 5 | 14 | 1,08 | S05 | 1,00-1,54 s: Di spalle, ferma, l'organza mossa dalla brezza. | Di spalle con il medaglione peonia, la N Seoul Tower blu compressa dal tele, il parafango blu in basso a sinistra. |
| 6 | 18 | 1,67 | S03 | 2,21-2,92 s: La mano sinistra sale e afferra il volante a ore 9. | Due mani sul volante, cruscotto acceso: torna il motivo del volante. |
| 7 | 19 | 2,42 | S06 | 1,00-1,75 s: Lei ferma con l'ombrello trasparente, i maxischermi cambiano colore. | Campo largo su Gangnam-daero bagnato: auto di profilo, lei accanto con l'ombrello, maxischermi astratti. |
| 8 | 10 | 3,21 | S04 | 3,58-3,96 s: Sguardo fisso in camera, battito di ciglia, accenno di sorriso. | Ritorno al viso: contatto visivo pieno. |
| 9 | 14 | 3,62 | S02 | 4,04-4,58 s: Appena seduta in posa formale, frontale, chima aperta a cerchio, ferma. | Seduta formale al centro della stanza, simmetria totale (analogo del seiza). |
| 10 | 10 | 4,21 | S07 | 1,00-1,38 s: Quattro fanali tondi accesi, prima della frenata. | Retro della R34 centrato sul viale, la porta Gwanghwamun dorata in fondo: i quattro fanali tondi, firma dell'auto. |
| 11 | 11 | 4,62 | S08 | 3,29-3,71 s: A meta' della girata: la testa ruota sopra la spalla sinistra verso camera. | Gangnam: accanto ai fanali posteriori si volta e guarda in camera sopra la spalla. |
| 12 | 15 | 5,08 | S01 | 2,29-2,88 s: Dolly a meta': il doppio lampeggio degli abbaglianti cade ~3 frame dopo il taglio (sul beat 10). | Gli abbaglianti lampeggiano nella pioggia: l'evento che sostituisce i fari a scomparsa. |
| 13 | 11 | 5,71 | S01 | 5,21-5,62 s: Fine del dolly: il faro riempie il quadro, abbagliante fisso, pioggia in controluce. | Dettaglio del faro acceso, gocce nel fascio. |
| 14 | 14 | 6,17 | S03 | 3,92-4,46 s: Crop 1,4x sulle mani che stringono il volante e flettono le dita. | Stretto sulle mani: le dita stringono la corona, il bangle di giada. |
| 15 | 13 | 6,75 | S08 | 5,00-5,50 s: Crop 1,3x: la mano sinistra sale verso i capelli. | Accanto all'auto alza la mano verso i capelli, neon in bokeh. |
| 16 | 10 | 7,29 | S08 | 6,21-6,58 s: Crop 1,6x: si sistema la ciocca dietro l'orecchio, accenno di sorriso. | Piu' stretto: la ciocca dietro l'orecchio, sorriso appena accennato. |
| 17 | 17 | 7,71 | S02 | 5,08-5,75 s: Crop 1,5x: da seduta gira la testa a destra fino al profilo. | Nella stanza hanok gira il viso di profilo verso la porta di carta luminosa. |
| 18 | 10 | 8,42 | S09 | 1,00-1,38 s: Immobile davanti ai fari, in controluce, occhiali scuri. | Davanti al muso della R34, tra i due fari, in controluce con la pioggia luminosa: simmetria. |
| 19 | 11 | 8,83 | S07 | 3,00-3,42 s: Crop 1,6x in basso a sinistra: fanali in frenata e sbuffo di vapore dallo scarico. | Dettaglio basso: fanali rossi e vapore di scarico nella luce rossa, riflessi oro sull'asfalto. |
| 20 | 11 | 9,29 | S09 | 3,00-3,42 s: La mano destra tocca la stanghetta degli occhiali e li sistema. | Si sistema gli occhiali da sole davanti ai fari. |
| 21 | 7 | 9,75 | S10 | 2,21-2,46 s: Le scarpe di raso avorio toccano il marciapiede bagnato. | Portiera aperta davanti al minimarket bianco: i piedi scendono sul bagnato. |
| 22 | 20 | 10,04 | S05 | 1,79-2,58 s: Ancora di spalle, piu' avanti nel push-in: la brezza solleva l'organza e le nappe. | Ritorno al motivo della torre: di spalle verso la N Seoul Tower. |
| 23 | 15 | 10,88 | S08 | 1,00-1,58 s: Cammina di spalle verso i fanali posteriori. | Cammina di spalle verso il retro della R34, medaglione peonia e organza che ondeggia. |
| 24 | 13 | 11,50 | S06 | 3,79-4,29 s: I primi ~5 frame coperti dal whip in post (blur direzionale + scie), poi il campo largo: ombrello inclinato, viso verso camera. | Whip pan che si risolve sul campo largo di Gangnam: auto e ragazza sotto la pioggia. |
| 25 | 25 | 12,04 | S05 | 5,79-6,79 s: Crop 1,3x: frontale dopo la girata, occhiali cat-eye, torre blu dietro, immobile. | Frontale con gli occhiali e la N Seoul Tower dietro: lo shot piu' lungo prima della chiusura. |
| 26 | 22 | 13,08 | S11 | 1,50-2,38 s: Push-in lentissimo, lanterne che oscillano appena. | Chiusura: il corridoio del palazzo porta alla stanza hanok, lei seduta al centro in fondo. Calma e simmetria. |
| | **336** | 14,00 | | | |

Controlli fatti dallo script di generazione:
- la somma e' 336 frame;
- ogni istante sta dentro la durata del suo clip;
- ogni setup copre esattamente gli shot dichiarati.

Crop in post, identici sui due pannelli: 14 (1,4x), 15 (1,3x), 16 (1,6x), 17 (1,5x), 19 (1,6x), 25 (1,3x). Lo shot 24 ha il whip in post sui primi 5 frame.

## 9. Musica (Suno su ePhone)

**Genere.** City pop coreano moderno incontra nu-disco notturno, a 115 BPM nativi: cassa dritta, clap sul 2 e sul 4, basso slap, Rhodes, lead synth lucido, stab sincopati, un accenno di gayageum sintetico. E' un groove pieno dal primo secondo e senza build lungo, come il brano del riferimento (misurato a 115,0 BPM, pieno da ~0,5 s).

**Generazione** (`suno.json`):
- `suno/music`, chirp-v6, strumentale, `custom:false` con `gpt_description_prompt`, durata 40 s, wav;
- seconda chiamata in modalita' custom: soli meta-tag, `max_mode`, 50 s;
- un eventuale run con chirp-v6-wild.

Ogni chiamata restituisce 2 take.

**BPM e finestra.**
- Misurare il BPM di ogni take (autocorrelazione dello spectral flux o librosa).
- Correggere con `suno/adjust-speed`: speed_multiplier = 115 / BPM misurato, keep_pitch.
- Tagliare 14,00 s che partano su un downbeat del drop, con quel downbeat a ~0,03 s del video.
- Con questo allineamento 13 tagli su 25 cadono sul beat entro +-1,6 frame; gli altri cadono sugli ottavi, come nel riferimento.

Griglia: 1 beat = 12,52 frame, 1 battuta = 50,1 frame.

| Frame video | Tempo | Shot | Beat | Accento |
|---|---|---|---|---|
| 0 | 0,00 s | 1 (vicolo) | 0, downbeat battuta 1 | crash + kick |
| 14 | 0,58 s | 3 | 1 | stab, comparsa del titolo |
| 26 | 1,08 s | 5 (prima torre) | 2 | clap accentato |
| 101 | 4,21 s | 10 (fanali e porta dorata) | 8, downbeat battuta 3 | kick + crash |
| 125 | 5,21 s | dentro il 12 | 10 | doppio stab sul lampeggio degli abbaglianti |
| 202 | 8,42 s | 18 (lei nei fari) | 16, downbeat battuta 5 | crash + bass drop, l'accento piu' forte |
| 262-276 | 10,9-11,5 s | 23 -> 24 | 21-22 | riser / reverse cymbal |
| 276 | 11,50 s | 24 (whip) | 22 | picco del whoosh |
| 289 | 12,04 s | 25 (frontale con la torre) | 23 | sub impact |
| 314 | 13,08 s | 26 (corridoio) | 25 | accordo finale + passa-basso, coda fino a 14,00 s, stop netto |

I punti esatti si rinforzano con `suno/sounds` (bpm 115, stessa tonalita'). Le durate degli shot non si toccano: si sposta solo l'offset del brano (`audio.offset_s` nell'EDL; valore positivo = salta l'inizio del file).

## 10. Ordine di produzione e costi

1. **Riferimenti Seedream** (`seedream.json`, primi 7 job): ref_ragazza (W1, volto), ref_ragazza_figura (W3), ref_ragazza_schiena (W4), ref_auto (C1), ref_auto_retro (C2), ref_auto_profilo (C3), ref_auto_interno (C4). Parametri: 2K, png, watermark false, seed fisso. Si approvano a vista: niente deriva verso kimono o hanfu, niente ibridi AE86/Supra.
2. **Keyframe di grade.** kf_S01 diventa il riferimento NOTTE, kf_S02 il riferimento CALDO. Poi gli altri keyframe e i last_frame lf_S05 e lf_S08.
3. **Test di moderazione dei volti** su S04, a 480p per 4 s:
   - (a) keyframe passato come file o URL;
   - (b) se rifiutato (400, non addebitato): `ephone asset upload` e `asset://ID`;
   - (c) se rifiutato anche cosi': clip ancora S04 da solo testo (output Seedance = canale fidato), caricato come asset e usato come riferimento (`seedance_manifest_omni.json`, piano C).
4. **Setup senza volto**, subito a 1080p: S01, S07, S03, S10, S11.
5. **Setup con volto**: S02, S06, S09, S05, S08. Gli ultimi due con first_frame + last_frame.
6. **Blockout Blender** su ogni clip:
   - camera match con fSpy sul primo frame, oppure clip come sfondo al 50%;
   - sensore 36 mm, 1920x1080, 24 fps;
   - animazioni sui frame reali del clip;
   - set riusati: vicolo (S01, S09), Gangnam (S06, S08), hanok (S02, S11), auto proxy unica.
7. **Musica**: Suno, misura del BPM, adjust-speed, finestra da 14 s.
8. **Montaggio** (`edl_bozza.json`): rifinire gli `in` sui clip veri (+-0,5 s), crop e whip identici sopra e sotto. `montaggio/render.py` oggi ignora `crop` e `fx`, che vanno ancora implementati.
9. **Impaginazione** 1080x1920: header "Opus 5.5", pillole "Blender" e "Seedance 2.5".

| Voce | Stima |
|---|---|
| Seedance 2.5, 62 s a 1080p (una take per setup) | ~3,0 M token, ~209 CNY, **~30 USD** |
| Retake (Seedance 2.5 non accetta seed) | +50-100% -> 45-60 USD |
| Test moderazione 480p / 4 s | ~0,35 USD a tentativo |
| Seedream 5.0 Pro, 20 immagini 2K | ~2 USD |
| Suno, 2-3 chiamate | ~0,2-0,4 USD |

## 11. Rischi e ripieghi

| Rischio | Dove | Ripiego |
|---|---|---|
| Volto rifiutato in input | S02, S04, S05, S06, S08, S09 | asset:// -> omni-reference -> ancora S04 da testo (piano C) |
| Girata di 180 gradi che deforma corpo o identita' | S05 | last_frame gia' previsto; altrimenti solo girata della testa sopra la spalla destra, gia' con gli occhiali |
| La chima "morpha" mentre si inginocchia | S02 | keyframe gia' seduta: lo shot 2 usa il campo largo seduto, 9 e 17 restano |
| Mano ai capelli deformata | S08 (15, 16) | 15 e 16 da istanti della girata con gli stessi crop; oppure togliere il gesto dal prompt |
| Mani sul volante | S03 | lock "five fingers"; ripiego: una sola mano (versione "fattibile") |
| Testo o loghi storpiati | Gangnam, minimarket, palazzo | insegne astratte e illeggibili, targa vuota; nel caso, sfocatura in post sul solo pannello inferiore |
| Auto che diventa un ibrido | tutti | ref_auto approvato come master, lock su quattro fanali tondi e alettone; rifiutare ogni keyframe sbagliato |
| Tempi d'azione non rispettati al frame | tutti | gli `in` dell'EDL si ricalcolano sui clip veri; il blockout segue il clip, non il prompt |

## 12. File del progetto

| File | Contenuto |
|---|---|
| `TRATTAMENTO.md` | questo documento |
| `shotlist.json` | personaggio, auto, 11 setup (con note di blockout), 26 shot con start_frame, istante nel clip e crop |
| `seedream.json` | 20 job Seedream 5.0 Pro in ordine di dipendenza: 7 riferimenti, 11 keyframe, 2 last_frame |
| `seedance_manifest.json` | 11 clip Seedance 2.5 in modalita' first_frame (S05 e S08 anche con last_frame), compatibile con `python3 -m pubblicita.ephone batch` |
| `seedance_manifest_omni.json` | stessa lista in modalita' reference_images (ragazza + auto), per quando il keyframe fallisce, con il prompt del piano C |
| `suno.json` | brano strumentale a 115 BPM: chiamata principale, alternativa custom, procedura BPM, finestra e accenti |
| `edl_bozza.json` | EDL dei 26 tagli (sopra blender/<setup>.mp4, sotto seedance/<setup>.mp4, stesso `in`), con crop e whip annotati |

I percorsi delle immagini sono relativi alla radice del repo (/home/user/tonno). `ephone batch` li risolve rispetto alla cartella del manifest: lanciarlo da una copia del manifest nella radice, oppure riscrivere i percorsi come `../../output/...`.
