#!/usr/bin/env python3
"""
Client grafico per il file server (Qt / PySide6).
Avvio: python3 client.py

Solo questo file riguarda la grafica: rete.py, lista.py e operazioni.py
sono gli stessi della versione precedente.
"""
import os
import sys
import threading
from datetime import datetime

from PySide6.QtCore import QFileInfo, QObject, Qt, Signal
from PySide6.QtGui import QAction, QColor, QKeySequence, QPalette
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QFileDialog, QFileIconProvider, QFrame,
    QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMainWindow, QMenu, QMessageBox,
    QProgressBar, QPushButton, QSpinBox, QStyle, QTreeWidget, QTreeWidgetItem,
    QVBoxLayout, QWidget,
)

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import operazioni                                      # noqa: E402
from lista import CARICATO, Lista                      # noqa: E402

COL_NOME, COL_DATA, COL_DIM, COL_STATO = range(4)


def dimensione_leggibile(n):
    for unita in ("B", "KB", "MB", "GB"):
        if n < 1024 or unita == "GB":
            return f"{n:.0f} {unita}" if unita == "B" else f"{n:.1f} {unita}"
        n /= 1024


def data_leggibile(iso):
    try:
        return datetime.fromisoformat(iso).strftime("%d/%m/%Y %H:%M:%S")
    except ValueError:
        return iso


class Ponte(QObject):
    """
    I trasferimenti girano in un thread separato; la finestra si può modificare
    solo dal thread principale. I segnali Qt emessi dal thread vengono consegnati
    da Qt al thread principale in modo sicuro.
    """
    avanzamento = Signal(int)
    finito = Signal(bool, str)


