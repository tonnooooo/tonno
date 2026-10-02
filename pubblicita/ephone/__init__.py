"""Client ePhone per Seedance 2.5 (video) e Seedream 5.0 Pro (immagini).

Uso da riga di comando: ``python3 -m pubblicita.ephone --help`` (vedi README.md).
Uso da Python::

    from pubblicita.ephone import ClientEphone, Esecutore, carica_configurazione, costruisci_video

    conf = carica_configurazione()
    client = ClientEphone(conf.richiedi_chiave(), conf.url_base)
    richiesta = costruisci_video({"id": "s01", "prompt": "...", "duration": 5, "resolution": "1080p"})
    esecutore = Esecutore(client)
    print(esecutore.esegui(esecutore.pianifica([richiesta])))
"""
from .client import (
    ClientEphone, Configurazione, ErroreAPI, ErroreConfigurazione, ErroreEphone, ErroreRete,
    RispostaInattesa, StatoTask, SubmitIncerto, carica_configurazione, normalizza_stato,
)
from .lavori import Esecutore, Esito, Piano
from .manifest import Manifest, carica as carica_manifest
from .richieste import ErroreValidazione, RichiestaImmagine, RichiestaVideo, costruisci_immagine, costruisci_video

__all__ = [
    "ClientEphone", "Configurazione", "ErroreAPI", "ErroreConfigurazione", "ErroreEphone", "ErroreRete",
    "RispostaInattesa", "StatoTask", "SubmitIncerto", "carica_configurazione", "normalizza_stato",
    "Esecutore", "Esito", "Piano", "Manifest", "carica_manifest",
    "ErroreValidazione", "RichiestaImmagine", "RichiestaVideo", "costruisci_immagine", "costruisci_video",
]
