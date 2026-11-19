"""
Operazioni complete: uniscono la lista locale e la rete.
Sono le funzioni che chiama l'interfaccia grafica.
Ognuna restituisce (riuscita: bool, messaggio per l'utente).
"""
import os

import rete
from lista import CARICATO, IN_CARICAMENTO, ErroreNome

MAX_TENTATIVI_NOME = 5


def _server(lista):
    return lista.server["host"], int(lista.server["porta"])


def carica(lista, percorso_locale, avanzamento=None):
    """Upload di un file nuovo."""
    try:
        voce = lista.nuova_voce(percorso_locale)          # 1. salvata come "in caricamento"
    except (ErroreNome, OSError) as e:
        return False, str(e)
    return _invia(lista, voce, riprova=False, avanzamento=avanzamento)


def riprova(lista, id_voce, avanzamento=None):
    """Nuovo tentativo per una voce rimasta "in caricamento"."""
    voce = lista.trova(id_voce)
    if voce is None or voce["stato"] != IN_CARICAMENTO:
        return False, "niente da riprovare"
    if not os.path.exists(voce["percorso"]):
        return False, f"il file {voce['percorso']} non esiste più sul portatile"
    return _invia(lista, voce, riprova=True, avanzamento=avanzamento)


def _invia(lista, voce, riprova, avanzamento):
    host, porta = _server(lista)
    tentati = set()
    for _ in range(MAX_TENTATIVI_NOME):
        esito = rete.upload(host, porta, voce["percorso"], voce["nome_server"], avanzamento)

        if esito.tipo == rete.Esito.OK:
            lista.imposta(voce["id"], stato=CARICATO)
            return True, f"{voce['nome_originale']} caricato come {voce['nome_server']}"

        if esito.tipo == rete.Esito.INCERTO:
            # Il file potrebbe essere arrivato oppure no: la voce resta da riprovare.
            return False, f"nessuna risposta dal server: {voce['nome_originale']} resta da riprovare"

        if esito.codice == rete.NAME_EXISTS_ERR:
            if riprova:
                # Il tentativo precedente era arrivato: il file è già sul server con questo nome.
                lista.imposta(voce["id"], stato=CARICATO)
                return True, f"{voce['nome_originale']} era già stato caricato"
            # Nome occupato sul server ma non nella lista (es. lista persa): provo il numero successivo.
            tentati.add(voce["nome_server"])
            try:
                nuovo = lista.nome_libero(voce["nome_originale"], escludi=tentati)
            except ErroreNome as e:
                lista.rimuovi(voce["id"])
                return False, str(e)
            lista.imposta(voce["id"], nome_server=nuovo)
            continue

        # Errore definito dal server: l'upload non è avvenuto.
        lista.rimuovi(voce["id"])
        return False, f"upload non riuscito: {esito.descrizione()}"

    lista.rimuovi(voce["id"])
    return False, "troppi nomi già presenti sul server"


def scarica(lista, id_voce, destinazione, avanzamento=None):
    voce = lista.trova(id_voce)
    if voce is None:
        return False, "voce non trovata"
    if voce["stato"] != CARICATO:
        return False, "il file non risulta ancora caricato: usa Riprova"
    host, porta = _server(lista)
    esito = rete.download(host, porta, voce["nome_server"], destinazione, voce["dimensione"], avanzamento)
    if esito.tipo == rete.Esito.OK:
        return True, f"salvato in {destinazione}"
    if esito.codice == rete.DB_NOT_FOUND:
        lista.rimuovi(voce["id"])
        return False, f"{voce['nome_originale']} non è più sul server: rimosso dalla lista"
    return False, f"download non riuscito: {esito.descrizione()}"


def elimina(lista, id_voce):
    voce = lista.trova(id_voce)
    if voce is None:
        return False, "voce non trovata"
    host, porta = _server(lista)
    esito = rete.delete(host, porta, voce["nome_server"])
    if esito.tipo == rete.Esito.OK or esito.codice == rete.DB_NOT_FOUND:
        lista.rimuovi(voce["id"])                         # in entrambi i casi sul server non c'è più
        return True, f"{voce['nome_originale']} eliminato"
    return False, f"eliminazione non riuscita: {esito.descrizione()}"
