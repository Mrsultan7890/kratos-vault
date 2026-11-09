from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView,
    QComboBox, QFrame
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QFont

ACTION_COLORS = {
    "case_created":   "#1f6feb",
    "case_updated":   "#8b949e",
    "case_deleted":   "#da3633",
    "case_exported":  "#10b981",
    "case_imported":  "#10b981",
    "entity_created": "#2ea043",
    "entity_updated": "#d29922",
    "entity_deleted": "#da3633",
    "edge_created":   "#8b5cf6",
    "edge_deleted":   "#da3633",
    "media_created":  "#f59e0b",
    "media_deleted":  "#da3633",
    "note_created":   "#06b6d4",
    "note_updated":   "#d29922",
    "note_deleted":   "#da3633",
}


class AuditPanel(QWidget):
    """Chain-of-custody view — append-only, tamper-evident audit trail."""

    def __init__(self, db, parent=None):
        super().__init__(parent)
        self.db = db
        self.case_id = None  # None = all cases
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        tb = QHBoxLayout()
        title = QLabel("Chain of Custody — Audit Log")
        title.setObjectName("section_title")
        tb.addWidget(title)
        tb.addStretch()

        self.scope_combo = QComboBox()
        self.scope_combo.addItem("All Cases", None)
        self.scope_combo.currentIndexChanged.connect(self._scope_changed)
        tb.addWidget(QLabel("Scope:"))
        tb.addWidget(self.scope_combo)

        self.btn_verify = QPushButton("🔐 Verify Chain")
        self.btn_verify.setObjectName("btn_success")
        self.btn_verify.setToolTip(
            "Recompute every hash in the audit chain.\n"
            "Any tampering (manual DB edit, deleted row) breaks verification.")
        self.btn_verify.clicked.connect(self._verify_chain)
        tb.addWidget(self.btn_verify)

        layout.addLayout(tb)

        info = QLabel(
            "Append-only, tamper-evident trail of every change. Each entry hashes the "
            "previous entry of the case — deleting or editing a row in the DB breaks the chain.")
        info.setStyleSheet("color:#8b949e;font-size:12px;")
        info.setWordWrap(True)
        layout.addWidget(info)

        self.table = QTableWidget()
        self.table.setColumnCount(5)
        self.table.setHorizontalHeaderLabels(
            ["Time", "Action", "Target", "Details", "Hash"])
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        layout.addWidget(self.table)

        self.status_label = QLabel("0 entries")
        self.status_label.setStyleSheet("color: #90a4ae; font-size: 12px;")
        layout.addWidget(self.status_label)

    def set_case(self, case_id):
        """Called when a case is opened — rebuild scope list, keep 'All'."""
        current = self.scope_combo.currentData() if self.scope_combo.currentIndex() > 0 else None
        self.scope_combo.blockSignals(True)
        while self.scope_combo.count() > 1:
            self.scope_combo.removeItem(1)
        for c in self.db.list_cases():
            self.scope_combo.addItem(c["name"], c["id"])
        # restore previous selection if it still exists
        if current:
            idx = self.scope_combo.findData(current)
            self.scope_combo.setCurrentIndex(idx if idx > 0 else 0)
        else:
            self.scope_combo.setCurrentIndex(0)
        self.scope_combo.blockSignals(False)
        self.refresh()

    def _scope_changed(self):
        self.case_id = self.scope_combo.currentData()
        self.refresh()

    def refresh(self):
        rows = self.db.list_audit(self.case_id)
        self.table.setRowCount(len(rows))
        for row, a in enumerate(rows):
            color = ACTION_COLORS.get(a["action"], "#8b949e")
            items = [
                QTableWidgetItem(a["ts"][:19].replace("T", " ")),
                QTableWidgetItem(a["action"]),
                QTableWidgetItem((a["target"] or "")[:44]),
                QTableWidgetItem(a["details"]),
                QTableWidgetItem(a["hash"][:16] + "…"),
            ]
            items[1].setForeground(QColor(color))
            items[1].setFont(QFont("", -1, QFont.Weight.Bold))
            items[4].setToolTip(a["hash"])
            items[2].setToolTip(a["target"])
            for col, item in enumerate(items):
                item.setTextAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
                self.table.setItem(row, col, item)
        self.status_label.setText(f"{len(rows)} audit entries")

    def _verify_chain(self):
        ok, broken_at = self.db.verify_audit_chain(self.case_id)
        if ok:
            self.status_label.setText("✅ Chain verified — every entry intact, no tampering")
            self.status_label.setStyleSheet("color: #2ea043; font-size: 12px; font-weight: 700;")
        else:
            self.status_label.setText(f"🔴 CHAIN BROKEN at entry {broken_at} — evidence tampered!")
            self.status_label.setStyleSheet("color: #f85149; font-size: 12px; font-weight: 700;")
