# File server in C with a Python client

THIS IS IA-GENERATED, SO I CAN FOCUS WRITING CODE.
A small system to store files on a remote machine and retrieve them from a laptop.

- **Server in C**: hand-written TCP sockets, one process per client (`fork`), files stored on disk and indexed with SQLite.
- **Client in Python** with a Qt graphical interface: uploads, downloads and deletes files, and keeps a local list of what is on the server.

![Client, light theme](qt_chiaro.png)

> The client's interface and the server's messages are in Italian.
> I'm going to translate them in later versions

---

## Contents

- [How it works](#how-it-works)
- [Project structure](#project-structure)
- [Server: build and run](#server-build-and-run)
- [Client: install and run](#client-install-and-run)
- [Protocol](#protocol)
- [Design choices](#design-choices)
- [Known limitations](#known-limitations)

---

## How it works

```
  LAPTOP                                           REMOTE MACHINE
┌──────────────────────┐        TCP        ┌──────────────────────────────┐
│ client.py  (Qt)      │                   │ server.c   network, protocol,│
│ operazioni.py        │  88-byte header   │            dispatch table    │
│ lista.py  ── local   │ ────────────────▶ │ store.c    files on disk     │
│            list      │ ◀──────────────── │            ./storage/<uuid>  │
│ rete.py              │ 128-byte response │ db.c       SQLite index      │
└──────────────────────┘    (+ file)       │            ../db/index       │
                                           └──────────────────────────────┘
```

1. The client sends a **header** with the operation (`UPLOAD`, `DOWNLOAD`, `DELETE`), the file name and its size.
2. The server picks the right function through a **dispatch table** and runs it in a child process.
3. Files are stored as `./storage/<uuid>.bin`: the name chosen by the client never becomes a path on disk. The database maps each name to its uuid.
4. The server replies with a **128-byte** message; for a download, the file follows right after it.

---

## Project structure

```
server/
├── server.c      sockets, fork, header parsing, dispatch table, responses
├── store.c       writing, reading and deleting files on disk
├── store.h
├── db.c          file index in SQLite (name → uuid, size, date)
└── db.h
client/
├── client.py     graphical interface (Qt / PySide6)
├── operazioni.py upload, download, delete, retry: combine the list and the network
├── lista.py      local list and choice of unique names
└── rete.py       protocol with the server
```

Each layer only uses the one below it: `server.c` contains no SQL, `store.c` knows nothing about the network, and in the client the interface knows nothing about the protocol.

---

## Server: build and run

Tested on Linux (Ubuntu 24.04).

### Dependencies

```bash
sudo apt install build-essential libsqlite3-dev uuid-dev
```

### Folders

The server uses paths **relative to the folder it is started from**: `./storage` for the files and `../db/index` for the database. The folders must exist:

```
fileserver/
├── db/            ← database (created on first start)
└── run/           ← folder the server is started from
    ├── server
    └── storage/   ← uploaded files
```

```bash
mkdir -p ~/fileserver/db ~/fileserver/run/storage
```

### Build

```bash
cd server
gcc -Wall -Wextra server.c store.c db.c -o ~/fileserver/run/server -lsqlite3 -luuid
```

### Run

```bash
cd ~/fileserver/run
./server 9201          # port between 1024 and 65535
```

If the firewall is active: `sudo ufw allow 9201/tcp`.

To keep it running after closing the terminal, use `tmux` or a systemd service.

---

## Client: install and run

Works on Windows, macOS and Linux. Requires **Python 3.9 or later**.

### Windows

1. Install Python from [python.org](https://www.python.org/downloads/), ticking **"Add python.exe to PATH"**.
2. Install the GUI library:
   ```
   py -m pip install PySide6
   ```
3. In the `client` folder:
   ```
   py client.py
   ```
   To start it with a double click and no console window, make a copy of `client.py` named `client.pyw` in the same folder.

### macOS and Linux

```bash
python3 -m pip install PySide6
cd client
python3 client.py
```

### First connection

At the top of the window, enter the server's **IP address** and **port**. They are remembered, together with the file list, in `~/.fileserver_client/` (on Windows `C:\Users\<name>\.fileserver_client\`).

To check that the server is reachable:

```
Test-NetConnection 192.168.1.20 -Port 9201      # Windows (PowerShell)
nc -vz 192.168.1.20 9201                        # macOS / Linux
```

### Usage

| Button | Action |
|---|---|
| **Carica file** (upload) | choose one or more files, or drag them into the window |
| **Scarica** (download) | or double-click the row |
| **Elimina** (delete) | also with the Delete key |
| **Riprova** (retry) | for files left "in caricamento" (uploading), see [Design choices](#design-choices) |

The same actions are available from the right-click menu.

### Building an executable

With PyInstaller, **on the target system** (the Windows `.exe` must be built on Windows):

```
py -m pip install pyinstaller
py -m PyInstaller --onefile --windowed --name FileClient client.py
```

The executable is in `dist/` and does not need Python on the computer that runs it (about 70 MB, since it bundles Python and Qt).

---

## Protocol

### Request: 88-byte header

Numbers in **big-endian** (network byte order), strings terminated by `'\0'`.

| Field | Type | Bytes | Content |
|---|---|---|---|
| `length` | `uint64_t` | 8 | file size for `UPLOAD`, 0 otherwise |
| `operation` | `char[16]` | 16 | `UPLOAD`, `DOWNLOAD` or `DELETE` |
| `namefile` | `char[64]` | 64 | file name on the server (at most 63 bytes) |

For `UPLOAD`, the header is immediately followed by `length` bytes of the file.

### Response: 128 bytes

Zero-terminated text:
- `OPERAZIONE RIUSCITA` (success)
- `ERRORE: NON SONO RIUSCITO NELL'OPERAZIONE, CODICE: <n>` (error, with its code)

For a successful `DOWNLOAD`, the file follows the 128 bytes until the connection is closed.

### Error codes

| Code | Meaning |
|---|---|
| -10 | request refused: invalid name, unknown command or file over 100 MB |
| -12 | the server could not store the file |
| -14 | deletion failed |
| -20 | database error during the upload |
| -21 | database error during the lookup |
| -22 | the server cannot open the database |
| -23 | file not found on the server |
| -24 | a file with that name already exists |

---

## Design choices

**Files on disk, metadata in SQLite.** File contents live in `./storage/<uuid>.bin`; the database only holds uuid, name, size and date. The database stays small and fast, files can be of any size, and several processes can receive files in parallel: SQLite's write lock is only taken for the short final `INSERT`.

**No half-written uploads.** The file is written as `<uuid>.temp`, flushed to disk with `fsync` and renamed to `<uuid>.bin` with `rename`, which is atomic. Only then is the row inserted into the database; if the insert fails, the file is deleted.

**One process per client.** Each connection is served by a child created with `fork`, which opens its own SQLite connection (a connection must not be shared between processes). `SIGCHLD` is ignored so no zombie processes are left behind, and `SIGPIPE` is ignored so a child is not killed if the client disconnects while it is sending.

**Dispatch table.** Operations are a table of `{name, function}` pairs: adding a command means adding a row and a handler, with no chain of `if`s.

**Unique names handled by the client.** The server refuses a name that already exists (`UNIQUE` index on the name, code -24). The client avoids conflicts: a second `foto.jpg` becomes `foto(1).jpg`, shortening the name if needed to fit in 63 bytes. In the list the user always sees the original name with date and time.

**Lost responses.** The client writes the entry to its list as "in caricamento" (uploading) *before* sending the file. If the connection drops and no response arrives, the entry is left to retry; if on the next attempt the server answers -24, the first upload had arrived and the entry becomes "caricato" (uploaded). This way no file ends up on the server without the client knowing about it.

**Verified downloads.** The client writes the file as `<name>.part` and renames it only if the bytes received match the size recorded in the list.

---

## Known limitations

- **No encryption and no authentication.** Anyone who can reach the port can upload, download and delete files. Use the server only on a trusted network or through a VPN (e.g. Tailscale, WireGuard), without exposing the port to the Internet.
- **One request per connection**: each operation opens a new TCP connection.
- **No server-side timeout**: a client that connects and sends nothing keeps a child process busy.
- **Files up to 100 MB** (`MAX_UPLOAD` in `server.c`).
- **Relative paths**: `./storage` and `../db/index` depend on the folder the server is started from.
- **An error halfway through a download** cannot be reported with a message (it would end up inside the file): the client detects it because it receives fewer bytes than expected.