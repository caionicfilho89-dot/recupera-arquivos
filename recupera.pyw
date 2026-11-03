"""Recupera Arquivos — recuperação de arquivos apagados por "carving" (assinatura). Tudo offline.

Varre um pendrive/cartão SD ou uma imagem de disco e extrai fotos, PDFs e documentos que ainda
estão gravados. Para ler um disco direto (ex.: E:) é preciso rodar como administrador.
"""
import ctypes
import os
import string
import subprocess
import sys

from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QIcon, QPainter, QPixmap
from PyQt6.QtWidgets import (QApplication, QCheckBox, QComboBox, QFileDialog, QHBoxLayout, QHeaderView,
                             QLabel, QMessageBox, QProgressBar, QPushButton, QTreeWidget,
                             QTreeWidgetItem, QVBoxLayout, QWidget)

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import carver  # noqa: E402
import ntfs  # noqa: E402
from carver import SPECS  # noqa: E402


def human(n):
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            s = f"{n:.1f}".replace(".", ",") if unit != "B" else str(int(n))
            return f"{s} {unit}"
        n /= 1024


QSS = """
QWidget { background:#11131a; color:#e7e9f0; font:10pt 'Segoe UI'; }
#title { font:700 18pt 'Segoe UI'; }
#warn { color:#ffb84d; }
#info { color:#8a93a8; }
QComboBox, QPushButton { background:#222a38; border:0; border-radius:10px; padding:9px 14px; }
QComboBox:hover, QPushButton:hover { background:#2d3550; }
QPushButton:disabled { color:#5b6377; }
#go { background:#7c5cff; color:#fff; font-weight:600; }
#go:hover { background:#8f74ff; }
QComboBox QAbstractItemView { background:#1b202b; selection-background-color:#2d3550; }
QCheckBox { padding:4px 8px; }
QTreeWidget { background:#161a23; border:0; border-radius:10px; }
QTreeWidget::item { padding:3px 2px; }
QTreeWidget::item:selected { background:#2d3550; }
QHeaderView::section { background:#1b202b; color:#8a93a8; border:0; padding:6px; }
QProgressBar { background:#1b202b; border:0; border-radius:7px; height:10px; text-align:center; }
QProgressBar::chunk { background:#7c5cff; border-radius:7px; }
"""

DRIVE_KIND = {2: "removível", 3: "fixo", 4: "rede", 5: "CD/DVD", 6: "RAM"}


def list_drives():
    out = []
    get_type = ctypes.windll.kernel32.GetDriveTypeW
    for letter in string.ascii_uppercase:
        root = f"{letter}:\\"
        if os.path.exists(root):
            out.append((f"{letter}:", DRIVE_KIND.get(get_type(root), "?")))
    return out


def is_admin():
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:  # noqa: BLE001
        return False


def app_icon():
    pm = QPixmap(64, 64)
    pm.fill(QColor("transparent"))
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setBrush(QColor("#7c5cff"))
    p.setPen(Qt.PenStyle.NoPen)
    p.drawRoundedRect(8, 8, 48, 48, 12, 12)
    p.setPen(QColor("white"))
    p.setFont(QFont("Segoe UI", 26))
    p.drawText(pm.rect(), Qt.AlignmentFlag.AlignCenter, "⏮")
    p.end()
    return QIcon(pm)


class Task(QThread):
    progress = pyqtSignal(int, int)
    done = pyqtSignal(object, str)

    def __init__(self, worker, parent=None):
        super().__init__(parent)
        self.worker = worker
        self._stop = False

    def stop(self):
        self._stop = True

    def run(self):
        try:
            rec = self.worker(lambda a, b: self.progress.emit(a, b), lambda: self._stop)
            self.done.emit(rec, "")
        except PermissionError:
            self.done.emit([], "admin")
        except Exception as e:  # noqa: BLE001
            self.done.emit([], str(e))