class Finestra(QMainWindow):
    def __init__(self, lista):
        super().__init__()
        self.lista = lista
        self.occupato = False
        self.icone = QFileIconProvider()
        self.ponte = Ponte()
        self.ponte.avanzamento.connect(self._su_avanzamento)
        self.ponte.finito.connect(self._su_finito)

        self.setWindowTitle("File server")
        self.resize(860, 520)
        self.setAcceptDrops(True)

        centrale = QWidget()
        self.setCentralWidget(centrale)
        principale = QVBoxLayout(centrale)
        principale.setContentsMargins(16, 16, 16, 12)
        principale.setSpacing(12)

        # --- intestazione: titolo e server ---
        intestazione = QHBoxLayout()
        titolo = QLabel("I miei file")
        titolo.setObjectName("titolo")
        intestazione.addWidget(titolo)
        intestazione.addStretch()
        intestazione.addWidget(QLabel("Server"))
        self.host = QLineEdit(lista.server["host"])
        self.host.setPlaceholderText("indirizzo del server")
        self.host.setMinimumWidth(180)
        intestazione.addWidget(self.host)
        intestazione.addWidget(QLabel("Porta"))
        self.porta = QSpinBox()
        self.porta.setRange(1, 65535)
        self.porta.setValue(int(lista.server["porta"]))
        intestazione.addWidget(self.porta)
        principale.addLayout(intestazione)

        # --- barra dei comandi ---
        comandi = QHBoxLayout()
        stile = self.style()
        self.btn_carica = QPushButton(stile.standardIcon(QStyle.SP_ArrowUp), "  Carica file")
        self.btn_carica.setObjectName("primario")
        self.btn_scarica = QPushButton(stile.standardIcon(QStyle.SP_ArrowDown), "  Scarica")
        self.btn_elimina = QPushButton(stile.standardIcon(QStyle.SP_TrashIcon), "  Elimina")
        self.btn_riprova = QPushButton(stile.standardIcon(QStyle.SP_BrowserReload), "  Riprova")
        for b in (self.btn_carica, self.btn_scarica, self.btn_elimina, self.btn_riprova):
            b.setMinimumHeight(34)
            comandi.addWidget(b)
        comandi.addStretch()
        suggerimento = QLabel("Puoi anche trascinare i file nella finestra")
        suggerimento.setObjectName("tenue")
        comandi.addWidget(suggerimento)
        principale.addLayout(comandi)

        self.btn_carica.clicked.connect(lambda: self.on_carica())
        self.btn_scarica.clicked.connect(lambda: self.on_scarica())
        self.btn_elimina.clicked.connect(lambda: self.on_elimina())
        self.btn_riprova.clicked.connect(self.on_riprova)

        # --- elenco ---
        self.elenco = QTreeWidget()
        self.elenco.setHeaderLabels(["Nome", "Caricato il", "Dimensione", "Stato"])
        self.elenco.setRootIsDecorated(False)
        self.elenco.setAlternatingRowColors(True)
        self.elenco.setUniformRowHeights(True)
        self.elenco.setSelectionMode(QAbstractItemView.SingleSelection)
        self.elenco.setSortingEnabled(True)
        self.elenco.sortByColumn(COL_DATA, Qt.DescendingOrder)
        self.elenco.setContextMenuPolicy(Qt.CustomContextMenu)
        testata = self.elenco.header()
        testata.setStretchLastSection(False)
        testata.setSectionResizeMode(COL_NOME, QHeaderView.Stretch)
        for col in (COL_DATA, COL_DIM, COL_STATO):
            testata.setSectionResizeMode(col, QHeaderView.ResizeToContents)
        self.elenco.itemSelectionChanged.connect(self.aggiorna_pulsanti)
        self.elenco.itemDoubleClicked.connect(lambda *_: self.on_scarica())
        self.elenco.customContextMenuRequested.connect(self._menu_contestuale)
        principale.addWidget(self.elenco, 1)

        # --- avanzamento e stato ---
        piede = QFrame()
        piede_layout = QHBoxLayout(piede)
        piede_layout.setContentsMargins(0, 0, 0, 0)
        self.stato = QLabel("Pronto")
        self.barra = QProgressBar()
        self.barra.setRange(0, 100)
        self.barra.setTextVisible(False)
        self.barra.setFixedWidth(220)
        self.barra.setFixedHeight(6)
        self.barra.hide()
        piede_layout.addWidget(self.stato, 1)
        piede_layout.addWidget(self.barra)
        principale.addWidget(piede)

        # scorciatoie da tastiera
        for testo, tasto, azione in (
            ("Carica", QKeySequence.Open, lambda: self.on_carica()),
            ("Elimina", QKeySequence.Delete, lambda: self.on_elimina()),
        ):
            a = QAction(testo, self)
            a.setShortcut(tasto)
            a.triggered.connect(azione)
            self.addAction(a)

        self._applica_stile()
        self.ridisegna()

    # ---------- aspetto ----------

    def _applica_stile(self):
        self.setStyleSheet("""
            QLabel#titolo { font-size: 18px; font-weight: 600; }
            QLabel#tenue  { color: palette(placeholder-text); }
            QPushButton { padding: 4px 14px; }
            QPushButton#primario {
                background: palette(highlight); color: palette(highlighted-text);
                border: none; border-radius: 6px; font-weight: 600; padding: 4px 16px;
            }
            QPushButton#primario:hover    { background: palette(link); }
            QPushButton#primario:disabled { background: palette(mid); }
            QTreeWidget { border: 1px solid palette(mid); border-radius: 6px; }
            QTreeWidget::item { height: 32px; }
            QProgressBar { border: none; border-radius: 3px; background: palette(mid); }
            QProgressBar::chunk { border-radius: 3px; background: palette(highlight); }
        """)

    # ---------- elenco ----------

    def ridisegna(self):
        selezionata = self.voce_selezionata()
        self.elenco.setSortingEnabled(False)
        self.elenco.clear()
        attesa = self.palette().color(self.palette().ColorRole.Link)
        for v in self.lista.voci:
            riga = QTreeWidgetItem([
                v["nome_originale"], data_leggibile(v["data"]),
                dimensione_leggibile(v["dimensione"]), v["stato"]])
            riga.setData(COL_NOME, Qt.UserRole, v["id"])
            riga.setData(COL_DATA, Qt.UserRole, v["data"])
            icona = self.icone.icon(QFileInfo(v["nome_originale"]))
            if icona.isNull():
                icona = self.style().standardIcon(QStyle.SP_FileIcon)
            riga.setIcon(COL_NOME, icona)
            riga.setTextAlignment(COL_DIM, Qt.AlignRight | Qt.AlignVCenter)
            riga.setToolTip(COL_NOME, f"Sul server: {v['nome_server']}")
            if v["stato"] != CARICATO:
                for col in range(4):
                    riga.setForeground(col, attesa)
            self.elenco.addTopLevelItem(riga)
            if v["id"] == selezionata:
                riga.setSelected(True)
        self.elenco.setSortingEnabled(True)
        self.aggiorna_pulsanti()

    def voce_selezionata(self):
        righe = self.elenco.selectedItems()
        return righe[0].data(COL_NOME, Qt.UserRole) if righe else None

    def aggiorna_pulsanti(self):
        voce = self.lista.trova(self.voce_selezionata()) if self.voce_selezionata() else None
        libero = not self.occupato
        self.btn_carica.setEnabled(libero)
        self.btn_scarica.setEnabled(libero and voce is not None and voce["stato"] == CARICATO)
        self.btn_elimina.setEnabled(libero and voce is not None)
        self.btn_riprova.setEnabled(libero and voce is not None and voce["stato"] != CARICATO)

    def _menu_contestuale(self, punto):
        riga = self.elenco.itemAt(punto)
        if riga is None:
            return
        riga.setSelected(True)
        menu = QMenu(self)
        for pulsante in (self.btn_scarica, self.btn_riprova, self.btn_elimina):
            if pulsante.isEnabled():
                azione = menu.addAction(pulsante.icon(), pulsante.text().strip())
                azione.triggered.connect(pulsante.click)
        if not menu.isEmpty():
            menu.exec(self.elenco.viewport().mapToGlobal(punto))

    # ---------- trascinamento ----------

    def dragEnterEvent(self, evento):
        if evento.mimeData().hasUrls() and not self.occupato:
            evento.acceptProposedAction()

    def dropEvent(self, evento):
        percorsi = [u.toLocalFile() for u in evento.mimeData().urls() if u.isLocalFile()]
        percorsi = [p for p in percorsi if os.path.isfile(p)]
        if percorsi:
            self.carica_in_sequenza(percorsi)

    # ---------- lavoro in background ----------

    def _salva_server(self):
        host = self.host.text().strip()
        if not host:
            QMessageBox.warning(self, "Server", "Scrivi l'indirizzo del server.")
            return False
        self.lista.server = {"host": host, "porta": self.porta.value()}
        self.lista.salva()
        return True

    def in_background(self, etichetta, lavoro):
        if self.occupato or not self._salva_server():
            return
        self.occupato = True
        self.aggiorna_pulsanti()
        self.stato.setText(etichetta)
        self.barra.setValue(0)
        self.barra.show()

        def esegui():
            try:
                riuscita, messaggio = lavoro()
            except Exception as e:                     # niente deve far sparire il thread in silenzio
                riuscita, messaggio = False, f"errore imprevisto: {e}"
            self.ponte.finito.emit(riuscita, messaggio)

        threading.Thread(target=esegui, daemon=True).start()

    def avanzamento(self, fatto, totale):
        self.ponte.avanzamento.emit(int(100 * fatto / totale) if totale else 100)

    def _su_avanzamento(self, percentuale):
        self.barra.setValue(percentuale)

    def _su_finito(self, riuscita, messaggio):
        self.occupato = False
        self.barra.hide()
        self.stato.setText(("✓  " if riuscita else "⚠  ") + messaggio)
        self.ridisegna()

    def carica_in_sequenza(self, percorsi):
        """Più file trascinati insieme: uno dopo l'altro."""
        def lavoro():
            esiti = []
            for p in percorsi:
                self.ponte.avanzamento.emit(0)
                esiti.append(operazioni.carica(self.lista, p, self.avanzamento))
            riusciti = sum(1 for ok, _ in esiti if ok)
            if len(percorsi) == 1:
                return esiti[0]
            return riusciti == len(percorsi), f"caricati {riusciti} file su {len(percorsi)}"
        self.in_background(f"Carico {len(percorsi)} file…" if len(percorsi) > 1
                           else f"Carico {os.path.basename(percorsi[0])}…", lavoro)

    # ---------- comandi ----------

    def on_carica(self, percorsi=None):
        if percorsi is None:
            percorsi, _ = QFileDialog.getOpenFileNames(self, "Scegli i file da caricare")
        if percorsi:
            self.carica_in_sequenza(list(percorsi))

    def on_scarica(self, destinazione=None):
        voce = self.lista.trova(self.voce_selezionata() or "")
        if not voce or voce["stato"] != CARICATO or self.occupato:
            return
        if destinazione is None:
            destinazione, _ = QFileDialog.getSaveFileName(self, "Salva come", voce["nome_originale"])
        if destinazione:
            self.in_background(f"Scarico {voce['nome_originale']}…",
                               lambda: operazioni.scarica(self.lista, voce["id"], destinazione, self.avanzamento))

    def on_elimina(self, conferma=True):
        voce = self.lista.trova(self.voce_selezionata() or "")
        if not voce or self.occupato:
            return
        if conferma and QMessageBox.question(
                self, "Elimina", f"Eliminare {voce['nome_originale']} dal server?") != QMessageBox.Yes:
            return
        self.in_background(f"Elimino {voce['nome_originale']}…",
                           lambda: operazioni.elimina(self.lista, voce["id"]))

    def on_riprova(self):
        voce = self.lista.trova(self.voce_selezionata() or "")
        if not voce:
            return
        self.in_background(f"Riprovo {voce['nome_originale']}…",
                           lambda: operazioni.riprova(self.lista, voce["id"], self.avanzamento))


