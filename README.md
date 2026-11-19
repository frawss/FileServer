# File server in C con client Python

IA GENERATED, SO I CAN FOCUS CODING.
Un piccolo sistema per salvare file su una macchina remota e ritrovarli da un portatile.

- **Server in C**: socket TCP scritti a mano, un processo per ogni client (`fork`), file salvati su disco e indicizzati con SQLite.
- **Client in Python** con interfaccia grafica Qt: carica, scarica ed elimina file, e tiene una lista locale di cosa c'è sul server.

![Client, tema chiaro](qt_chiaro.png)

---

## Indice

- [Come funziona](#come-funziona)
- [Struttura del progetto](#struttura-del-progetto)
- [Server: compilazione e avvio](#server-compilazione-e-avvio)
- [Client: installazione e avvio](#client-installazione-e-avvio)
- [Protocollo](#protocollo)
- [Scelte di progetto](#scelte-di-progetto)
- [Limiti noti](#limiti-noti)

---

## Come funziona

```
  PORTATILE                                        MACCHINA REMOTA
┌──────────────────────┐        TCP        ┌──────────────────────────────┐
│ client.py  (Qt)      │                   │ server.c   rete, protocollo, │
│ operazioni.py        │  header 88 byte   │            dispatch table    │
│ lista.py  ── lista   │ ────────────────▶ │ store.c    file su disco     │
│            locale    │ ◀──────────────── │            ./storage/<uuid>  │
│ rete.py              │ risposta 128 byte │ db.c       indice SQLite     │
└──────────────────────┘    (+ file)       │            ../db/index       │
                                           └──────────────────────────────┘
```

1. Il client manda un **header** con l'operazione (`UPLOAD`, `DOWNLOAD`, `DELETE`), il nome del file e la sua dimensione.
2. Il server sceglie la funzione giusta tramite una **dispatch table** e la esegue in un processo figlio.
3. I file vengono salvati come `./storage/<uuid>.bin`: il nome scelto dal client non diventa mai un percorso su disco. Il database associa ogni nome al suo uuid.
4. Il server risponde con un messaggio di **128 byte**; nel download, subito dopo arriva il file.

---

## Struttura del progetto

```
server/
├── server.c      socket, fork, lettura dell'header, dispatch table, risposte
├── store.c       scrittura, lettura e cancellazione dei file su disco
├── store.h
├── db.c          indice dei file in SQLite (nome → uuid, dimensione, data)
└── db.h
client/
├── client.py     interfaccia grafica (Qt / PySide6)
├── operazioni.py upload, download, elimina, riprova: uniscono lista e rete
├── lista.py      lista locale e scelta dei nomi unici
└── rete.py       protocollo con il server
```

Ogni livello usa solo quello sotto di sé: `server.c` non contiene SQL, `store.c` non sa niente della rete, e nel client la grafica non sa niente del protocollo.

---

## Server: compilazione e avvio

Testato su Linux (Ubuntu 24.04).

### Dipendenze

```bash
sudo apt install build-essential libsqlite3-dev uuid-dev
```

### Cartelle

Il server usa percorsi **relativi alla cartella da cui viene avviato**: `./storage` per i file e `../db/index` per il database. Le cartelle devono esistere:

```
fileserver/
├── db/            ← database (creato al primo avvio)
└── run/           ← cartella da cui si avvia il server
    ├── server
    └── storage/   ← file caricati
```

```bash
mkdir -p ~/fileserver/db ~/fileserver/run/storage
```

### Compilazione

```bash
cd server
gcc -Wall -Wextra server.c store.c db.c -o ~/fileserver/run/server -lsqlite3 -luuid
```

### Avvio

```bash
cd ~/fileserver/run
./server 9201          # porta tra 1024 e 65535
```

Se il firewall è attivo: `sudo ufw allow 9201/tcp`.

Per lasciarlo in esecuzione dopo aver chiuso il terminale si può usare `tmux` o un servizio systemd.

---

## Client: installazione e avvio

Funziona su Windows, macOS e Linux. Serve **Python 3.9 o successivo**.

### Windows

1. Installa Python da [python.org](https://www.python.org/downloads/), spuntando **"Add python.exe to PATH"**.
2. Installa la libreria grafica:
   ```
   py -m pip install PySide6
   ```
3. Nella cartella `client`:
   ```
   py client.py
   ```
   Per avviarlo con un doppio clic senza finestra nera, fai una copia di `client.py` chiamata `client.pyw`, nella stessa cartella.

### macOS e Linux

```bash
python3 -m pip install PySide6
cd client
python3 client.py
```

### Primo collegamento

In alto nella finestra inserisci **indirizzo IP** e **porta** del server: vengono ricordati, insieme alla lista dei file, in `~/.fileserver_client/` (su Windows `C:\Users\<nome>\.fileserver_client\`).

Per verificare che il server sia raggiungibile:

```
Test-NetConnection 192.168.1.20 -Port 9201      # Windows (PowerShell)
nc -vz 192.168.1.20 9201                        # macOS / Linux
```

### Uso

- **Carica file**, oppure trascina uno o più file nella finestra.
- **Scarica**: oppure doppio clic sulla riga.
- **Elimina**: anche con il tasto Canc.
- **Riprova**: per i file rimasti "in caricamento" (vedi [Scelte di progetto](#scelte-di-progetto)).
- Le stesse azioni sono nel menu del tasto destro.

### Creare un eseguibile

Con PyInstaller, **sul sistema di destinazione** (l'`.exe` per Windows si crea su Windows):

```
py -m pip install pyinstaller
py -m PyInstaller --onefile --windowed --name FileClient client.py
```

L'eseguibile si trova in `dist/` e non richiede Python sul computer che lo usa (circa 70 MB, perché include Python e Qt).

---

## Protocollo

### Richiesta: header di 88 byte

Numeri in **big-endian** (ordine di rete), stringhe terminate da `'\0'`.

| Campo | Tipo | Byte | Contenuto |
|---|---|---|---|
| `length` | `uint64_t` | 8 | dimensione del file per `UPLOAD`, 0 altrimenti |
| `operation` | `char[16]` | 16 | `UPLOAD`, `DOWNLOAD` o `DELETE` |
| `namefile` | `char[64]` | 64 | nome del file sul server (massimo 63 byte) |

Per `UPLOAD`, subito dopo l'header seguono `length` byte del file.

### Risposta: 128 byte

Testo terminato da zeri:
- `OPERAZIONE RIUSCITA`
- `ERRORE: NON SONO RIUSCITO NELL'OPERAZIONE, CODICE: <n>`

Per un `DOWNLOAD` riuscito, dopo i 128 byte arriva il file fino alla chiusura della connessione.

### Codici di errore

| Codice | Significato |
|---|---|
| -10 | richiesta rifiutata: nome non valido, comando sconosciuto o file oltre 100 MB |
| -12 | il server non è riuscito a salvare il file |
| -14 | cancellazione non riuscita |
| -20 | errore del database durante l'upload |
| -21 | errore del database nella ricerca |
| -22 | il server non riesce ad aprire il database |
| -23 | file non presente sul server |
| -24 | esiste già un file con quel nome |

---

## Scelte di progetto

**File su disco, metadati in SQLite.** I contenuti stanno in `./storage/<uuid>.bin`; il database contiene solo uuid, nome, dimensione e data. Il database resta piccolo e veloce, i file possono essere di qualsiasi dimensione, e più processi possono ricevere file in parallelo: il lock di scrittura di SQLite viene preso solo per il breve `INSERT` finale.

**Upload senza file a metà.** Il file viene scritto come `<uuid>.temp`, forzato su disco con `fsync` e rinominato in `<uuid>.bin` con `rename`, che è atomico. Solo dopo viene inserita la riga nel database; se l'inserimento fallisce, il file viene cancellato.

**Un processo per client.** Ogni connessione viene servita da un figlio creato con `fork`, che apre la propria connessione SQLite (una connessione non va condivisa tra processi). `SIGCHLD` è ignorato per non lasciare processi zombie, `SIGPIPE` per non far terminare un figlio se il client chiude durante un invio.

**Dispatch table.** Le operazioni sono una tabella `{nome, funzione}`: aggiungere un comando significa aggiungere una riga e un handler, senza catene di `if`.

**Nomi unici gestiti dal client.** Il server rifiuta un nome già presente (indice `UNIQUE` sul nome, codice -24). Il client evita i conflitti: un secondo `foto.jpg` diventa `foto(1).jpg`, accorciando il nome se serve per stare nei 63 byte. Nell'elenco l'utente vede sempre il nome originale con data e ora.

**Risposte perse.** Il client scrive la voce nella lista come "in caricamento" *prima* di inviare il file. Se la connessione cade e la risposta non arriva, la voce resta da riprovare; se al nuovo tentativo il server risponde -24, il primo invio era arrivato e la voce diventa "caricato". Così nessun file finisce sul server senza che il client lo sappia.

**Download verificato.** Il client scrive il file come `<nome>.part` e lo rinomina solo se i byte ricevuti corrispondono alla dimensione registrata nella lista.

---

## Limiti noti

- **Nessuna cifratura e nessuna autenticazione.** Chiunque raggiunga la porta può caricare, scaricare e cancellare file. Usare il server solo in una rete fidata o tramite una VPN (es. Tailscale, WireGuard), senza esporre la porta su Internet.
- **Una richiesta per connessione**: ogni operazione apre una nuova connessione TCP.
- **Nessun timeout lato server**: un client che si collega e non invia niente tiene occupato un processo figlio.
- **File fino a 100 MB** (`MAX_UPLOAD` in `server.c`).
- **Percorsi relativi**: `./storage` e `../db/index` dipendono dalla cartella da cui si avvia il server.
- **Un errore a metà download** non può essere segnalato con un messaggio (finirebbe dentro il file): il client lo riconosce perché riceve meno byte del previsto.
