from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView,
    QComboBox, QLineEdit
)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor

EVENT_COLORS = {
    "case_created":   "#1f6feb",
    "entity_added":   "#2ea043",
    "link_created":   "#8b5cf6",
    "auto_link":      "#6366f1",
    "media_added":    "#f59e0b",
    "note_added":     "#06b6d4",
    "enrichment_done":"#00b4d8",
    "export":         "#10b981",
    "import":         "#10b981",
    "delete":         "#da3633",
}

EVENT_ICONS = {
    "case_created":   "📁",
    "entity_added":   "🔵",
    "link_created":   "🔗",
    "auto_link":      "⚡",
    "media_added":    "🖼",
    "note_added":     "📝",
    "enrichment_done":"🔍",
    "export":         "📤",
    "import":         "📥",
    "delete":         "🗑",
}


class TimelinePanel(QWidget):
    data_changed = pyqtSignal()
    def __init__(self, db, parent=None):
        super().__init__(parent)
        self.db = db
        self.case_id = None
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        tb = QHBoxLayout()
        title = QLabel("Investigation Timeline")
        title.setObjectName("section_title")
        tb.addWidget(title)
        tb.addStretch()

        self.filter_combo = QComboBox()
        self.filter_combo.addItem("All Events", "")
        for etype in EVENT_COLORS:
            self.filter_combo.addItem(etype.replace("_", " ").title(), etype)
        self.filter_combo.currentIndexChanged.connect(self.refresh)

        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("Search events...")
        self.search_edit.setMaximumWidth(200)
        self.search_edit.textChanged.connect(self.refresh)

        btn_clear = QPushButton("Clear Filter")
        btn_clear.clicked.connect(self._clear_filter)

        tb.addWidget(QLabel("Filter:"))
        tb.addWidget(self.filter_combo)
        tb.addWidget(self.search_edit)
        tb.addWidget(btn_clear)
        layout.addLayout(tb)

        self.table = QTableWidget()
        self.table.setColumnCount(4)
        self.table.setHorizontalHeaderLabels(["Type", "Title", "Detail", "Timestamp"])
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        layout.addWidget(self.table)

        self.count_label = QLabel("0 events")
        self.count_label.setStyleSheet("color: #90a4ae; font-size: 12px;")
        layout.addWidget(self.count_label)

    def set_case(self, case_id):
        self.case_id = case_id
        self.refresh()

    def refresh(self):
        if not self.case_id:
            self.table.setRowCount(0)
            return
        events = self.db.list_events(self.case_id)

        type_filter = self.filter_combo.currentData()
        if type_filter:
            events = [e for e in events if e["event_type"] == type_filter]

        search = self.search_edit.text().strip().lower()
        if search:
            events = [e for e in events
                      if search in e["title"].lower() or search in e.get("detail", "").lower()]

        self.table.setRowCount(len(events))
        for row, e in enumerate(events):
            icon = EVENT_ICONS.get(e["event_type"], "•")
            color = EVENT_COLORS.get(e["event_type"], "#8b949e")
            type_item = QTableWidgetItem(f"{icon} {e['event_type'].replace('_', ' ').title()}")
            type_item.setForeground(QColor(color))

            items = [
                type_item,
                QTableWidgetItem(e["title"]),
                QTableWidgetItem(e.get("detail", "")),
                QTableWidgetItem(e["created"][:19].replace("T", " ")),
            ]
            for col, item in enumerate(items):
                item.setTextAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
                self.table.setItem(row, col, item)

        self.count_label.setText(f"{len(events)} events")

    def _clear_filter(self):
        self.filter_combo.setCurrentIndex(0)
        self.search_edit.clear()
