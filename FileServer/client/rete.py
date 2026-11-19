"""
Strato di rete: parla con il server secondo il suo protocollo.
Non sa niente della lista locale né della grafica.

Protocollo del server:
  richiesta  -> header di 88 byte: length (uint64 big-endian), operation[16], namefile[64]
                UPLOAD: dopo l'header seguono 'length' byte del file
  risposta   <- 128 byte di testo terminato da zeri:
                "OPERAZIONE RIUSCITA" oppure "ERRORE: ... CODICE: <numero>"
                DOWNLOAD riuscito: dopo i 128 byte arriva il file, fino alla chiusura
"""
import os
import re
import socket
import struct

HEADER = struct.Struct("!Q16s64s")
RISPOSTA_LEN = 128
BLOCCO = 8192
TIMEOUT = 15                       # secondi senza dati prima di considerare la rete caduta

MESSAGGIO_OK = "OPERAZIONE RIUSCITA"

# Codici del server
SOCKET_ERR = -10                   # richiesta rifiutata: nome non valido, comando sconosciuto, file troppo grande
INSERT_ERR = -12                   # il server non è riuscito a salvare il file
DELETE_ERR = -14
INSERT_DB_ERR = -20
FIND_DB_ERR = -21
OPENDB_ERR = -22
DB_NOT_FOUND = -23
NAME_EXISTS_ERR = -24

DESCRIZIONI = {
    SOCKET_ERR: "richiesta rifiutata dal server (nome non valido o file troppo grande)",
    INSERT_ERR: "il server non è riuscito a salvare il file",
    DELETE_ERR: "il server non è riuscito a cancellare il file",
    INSERT_DB_ERR: "errore del database del server",
    FIND_DB_ERR: "errore del database del server",
    OPENDB_ERR: "il server non riesce ad aprire il database",
    DB_NOT_FOUND: "file non presente sul server",
    NAME_EXISTS_ERR: "nome già presente sul server",
}


class Esito:
    """Com'è andata un'operazione."""

    OK = "ok"
    ERRORE = "errore"          # il server ha risposto con un codice d'errore
    INCERTO = "incerto"        # nessuna risposta completa: rete caduta, server irraggiungibile...

    def __init__(self, tipo, codice=None, dettaglio=""):
        self.tipo = tipo
        self.codice = codice
        self.dettaglio = dettaglio

    def __repr__(self):
        return f"Esito({self.tipo}, {self.codice}, {self.dettaglio!r})"

    def descrizione(self):
        if self.tipo == Esito.OK:
            return "operazione riuscita"
        if self.tipo == Esito.ERRORE:
            return DESCRIZIONI.get(self.codice, f"errore del server (codice {self.codice})")
        return f"nessuna risposta dal server ({self.dettaglio})"


def _ricevi_esatti(sock, n):
    """Legge esattamente n byte: TCP può consegnarli a pezzi."""
    dati = bytearray()
    while len(dati) < n:
        pezzo = sock.recv(n - len(dati))
        if not pezzo:
            raise ConnectionError("il server ha chiuso la connessione")
        dati += pezzo
    return bytes(dati)


def interpreta_risposta(grezza):
    """Trasforma i 128 byte del server in un Esito."""
    testo = grezza.split(b"\0", 1)[0].decode("utf-8", errors="replace").strip()
    if testo == MESSAGGIO_OK:
        return Esito(Esito.OK)
    trovato = re.search(r"CODICE:\s*(-?\d+)\s*$", testo)
    if trovato:
        return Esito(Esito.ERRORE, int(trovato.group(1)), testo)
    return Esito(Esito.INCERTO, dettaglio=f"risposta non riconosciuta: {testo!r}")


def _connetti(host, porta):
    sock = socket.create_connection((host, porta), timeout=TIMEOUT)
    sock.settimeout(TIMEOUT)
    return sock


def _header(operazione, nome, lunghezza=0):
    nome_b = nome.encode("utf-8")
    if len(nome_b) > 63:
        raise ValueError("nome troppo lungo per il server (max 63 byte)")
    return HEADER.pack(lunghezza, operazione.encode(), nome_b)


def upload(host, porta, percorso_locale, nome_server, avanzamento=None):
    """Invia il file. Restituisce un Esito."""
    dimensione = os.path.getsize(percorso_locale)
    try:
        with _connetti(host, porta) as sock, open(percorso_locale, "rb") as f:
            sock.sendall(_header("UPLOAD", nome_server, dimensione))
            inviati = 0
            while True:
                blocco = f.read(BLOCCO)
                if not blocco:
                    break
                sock.sendall(blocco)
                inviati += len(blocco)
                if avanzamento:
                    avanzamento(inviati, dimensione)
            return interpreta_risposta(_ricevi_esatti(sock, RISPOSTA_LEN))
    except (OSError, ConnectionError) as e:
        # Il server potrebbe aver rifiutato e chiuso mentre inviavamo: l'esito è incerto.
        return Esito(Esito.INCERTO, dettaglio=str(e))


def download(host, porta, nome_server, destinazione, dimensione_attesa, avanzamento=None):
    """
    Scarica il file in 'destinazione'. Scrive prima un file temporaneo e lo rinomina
    solo se i byte ricevuti sono esattamente quelli attesi. Restituisce un Esito.
    """
    temporaneo = destinazione + ".part"
    try:
        with _connetti(host, porta) as sock:
            sock.sendall(_header("DOWNLOAD", nome_server))
            esito = interpreta_risposta(_ricevi_esatti(sock, RISPOSTA_LEN))
            if esito.tipo != Esito.OK:
                return esito
            ricevuti = 0
            with open(temporaneo, "wb") as f:
                while True:
                    blocco = sock.recv(BLOCCO)
                    if not blocco:                       # il server ha chiuso: file finito
                        break
                    f.write(blocco)
                    ricevuti += len(blocco)
                    if avanzamento:
                        avanzamento(ricevuti, dimensione_attesa)
    except (OSError, ConnectionError) as e:
        _rimuovi(temporaneo)
        return Esito(Esito.INCERTO, dettaglio=str(e))

    if ricevuti != dimensione_attesa:
        _rimuovi(temporaneo)
        return Esito(Esito.INCERTO,
                     dettaglio=f"download interrotto: ricevuti {ricevuti} byte su {dimensione_attesa}")
    os.replace(temporaneo, destinazione)
    return Esito(Esito.OK)


def delete(host, porta, nome_server):
    try:
        with _connetti(host, porta) as sock:
            sock.sendall(_header("DELETE", nome_server))
            return interpreta_risposta(_ricevi_esatti(sock, RISPOSTA_LEN))
    except (OSError, ConnectionError) as e:
        return Esito(Esito.INCERTO, dettaglio=str(e))


def _rimuovi(percorso):
    try:
        os.remove(percorso)
    except FileNotFoundError:
        pass
