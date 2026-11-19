"""
Lista locale dei file caricati sul server.
Non sa niente della rete né della grafica.

Ogni voce:
  id             identificativo locale della voce
  nome_server    nome unico sul server, es. "foto(1).jpg"
  nome_originale nome del file sul portatile, es. "foto.jpg"
  percorso       percorso locale del file, serve per riprovare l'upload
  dimensione     byte
  data           momento dell'upload, formato ISO
  stato          "in caricamento" oppure "caricato"
"""
import json
import os
import tempfile
import uuid
from datetime import datetime
from pathlib import Path

IN_CARICAMENTO = "in caricamento"
CARICATO = "caricato"

MAX_NOME_BYTE = 63                 # il campo namefile del server è di 64 byte, '\0' compreso
MAX_COPIE = 99
MAX_UPLOAD = 100 * 1024 * 1024     # lo stesso limite del server

CARTELLA_PREDEFINITA = Path.home() / ".fileserver_client"


class ErroreNome(Exception):
    pass


def _taglia_utf8(testo, max_byte):
    """Accorcia una stringa senza spezzare a metà un carattere accentato."""
    b = testo.encode("utf-8")[:max_byte]
    return b.decode("utf-8", errors="ignore")


class Lista:
    def __init__(self, cartella=CARTELLA_PREDEFINITA):
        self.cartella = Path(cartella)
        self.file = self.cartella / "lista.json"
        self.voci = []
        self.server = {"host": "127.0.0.1", "porta": 9201}
        self.carica()

    # ---------- salvataggio ----------

    def carica(self):
        if not self.file.exists():
            return
        with open(self.file, encoding="utf-8") as f:
            dati = json.load(f)
        self.voci = dati.get("voci", [])
        self.server = dati.get("server", self.server)

    def salva(self):
        """Scrive un file temporaneo e lo sostituisce al vecchio in un colpo solo."""
        self.cartella.mkdir(parents=True, exist_ok=True)
        fd, temp = tempfile.mkstemp(dir=self.cartella, prefix="lista-", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump({"server": self.server, "voci": self.voci}, f, ensure_ascii=False, indent=2)
                f.flush()
                os.fsync(f.fileno())
            os.replace(temp, self.file)
        except BaseException:
            if os.path.exists(temp):
                os.remove(temp)
            raise

    # ---------- nomi unici ----------

    def _nomi_occupati(self):
        return {v["nome_server"] for v in self.voci}

    def nome_libero(self, nome_originale, escludi=()):
        """
        Restituisce un nome che non è nella lista: foto.jpg, foto(1).jpg, foto(2).jpg...
        Il numero va prima dell'estensione e il nome finale sta nei 63 byte del server.
        """
        base, est = os.path.splitext(nome_originale)
        if not base:                                  # es. ".bashrc": splitext dà base vuota
            base, est = est, ""
        while base.startswith("."):                   # il server rifiuta i nomi che iniziano con '.'
            base = "_" + base[1:]
        base = base.replace("/", "_")
        if not base:
            raise ErroreNome("nome del file non valido")
        if len(est.encode("utf-8")) > 20:             # estensione assurdamente lunga: la tratto come nome
            base, est = base + est, ""

        occupati = self._nomi_occupati() | set(escludi)
        for n in range(0, MAX_COPIE + 1):
            suffisso = "" if n == 0 else f"({n})"
            spazio = MAX_NOME_BYTE - len(suffisso.encode("utf-8")) - len(est.encode("utf-8"))
            candidato = _taglia_utf8(base, spazio) + suffisso + est
            if candidato not in occupati:
                return candidato
        raise ErroreNome(f"ci sono già {MAX_COPIE} copie di {nome_originale}")

    # ---------- voci ----------

    def nuova_voce(self, percorso_locale):
        """Crea la voce "in caricamento" e la salva PRIMA dell'upload."""
        dimensione = os.path.getsize(percorso_locale)
        if dimensione > MAX_UPLOAD:
            raise ErroreNome("il file supera i 100 MB accettati dal server")
        nome_originale = os.path.basename(percorso_locale)
        voce = {
            "id": str(uuid.uuid4()),
            "nome_server": self.nome_libero(nome_originale),
            "nome_originale": nome_originale,
            "percorso": os.path.abspath(percorso_locale),
            "dimensione": dimensione,
            "data": datetime.now().isoformat(timespec="seconds"),
            "stato": IN_CARICAMENTO,
        }
        self.voci.append(voce)
        self.salva()
        return voce

    def trova(self, id_voce):
        for v in self.voci:
            if v["id"] == id_voce:
                return v
        return None

    def imposta(self, id_voce, **campi):
        v = self.trova(id_voce)
        if v is not None:
            v.update(campi)
            self.salva()

    def rimuovi(self, id_voce):
        self.voci = [v for v in self.voci if v["id"] != id_voce]
        self.salva()

    def ordinate(self):
        """Più recenti per prime."""
        return sorted(self.voci, key=lambda v: v["data"], reverse=True)
