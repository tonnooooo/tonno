# Quadro Contesto — interfaccia di chat

Un solo file, `index.html`. Nessun build, nessuna dipendenza da installare:
si apre nel browser o si serve da qualunque server statico.

## Perché esiste

L'interfaccia normale non ti dice mai quanto contesto stai consumando né
quando compatta. Cosi' i guasti sembrano casuali: la chat "a un certo punto"
si rompe. Qui tutto quello che succede al contesto e' visibile:

- **misuratore in alto** — token usati sul budget reale, con la tacca della
  soglia oltre la quale scatta la compattazione;
- **eventi di compattazione nella trascrizione** — quanti messaggi sono stati
  assorbiti e quanti token si sono liberati, con il riassunto in chiaro;
- **errori del server mostrati per intero**, con il messaggio grezzo del
  motore e cosa significa, invece di una schermata vuota;
- **avviso rosso** quando la finestra impostata e' piu' larga di quella che il
  motore serve davvero (`true_max_context_length`): e' la causa piu' comune
  dei guasti apparentemente casuali.

La compattazione qui e' fatta in modo sicuro: il riassunto viene chiesto al
modello **prima** di archiviare qualcosa, e i messaggi vengono nascosti, mai
cancellati. Se il riassunto fallisce, la conversazione resta intatta.

## Uso

Aprilo e basta, oppure servilo dalla VM:

```bash
cd webui && python3 -m http.server 8090
```

Poi ⚙ → indirizzo del server → **Interroga il server**: rileva da solo il tipo
di API (OpenAI-compatible o KoboldCpp), il modello e la finestra reale, e se
quella impostata e' troppo alta la corregge.

Senza indirizzo parte in modalita' dimostrativa, con una conversazione di
esempio che mostra come si leggono compattazione ed errori.

Le conversazioni stanno nel `localStorage` del browser e si esportano in JSON
dal fondo della colonna di sinistra.