class Recupera(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Recupera Arquivos")
        self.setWindowIcon(app_icon())
        self.resize(820, 640)
        self.source = None
        self.out_dir = None
        self.task = None

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 16, 18, 14)
        root.setSpacing(9)
        root.addWidget(QLabel("Recupera Arquivos", objectName="title"))
        root.addWidget(QLabel("Recupera fotos e documentos apagados de pendrive, cartão SD ou imagem de "
                              "disco. Tudo no seu PC.", objectName="info"))
        self.admin_lbl = QLabel(objectName="warn")
        self.admin_lbl.setWordWrap(True)
        root.addWidget(self.admin_lbl)

        # modo
        mrow = QHBoxLayout()
        mrow.addWidget(QLabel("Modo:"))
        self.mode = QComboBox()
        self.mode.addItem("Por conteúdo (carving) — acha por tipo, em qualquer disco", "carving")
        self.mode.addItem("NTFS — recupera COM o nome (só partição NTFS)", "ntfs")
        self.mode.activated.connect(self.on_mode)
        mrow.addWidget(self.mode, 1)
        root.addLayout(mrow)

        # origem
        orow = QHBoxLayout()
        orow.addWidget(QLabel("Onde procurar:"))
        self.src_combo = QComboBox()
        self.src_combo.addItem("📄  Escolher imagem de disco (arquivo)…", ("image", None))
        for letter, kind in list_drives():
            self.src_combo.addItem(f"💾  {letter}\\  ({kind})", ("drive", letter))
        self.src_combo.activated.connect(self.pick_source)
        orow.addWidget(self.src_combo, 1)
        root.addLayout(orow)
        self.src_lbl = QLabel("", objectName="info")
        root.addWidget(self.src_lbl)

        # destino
        drow = QHBoxLayout()
        out_btn = QPushButton("📂  Salvar os recuperados em…")
        out_btn.clicked.connect(self.pick_out)
        self.out_lbl = QLabel("(escolha uma pasta em OUTRO disco)", objectName="info")
        drow.addWidget(out_btn)
        drow.addWidget(self.out_lbl, 1)
        root.addLayout(drow)

        # tipos
        trow = QHBoxLayout()
        self.types_lbl = QLabel("Tipos:")
        trow.addWidget(self.types_lbl)
        self.checks = {}
        for key, spec in SPECS.items():
            cb = QCheckBox(spec["label"])
            cb.setChecked(True)
            self.checks[key] = cb
            trow.addWidget(cb)
        trow.addStretch(1)
        root.addLayout(trow)

        # ação
        arow = QHBoxLayout()
        self.go = QPushButton("🔎  Recuperar", objectName="go")
        self.go.clicked.connect(self.start)
        self.stop_btn = QPushButton("⏹  Parar")
        self.stop_btn.clicked.connect(lambda: self.task and self.task.stop())
        self.stop_btn.setEnabled(False)
        arow.addWidget(self.go)
        arow.addWidget(self.stop_btn)
        arow.addStretch(1)
        root.addLayout(arow)

        self.prog = QProgressBar()
        self.prog.hide()
        root.addWidget(self.prog)
        self.status = QLabel("", objectName="info")
        self.status.setWordWrap(True)
        root.addWidget(self.status)

        self.results = QTreeWidget()
        self.results.setColumnCount(3)
        self.results.setHeaderLabels(["Tipo", "Tamanho", "Arquivo recuperado"])
        self.results.header().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.results.setColumnWidth(0, 160)
        self.results.setColumnWidth(1, 100)
        self.results.itemDoubleClicked.connect(
            lambda it, _c: self._open(it.data(0, Qt.ItemDataRole.UserRole)))
        root.addWidget(self.results, 1)

        brow = QHBoxLayout()
        brow.addStretch(1)
        self.open_btn = QPushButton("📂  Abrir pasta dos recuperados")
        self.open_btn.setEnabled(False)
        self.open_btn.clicked.connect(lambda: self.out_dir and os.startfile(self.out_dir))
        brow.addWidget(self.open_btn)
        root.addLayout(brow)

        self.refresh_admin()
        self.on_mode()

    def on_mode(self):
        ntfs_mode = self.mode.currentData() == "ntfs"
        self.types_lbl.setEnabled(not ntfs_mode)
        for cb in self.checks.values():
            cb.setEnabled(not ntfs_mode)

    def refresh_admin(self):
        if is_admin():
            self.admin_lbl.setText("")
            self.admin_lbl.hide()
        else:
            self.admin_lbl.show()
            self.admin_lbl.setText("⚠ Sem administrador: dá para varrer imagens de disco (arquivo), mas "
                                   "para ler um pendrive/cartão direto feche e abra como administrador.")

    # ---- origem/destino ----------------------------------------------------
    def pick_source(self, _idx):
        kind, val = self.src_combo.currentData()
        if kind == "image":
            path, _ = QFileDialog.getOpenFileName(self, "Escolher imagem de disco", "",
                                                  "Imagens de disco (*.img *.dd *.iso *.bin *.raw);;Todos (*.*)")
            if path:
                self.source = path
                self.src_lbl.setText(f"Imagem: {path}")
            else:
                self.source = None
                self.src_lbl.setText("")
        else:
            self.source = val
            self.src_lbl.setText(f"Disco {val}\\  —  precisa de administrador para ler")

    def pick_out(self):
        d = QFileDialog.getExistingDirectory(self, "Pasta para salvar os recuperados")
        if d:
            self.out_dir = d
            self.out_lbl.setText(d)

    def _src_drive(self):
        if not self.source:
            return None
        if len(self.source) == 2 and self.source[1] == ":":
            return self.source[0].upper()
        return (os.path.splitdrive(os.path.abspath(self.source))[0] or "").rstrip(":").upper()

    # ---- recuperar ---------------------------------------------------------
    def start(self):
        if self.task and self.task.isRunning():
            return
        if not self.source:
            return self.msg("Escolha onde procurar (uma imagem ou um disco).")
        if not self.out_dir:
            return self.msg("Escolha a pasta onde salvar os arquivos recuperados.")
        out_drive = (os.path.splitdrive(os.path.abspath(self.out_dir))[0] or "").rstrip(":").upper()
        if out_drive and out_drive == self._src_drive():
            return self.msg("A pasta de saída está no MESMO disco de onde você quer recuperar.\n\n"
                            "Isso pode sobregravar justamente o que você tenta salvar. Escolha uma pasta "
                            "em outro disco (outro pendrive, HD externo, etc.).")
        src, out = self.source, self.out_dir
        if self.mode.currentData() == "ntfs":
            worker = lambda prog, stop: ntfs.scan_ntfs(src, out, progress=prog, should_stop=stop)  # noqa: E731
        else:
            types = [k for k, cb in self.checks.items() if cb.isChecked()]
            if not types:
                return self.msg("Marque pelo menos um tipo de arquivo.")
            worker = lambda prog, stop: carver.carve(src, out, types, progress=prog, should_stop=stop)  # noqa: E731

        self.results.clear()
        self.prog.show()
        self.prog.setRange(0, 0)
        self.go.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.open_btn.setEnabled(False)
        self.status.setStyleSheet("color:#8a93a8;")
        self.status.setText("Varrendo o disco em busca de arquivos… (quanto maior, mais demora)")
        self.task = Task(worker, self)
        self.task.progress.connect(self.on_progress)
        self.task.done.connect(self.on_done)
        self.task.start()

    def on_progress(self, scanned, total):
        if total:
            self.prog.setRange(0, 1000)
            self.prog.setValue(min(1000, int(scanned / total * 1000)))
            self.prog.setFormat(f"{scanned / total * 100:.0f}%  ({human(scanned)} de {human(total)})")
        else:
            self.status.setText(f"Varrendo… {human(scanned)}")

    def on_done(self, rec, err):
        self.prog.hide()
        self.go.setEnabled(True)
        self.stop_btn.setEnabled(False)
        if err == "admin":
            self.status.setStyleSheet("color:#ff6b6b;")
            self.status.setText("✕ Sem permissão para ler esse disco. Feche e abra o programa como "
                                "administrador (botão direito › Executar como administrador).")
            return
        if err:
            self.status.setStyleSheet("color:#ff6b6b;")
            self.status.setText(f"✕ Deu erro: {err}")
            return
        total = sum(r["size"] for r in rec)
        self.status.setStyleSheet("color:#3ddc97;")
        self.status.setText(f"✓ Recuperei {len(rec)} arquivo(s) ({human(total)}) em: {self.out_dir}")
        self.open_btn.setEnabled(bool(rec))
        for r in rec:
            if "kind" in r:   # carving
                col0, nome = SPECS[r["kind"]]["label"], os.path.basename(r["path"])
            else:             # ntfs
                col0, nome = ("resident" if r.get("resident") else "non-resident"), r["name"]
            it = QTreeWidgetItem([col0, human(r["size"]), nome])
            it.setData(0, Qt.ItemDataRole.UserRole, r["path"])
            it.setTextAlignment(1, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self.results.addTopLevelItem(it)

    def _open(self, path):
        if path and os.path.exists(path):
            subprocess.run(["explorer", "/select,", os.path.normpath(path)], check=False)

    def msg(self, text):
        QMessageBox.information(self, "Recupera Arquivos", text)


def main():
    app = QApplication(sys.argv)
    app.setStyleSheet(QSS)
    w = Recupera()
    w.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
