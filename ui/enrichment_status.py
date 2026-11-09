from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView
)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor
from core.enrichment import get_all_status, should_enrich, set_entity_status


class EnrichmentStatusDialog(QDialog):
    rerun_requested = pyqtSignal(str)  # entity_id

    def __init__(self, db, case_id, parent=None):
        super().__init__(parent)
        self.db      = db
        self.case_id = case_id
        self.setWindowTitle("🔍 Enrichment Status")
        self.setMinimumSize(700, 420)
        self._build_ui()
        self._load()

    def _build_ui(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 16, 16, 16)
        lay.setSpacing(10)

        title = QLabel("Enrichment Status — All Entities")
        title.setStyleSheet("font-size: 14px; font-weight: 700; color: #42a5f5;")
        lay.addWidget(title)

        self.table = QTableWidget()
        self.table.setColumnCount(5)
        self.table.setHorizontalHeaderLabels(["Entity", "Type", "Value", "Status", "Detail"])
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        lay.addWidget(self.table)

        btns = QHBoxLayout()
        btns.addStretch()

        self.btn_rerun = QPushButton("▶  Re-run Selected")
        self.btn_rerun.setObjectName("btn_warning")
        self.btn_rerun.setFixedHeight(34)
        self.btn_rerun.clicked.connect(self._rerun_selected)

        refresh_btn = QPushButton("↻  Refresh")
        refresh_btn.setFixedHeight(34)
        refresh_btn.clicked.connect(self._load)

        close_btn = QPushButton("Close")
        close_btn.setFixedHeight(34)
        close_btn.clicked.connect(self.accept)

        btns.addWidget(refresh_btn)
        btns.addWidget(self.btn_rerun)
        btns.addWidget(close_btn)
        lay.addLayout(btns)

    def _load(self):
        if not self.case_id:
            return

        entities = self.db.list_entities(self.case_id)
        enrichable = [e for e in entities if should_enrich(e)]
        all_status = get_all_status()

        self.table.setRowCount(len(enrichable))
        self._entity_ids = []

        STATUS_COLORS = {
            "done":    "#2ea043",
            "running": "#42a5f5",
            "failed":  "#f85149",
            "pending": "#d29922",
        }

        for row, e in enumerate(enrichable):
            eid    = e["id"]
            status = all_status.get(eid, {})
            s      = status.get("status", "pending")
            detail = status.get("detail", "Not run yet")

            icon_map = {"done": "✅", "running": "⏳", "failed": "❌", "pending": "⏸"}
            icon = icon_map.get(s, "⏸")

            items = [
                QTableWidgetItem((e.get("name") or e.get("value", ""))[:60]),
                QTableWidgetItem(e.get("type", "")),
                QTableWidgetItem(e.get("value", "")[:60]),
                QTableWidgetItem(f"{icon} {s.upper()}"),
                QTableWidgetItem((detail or "Not run yet")[:80]),
            ]
            items[0].setData(Qt.ItemDataRole.UserRole, eid)
            color = STATUS_COLORS.get(s, "#9ca3af")
            items[3].setForeground(QColor(color))

            for col, item in enumerate(items):
                item.setTextAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
                self.table.setItem(row, col, item)

            self._entity_ids.append(eid)

        # Summary bar
        done    = sum(1 for e in enrichable if all_status.get(e["id"], {}).get("status") == "done")
        failed  = sum(1 for e in enrichable if all_status.get(e["id"], {}).get("status") == "failed")
        pending = len(enrichable) - done - failed
        self.setWindowTitle(
            f"🔍 Enrichment Status  —  ✅ {done}  ❌ {failed}  ⏸ {pending}"
        )

    def _rerun_selected(self):
        rows = set(i.row() for i in self.table.selectedItems())
        for row in rows:
            item = self.table.item(row, 0)
            if item:
                eid = item.data(Qt.ItemDataRole.UserRole)
                # Reset status BEFORE emitting — _trigger_enrichment skips 'done'
                set_entity_status(eid, "pending", "Manual re-run requested")
                self.rerun_requested.emit(eid)
        self.accept()
