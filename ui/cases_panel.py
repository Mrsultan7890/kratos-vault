from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QTableWidget, QTableWidgetItem, QDialog, QFormLayout,
    QLineEdit, QTextEdit, QComboBox, QHeaderView, QFrame,
    QMessageBox, QAbstractItemView
)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor
from ui.theme import STATUS_COLORS, PRIORITY_COLORS
from core.enrichment import get_all_status, should_enrich


class CasesPanel(QWidget):
    case_opened = pyqtSignal(str)  # case_id

    def __init__(self, db, parent=None):
        super().__init__(parent)
        self.db = db
        self._build_ui()
        self.refresh()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        # Toolbar
        toolbar = QHBoxLayout()
        title = QLabel("Case Management")
        title.setObjectName("section_title")
        toolbar.addWidget(title)
        toolbar.addStretch()

        self.btn_new = QPushButton("＋  New Case")
        self.btn_new.setObjectName("btn_primary")
        self.btn_new.setFixedHeight(34)
        self.btn_new.clicked.connect(self._new_case)

        self.btn_open = QPushButton("▶  Open")
        self.btn_open.setFixedHeight(34)
        self.btn_open.clicked.connect(self._open_selected)

        self.btn_edit = QPushButton("✎  Edit")
        self.btn_edit.setFixedHeight(34)
        self.btn_edit.clicked.connect(self._edit_selected)

        self.btn_delete = QPushButton("✕  Delete")
        self.btn_delete.setObjectName("btn_danger")
        self.btn_delete.setFixedHeight(34)
        self.btn_delete.clicked.connect(self._delete_selected)

        for btn in [self.btn_new, self.btn_open, self.btn_edit, self.btn_delete]:
            toolbar.addWidget(btn)
        layout.addLayout(toolbar)

        # Table
        self.table = QTableWidget()
        self.table.setColumnCount(7)
        self.table.setHorizontalHeaderLabels(
            ["Name", "Status", "Priority", "Entities", "Media", "Enrichment", "Updated"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for col in (1, 2, 3, 4, 5, 6):
            self.table.horizontalHeader().setSectionResizeMode(
                col, QHeaderView.ResizeMode.ResizeToContents)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.doubleClicked.connect(self._open_selected)
        layout.addWidget(self.table)

    def refresh(self):
        cases = self.db.list_cases()
        self.table.setRowCount(len(cases))
        self._cases = cases
        all_status = get_all_status()
        for row, c in enumerate(cases):
            stats = self.db.case_stats(c["id"])
            # Enrichment coverage for this case
            entities = self.db.list_entities(c["id"])
            enrichable = [e for e in entities if should_enrich(e)]
            done = sum(1 for e in enrichable
                       if all_status.get(e["id"], {}).get("status") == "done")
            failed = sum(1 for e in enrichable
                         if all_status.get(e["id"], {}).get("status") == "failed")
            if enrichable:
                pct = done * 100 // len(enrichable)
                enrich_str = f"{done}/{len(enrichable)} ({pct}%)"
                if failed:
                    enrich_str += f"  ⚠{failed}"
                ecolor = "#2ea043" if pct == 100 else "#d29922" if pct >= 50 else "#f85149"
            else:
                enrich_str = "—"
                ecolor = "#4a5568"
            items = [
                QTableWidgetItem(c["name"]),
                QTableWidgetItem(c["status"]),
                QTableWidgetItem(c["priority"]),
                QTableWidgetItem(str(stats["entities"])),
                QTableWidgetItem(str(stats["media"])),
                QTableWidgetItem(enrich_str),
                QTableWidgetItem(c["updated"][:16].replace("T", " ")),
            ]
            items[0].setData(Qt.ItemDataRole.UserRole, c["id"])
            color = STATUS_COLORS.get(c["status"], "#30363d")
            items[1].setForeground(QColor(color))
            pcolor = PRIORITY_COLORS.get(c["priority"], "#8b949e")
            items[2].setForeground(QColor(pcolor))
            items[5].setForeground(QColor(ecolor))
            items[5].setToolTip(
                f"{done} enriched, {failed} failed, {len(enrichable) - done - failed} pending"
                if enrichable else "No enrichable entities in this case")
            for col, item in enumerate(items):
                item.setTextAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
                self.table.setItem(row, col, item)

    def _selected_id(self):
        row = self.table.currentRow()
        if row < 0:
            return None
        item = self.table.item(row, 0)
        return item.data(Qt.ItemDataRole.UserRole) if item else None

    def _new_case(self):
        dlg = CaseDialog(self.db, parent=self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self.refresh()

    def _open_selected(self):
        cid = self._selected_id()
        if cid:
            self.case_opened.emit(cid)

    def _edit_selected(self):
        cid = self._selected_id()
        if not cid:
            return
        case = self.db.get_case(cid)
        dlg = CaseDialog(self.db, case=case, parent=self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self.refresh()

    def _delete_selected(self):
        cid = self._selected_id()
        if not cid:
            return
        case = self.db.get_case(cid)
        reply = QMessageBox.question(
            self, "Delete Case",
            f"Delete case '{case['name']}' and ALL its data?\nThis cannot be undone.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if reply == QMessageBox.StandardButton.Yes:
            self.db.delete_case(cid)
            self.refresh()


class CaseDialog(QDialog):
    def __init__(self, db, case=None, parent=None):
        super().__init__(parent)
        self.db = db
        self.case = case
        self.setWindowTitle("Edit Case" if case else "New Case")
        self.setMinimumWidth(420)
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        form = QFormLayout()
        form.setSpacing(10)

        self.name_edit = QLineEdit(self.case["name"] if self.case else "")
        self.name_edit.setPlaceholderText("e.g., Operation Nightfall")

        self.desc_edit = QTextEdit(self.case["description"] if self.case else "")
        self.desc_edit.setPlaceholderText("Case overview, objectives...")
        self.desc_edit.setMaximumHeight(100)

        self.status_combo = QComboBox()
        self.status_combo.addItems(["Active", "Pending", "Closed", "Archived"])
        if self.case:
            self.status_combo.setCurrentText(self.case["status"])

        self.priority_combo = QComboBox()
        self.priority_combo.addItems(["Critical", "High", "Medium", "Low"])
        if self.case:
            self.priority_combo.setCurrentText(self.case["priority"])

        form.addRow("Name *", self.name_edit)
        form.addRow("Description", self.desc_edit)
        form.addRow("Status", self.status_combo)
        form.addRow("Priority", self.priority_combo)
        layout.addLayout(form)

        btns = QHBoxLayout()
        btns.addStretch()
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        save = QPushButton("Save Case")
        save.setObjectName("btn_primary")
        save.clicked.connect(self._save)
        btns.addWidget(cancel)
        btns.addWidget(save)
        layout.addLayout(btns)

    def _save(self):
        name = self.name_edit.text().strip()
        if not name:
            QMessageBox.warning(self, "Validation", "Case name is required.")
            return
        kwargs = dict(
            name=name,
            description=self.desc_edit.toPlainText().strip(),
            status=self.status_combo.currentText(),
            priority=self.priority_combo.currentText(),
        )
        if self.case:
            self.db.update_case(self.case["id"], **kwargs)
        else:
            self.db.create_case(**kwargs)
        self.accept()