def tavolozza(scuro):
    """Colori espliciti per il tema chiaro e scuro: stesso risultato su ogni sistema."""
    p = QPalette()
    if scuro:
        colori = {
            QPalette.Window: "#1f2125", QPalette.WindowText: "#e6e6e6",
            QPalette.Base: "#16181b", QPalette.AlternateBase: "#1c1e22",
            QPalette.Text: "#e6e6e6", QPalette.Button: "#2b2e33",
            QPalette.ButtonText: "#e6e6e6", QPalette.Highlight: "#3d8ee6",
            QPalette.HighlightedText: "#ffffff", QPalette.Link: "#e0a526",
            QPalette.Mid: "#3a3d42", QPalette.PlaceholderText: "#8a8f98",
            QPalette.ToolTipBase: "#2b2e33", QPalette.ToolTipText: "#e6e6e6",
        }
    else:
        colori = {
            QPalette.Window: "#f3f4f6", QPalette.WindowText: "#1d1f23",
            QPalette.Base: "#ffffff", QPalette.AlternateBase: "#f7f8fa",
            QPalette.Text: "#1d1f23", QPalette.Button: "#ffffff",
            QPalette.ButtonText: "#1d1f23", QPalette.Highlight: "#2f7fd6",
            QPalette.HighlightedText: "#ffffff", QPalette.Link: "#b07800",
            QPalette.Mid: "#d5d8dd", QPalette.PlaceholderText: "#7a808a",
            QPalette.ToolTipBase: "#ffffff", QPalette.ToolTipText: "#1d1f23",
        }
    for ruolo, colore in colori.items():
        p.setColor(ruolo, QColor(colore))
    p.setColor(QPalette.Disabled, QPalette.ButtonText, QColor("#7a808a"))
    p.setColor(QPalette.Disabled, QPalette.Text, QColor("#7a808a"))
    return p


def applica_tema(app, finestra=None):
    """Segue il tema chiaro/scuro del sistema, anche se cambia mentre il client è aperto."""
    scuro = app.styleHints().colorScheme() == Qt.ColorScheme.Dark
    app.setPalette(tavolozza(scuro))
    if finestra is not None:
        finestra.ridisegna()


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("File server")
    app.setStyle("Fusion")             # stesso aspetto su Windows, macOS e Linux
    applica_tema(app)
    finestra = Finestra(Lista())
    app.styleHints().colorSchemeChanged.connect(lambda *_: applica_tema(app, finestra))
    finestra.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
