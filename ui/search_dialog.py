from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLineEdit, QPushButton,
    QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView, QLabel
)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor, QKeySequence, QShortcut

from ui.theme import ENTITY_COLORS


class GlobalSearchDialog(QDialog):
    """Search across ALL cases: entities, notes, media, timeline events."""
    case_open_requested = pyqtSignal(str)  # case_id

    KIND_COLORS = {
        "Entity":  "#42a5f5",
        "Note":    "#06b6d4",
        "Media":   "#f59e0b",
        "Event":   "#8b5cf6",
        "Case":    "#2ea043",
    }

    def __init__(self, db, main_window, parent=None):
        super().__init__(parent)
        self.db = db
        self.mw = main_window
        self.setWindowTitle("🔎 Global Search — all cases")
        self.setMinimumSize(780, 520)
        self._build_ui()
        self._search_shortcut = QShortcut(QKeySequence("Ctrl+F"), self)
        self._search_shortcut.activated.connect(self._focus)
        self.search_edit.setFocus()

    def _build_ui(self):
        lay = QVBoxLayout(self)
        lay.setSpacing(10)

        row = QHBoxLayout()
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText(
            "Search entities, notes, media, events across all cases…  (min 2 chars)")
        self.search_edit.returnPressed.connect(self.refresh)
        btn = QPushButton("Search")
        btn.setObjectName("btn_primary")
        btn.clicked.connect(self.refresh)
        row.addWidget(self.search_edit, 1)
        row.addWidget(btn)
        lay.addLayout(row)

        self.status_lbl = QLabel("")
        self.status_lbl.setStyleSheet("color:#8b949e;font-size:12px;")
        lay.addWidget(self.status_lbl)

        self.table = QTableWidget()
        self.table.setColumnCount(5)
        self.table.setHorizontalHeaderLabels(
            ["Kind", "Match", "Detail", "Case", "Updated"])
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.doubleClicked.connect(self._open_selected)
        lay.addWidget(self.table)

        hint = QLabel("Double-click a result to open its case.")
        hint.setStyleSheet("color:#90a4ae;font-size:11px;")
        lay.addWidget(hint)

    def _focus(self):
        self.search_edit.setFocus()
        self.search_edit.selectAll()

    def refresh(self):
        q = self.search_edit.text().strip()
        if len(q) < 2:
            self.status_lbl.setText("Type at least 2 characters.")
            self.table.setRowCount(0)
            return
        like = f"%{q}%"
        conn = self.db._conn
        results = []

        cases = {c["id"]: c["name"] for c in self.db.list_cases()}

        for cid, cname in cases.items():
            for r in conn.execute(
                "SELECT * FROM entities WHERE case_id=? AND "
                "(name LIKE ? OR value LIKE ? OR notes LIKE ?) LIMIT 50",
                    (cid, like, like, like)).fetchall():
                results.append(("Entity", r["name"] or r["value"],
                                f"[{r['type']}] {r['value']}", cname, cid,
                                r["updated"][:10]))
            for r in conn.execute(
                "SELECT * FROM notes WHERE case_id=? AND "
                "(title LIKE ? OR content LIKE ?) LIMIT 30",
                    (cid, like, like)).fetchall():
                results.append(("Note", r["title"],
                                r["content"][:120].replace("\n", " "), cname, cid,
                                r["updated"][:10]))
            for r in conn.execute(
                "SELECT id,case_id,name,created FROM media WHERE case_id=? AND name LIKE ? LIMIT 20",
                    (cid, like)).fetchall():
                results.append(("Media", r["name"], "", cname, cid, r["created"][:10]))
            for r in conn.execute(
                "SELECT * FROM timeline WHERE case_id=? AND "
                "(title LIKE ? OR detail LIKE ?) LIMIT 20",
                    (cid, like, like)).fetchall():
                results.append(("Event", r["title"], r["detail"][:100], cname, cid,
                                r["created"][:10]))

        self.table.setRowCount(len(results))
        self._results = [(r[0], r[4]) for r in results]  # (kind, case_id)
        for row, (kind, match, detail, cname, cid, updated) in enumerate(results):
            kind_item = QTableWidgetItem(kind)
            kind_item.setForeground(QColor(self.KIND_COLORS.get(kind, "#8b949e")))
            if kind == "Entity" and detail.startswith("["):
                etype = detail[1:detail.index("]")]
                kind_item.setForeground(QColor(ENTITY_COLORS.get(etype, "#8b949e")))
            items = [
                kind_item,
                QTableWidgetItem(match),
                QTableWidgetItem(detail),
                QTableWidgetItem(cname),
                QTableWidgetItem(updated),
            ]
            for col, item in enumerate(items):
                item.setTextAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
                self.table.setItem(row, col, item)
        self.status_lbl.setText(f"{len(results)} result(s) across {len(cases)} case(s)")

    def _open_selected(self):
        row = self.table.currentRow()
        if row < 0 or row >= len(self._results):
            return
        _kind, case_id = self._results[row]
        self.accept()
        self.case_open_requested.emit(case_id)
