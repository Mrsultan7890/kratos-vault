from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QTableWidget, QTableWidgetItem, QDialog, QFormLayout,
    QLineEdit, QTextEdit, QComboBox, QHeaderView, QMessageBox,
    QAbstractItemView, QSpinBox, QCheckBox, QSplitter,
    QListWidget, QListWidgetItem, QFrame, QApplication, QFileDialog
)
from PyQt6.QtCore import Qt, pyqtSignal, QThread, pyqtSlot
from PyQt6.QtGui import QColor, QFont
from ui.theme import ENTITY_COLORS, ENTITY_TYPES
from core.extractor import extract
from core.enrichment import EnrichmentWorker, should_enrich, get_entity_status


class EntitiesPanel(QWidget):
    entity_selected  = pyqtSignal(dict)
    data_changed     = pyqtSignal()
    notify           = pyqtSignal(str, str)  # title, message

    def __init__(self, db, parent=None):
        super().__init__(parent)
        self.db = db
        self.case_id = None
        self._active_workers = {}  # entity_id -> EnrichmentWorker
        self._workers = set()
        self._remote_enrichment_enabled = False
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        # Toolbar row 1
        tb1 = QHBoxLayout()
        self._toolbar_title = QLabel("Entity Manager")
        self._toolbar_title.setObjectName("section_title")
        tb1.addWidget(self._toolbar_title)
        tb1.addStretch()

        self.btn_add = QPushButton("＋  Add Entity")
        self.btn_add.setObjectName("btn_primary")
        self.btn_add.setFixedHeight(34)
        self.btn_add.setToolTip("Add entity")
        self.btn_add.clicked.connect(self._add_entity)

        self.btn_extract = QPushButton("⚡  Auto-Extract")
        self.btn_extract.setObjectName("btn_warning")
        self.btn_extract.setFixedHeight(34)
        self.btn_extract.setToolTip("Extract IOCs from raw text")
        self.btn_extract.clicked.connect(self._auto_extract)

        self.btn_link = QPushButton("🔗  Link")
        self.btn_link.setFixedHeight(34)
        self.btn_link.setToolTip("Link selected entities")
        self.btn_link.clicked.connect(self._link_entities)

        self.btn_delete = QPushButton("✕  Delete")
        self.btn_delete.setObjectName("btn_danger")
        self.btn_delete.setFixedHeight(34)
        self.btn_delete.setToolTip("Delete selected entities")
        self.btn_delete.clicked.connect(self._delete_selected)

        self.btn_copy = QPushButton("⧉  Copy")
        self.btn_copy.setFixedHeight(34)
        self.btn_copy.setToolTip("Copy selected entity value")
        self.btn_copy.clicked.connect(self._copy_value)

        self.btn_enrich_status = QPushButton("🔍  Enrichment")
        self.btn_enrich_status.setFixedHeight(34)
        self.btn_enrich_status.setToolTip("View enrichment status for all entities")
        self.btn_enrich_status.clicked.connect(self._show_enrichment_status)

        for btn in [self.btn_add, self.btn_extract, self.btn_link, self.btn_copy,
                    self.btn_enrich_status, self.btn_delete]:
            tb1.addWidget(btn)
        layout.addLayout(tb1)

        # Toolbar row 2 - search/filter
        tb2 = QHBoxLayout()
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("Search name, value, notes...")
        self.search_edit.textChanged.connect(self.refresh)

        self.type_filter = QComboBox()
        self.type_filter.addItem("All Types", "")
        for t in ENTITY_TYPES:
            self.type_filter.addItem(t, t)
        self.type_filter.currentIndexChanged.connect(self.refresh)

        self.conf_filter = QComboBox()
        self.conf_filter.addItems(["Any Confidence", "High (≥80)", "Medium (≥50)", "Low (<50)"])
        self.conf_filter.currentIndexChanged.connect(self.refresh)

        self._search_label = QLabel("Search:")
        self._type_label = QLabel("Type:")
        self._confidence_label = QLabel("Confidence:")
        tb2.addWidget(self._search_label)
        tb2.addWidget(self.search_edit, 2)
        tb2.addWidget(self._type_label)
        tb2.addWidget(self.type_filter)
        tb2.addWidget(self._confidence_label)
        tb2.addWidget(self.conf_filter)
        layout.addLayout(tb2)

        # Table
        self.table = QTableWidget()
        self.table.setColumnCount(7)
        self.table.setHorizontalHeaderLabels(
            ["Name / Value", "Type", "Tags", "Confidence", "Source", "Links", "Created"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(6, QHeaderView.ResizeMode.Interactive)
        self.table.setColumnWidth(6, 100)
        self._wide_column_modes = [
            QHeaderView.ResizeMode.Stretch,
            QHeaderView.ResizeMode.ResizeToContents,
            QHeaderView.ResizeMode.Stretch,
            QHeaderView.ResizeMode.ResizeToContents,
            QHeaderView.ResizeMode.ResizeToContents,
            QHeaderView.ResizeMode.ResizeToContents,
            QHeaderView.ResizeMode.Interactive,
        ]
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.doubleClicked.connect(self._view_detail)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        layout.addWidget(self.table)

        # Count label
        self.count_label = QLabel("0 entities")
        self.count_label.setStyleSheet("color: #90a4ae; font-size: 12px;")
        layout.addWidget(self.count_label)

        # Ctrl+F jumps to search
        from PyQt6.QtGui import QShortcut, QKeySequence
        self._search_shortcut = QShortcut(QKeySequence("Ctrl+F"), self)
        self._search_shortcut.activated.connect(self._focus_search)

    def set_case(self, case_id):
        self.case_id = case_id
        self.refresh()

    def resizeEvent(self, event):
        compact = self.width() < 850
        if compact != getattr(self, "_compact_layout", None):
            self._compact_layout = compact
            labels = ("＋", "⚡", "🔗", "⧉", "🔍", "✕")
            full = ("＋  Add Entity", "⚡  Auto-Extract", "🔗  Link", "⧉  Copy",
                    "🔍  Enrichment", "✕  Delete")
            buttons = (self.btn_add, self.btn_extract, self.btn_link, self.btn_copy,
                       self.btn_enrich_status, self.btn_delete)
            for button, short, long in zip(buttons, labels, full):
                button.setText(short if compact else long)
                if compact:
                    button.setFixedWidth(40)
                else:
                    button.setMinimumWidth(0)
                    button.setMaximumWidth(16777215)
            self._toolbar_title.setVisible(not compact)
            self._search_label.setVisible(not compact)
            self._type_label.setVisible(not compact)
            self._confidence_label.setVisible(not compact)
            for column, mode in enumerate(self._wide_column_modes):
                self.table.horizontalHeader().setSectionResizeMode(
                    column, QHeaderView.ResizeMode.Interactive if compact else mode)
            if compact:
                for column, width in {0: 160, 1: 75, 2: 140, 3: 110, 4: 95, 5: 60, 6: 100}.items():
                    self.table.setColumnWidth(column, width)
        super().resizeEvent(event)

    def _focus_search(self):
        self.search_edit.setFocus()
        self.search_edit.selectAll()

    def refresh(self):
        if not self.case_id:
            self.table.setRowCount(0)
            self.count_label.setText("Open a case first — entities will appear here")
            return
        search = self.search_edit.text().strip() or None
        type_filter = self.type_filter.currentData() or None
        entities = self.db.list_entities(self.case_id, type_filter=type_filter, search=search)

        # Confidence filter
        cf = self.conf_filter.currentIndex()
        if cf == 1:
            entities = [e for e in entities if e["confidence"] >= 80]
        elif cf == 2:
            entities = [e for e in entities if e["confidence"] >= 50]
        elif cf == 3:
            entities = [e for e in entities if e["confidence"] < 50]

        self.table.setRowCount(len(entities))
        self._entities = entities
        for row, e in enumerate(entities):
            color = ENTITY_COLORS.get(e["type"], "#9ca3af")
            tags_str = ", ".join(e["tags"]) if e["tags"] else ""
            links_count = len(e["linked_to"])

            # Tooltip: everything an investigator needs on hover
            tip_lines = [f"Value: {e['value']}", f"Type: {e['type']}"]
            if tags_str:
                tip_lines.append(f"Tags: {tags_str}")
            if e.get("source"):
                tip_lines.append(f"Source: {e['source']}")
            if e.get("notes"):
                tip_lines.append(f"\nNotes: {e['notes'][:300]}{'…' if len(e.get('notes','')) > 300 else ''}")
            tip = "\n".join(tip_lines)

            items = [
                QTableWidgetItem(e["name"] or e["value"]),
                QTableWidgetItem(e["type"]),
                QTableWidgetItem(tags_str),
                QTableWidgetItem(f"{e['confidence']}%"),
                QTableWidgetItem(e.get("source", "")),
                QTableWidgetItem(str(links_count) if links_count else ""),
                QTableWidgetItem(e["created"][:10]),
            ]
            items[0].setData(Qt.ItemDataRole.UserRole, e["id"])
            for it in items:
                it.setToolTip(tip)
            items[0].setToolTip(f"{e['value']}\n\n(double-click for full details)")
            items[1].setForeground(QColor(color))
            items[1].setFont(QFont("", -1, QFont.Weight.Bold))

            conf = e["confidence"]
            if conf >= 80:
                items[3].setForeground(QColor("#2ea043"))
            elif conf >= 50:
                items[3].setForeground(QColor("#d29922"))
            else:
                items[3].setForeground(QColor("#f85149"))

            for col, item in enumerate(items):
                item.setTextAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
                self.table.setItem(row, col, item)

        self.count_label.setText(f"{len(entities)} entities")

    def _selected_ids(self):
        rows = set(i.row() for i in self.table.selectedItems())
        ids = []
        for row in rows:
            item = self.table.item(row, 0)
            if item:
                ids.append(item.data(Qt.ItemDataRole.UserRole))
        return ids

    def _add_entity(self):
        if not self.case_id:
            QMessageBox.warning(self, "No Case", "Open a case first.")
            return
        dlg = EntityDialog(self.db, self.case_id, parent=self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self.refresh()
            self.data_changed.emit()
            # Auto-trigger enrichment on newly saved entity
            if dlg.entity_result:
                self._trigger_enrichment(dlg.entity_result)

    def _view_detail(self):
        ids = self._selected_ids()
        if not ids:
            return
        entity = self.db.get_entity(ids[0])
        if not entity:
            return
        dlg = EntityDetailDialog(entity, parent=self)
        dlg.edit_requested.connect(lambda: self._edit_selected())
        dlg.exec()

    def _edit_selected(self):
        ids = self._selected_ids()
        if not ids:
            return
        entity = self.db.get_entity(ids[0])
        if not entity:
            return
        dlg = EntityDialog(self.db, self.case_id, entity=entity, parent=self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self.refresh()
            self.data_changed.emit()
            updated = self.db.get_entity(ids[0])
            if updated:
                self._trigger_enrichment(updated)

    def _delete_selected(self):
        ids = self._selected_ids()
        if not ids:
            return
        reply = QMessageBox.question(
            self, "Delete", f"Delete {len(ids)} entity/entities?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if reply == QMessageBox.StandardButton.Yes:
            for eid in ids:
                self.db.delete_entity(eid)
            self.refresh()
            self.data_changed.emit()

    def _copy_value(self):
        ids = self._selected_ids()
        if not ids:
            return
        entity = self.db.get_entity(ids[0])
        if entity:
            QApplication.clipboard().setText(entity["value"])

    def _trigger_enrichment(self, entity: dict, force: bool = False):
        if not should_enrich(entity):
            return
        if not self._remote_enrichment_enabled:
            self.notify.emit(
                "🔒 Remote lookups disabled",
                "Enable Remote Lookups in the top bar to send this entity to OSINT services.")
            return
        eid = entity["id"]
        # Don't re-run if already running
        if eid in self._active_workers and self._active_workers[eid].isRunning():
            return
        # Don't re-run if already done (unless forced)
        if not force and get_entity_status(eid).get("status") == "done":
            return
        worker = EnrichmentWorker(self.db, entity)
        worker.started_signal.connect(self._on_enrich_started)
        worker.finished_signal.connect(self._on_enrich_done)
        worker.error_signal.connect(self._on_enrich_error)
        worker.finished.connect(lambda w=worker, entity_id=eid: (
            self._workers.discard(w),
            self._active_workers.pop(entity_id, None)
            if self._active_workers.get(entity_id) is w else None
        ))
        # Connect to live monitor if set
        if hasattr(self, '_monitor') and self._monitor:
            worker.started_signal.connect(self._monitor.on_started)
            worker.finished_signal.connect(self._monitor.on_finished)
            worker.error_signal.connect(self._monitor.on_error)
            worker.phase_signal.connect(self._monitor.on_phase)
            worker.step_signal.connect(self._monitor.on_step)
        self._active_workers[eid] = worker
        self._workers.add(worker)
        worker.start()

    def set_monitor(self, monitor):
        self._monitor = monitor

    def set_remote_enrichment_enabled(self, enabled: bool):
        self._remote_enrichment_enabled = enabled

    def wait_for_workers(self):
        for worker in tuple(self._workers):
            worker.wait()

    def _trigger_enrichment_by_id(self, entity_id: str, force: bool = False):
        entity = self.db.get_entity(entity_id)
        if entity:
            self._trigger_enrichment(entity, force=force)

    @pyqtSlot(str, str)
    def _on_enrich_started(self, entity_id: str, value: str):
        self.notify.emit("🔍 Enriching...", f"Collecting OSINT for: {value}")

    @pyqtSlot(str, dict)
    def _on_enrich_done(self, entity_id: str, result: dict):
        self._active_workers.pop(entity_id, None)
        value = (result.get("value") or result.get("phone") or result.get("email")
                 or result.get("username") or result.get("handle")
                 or result.get("address") or result.get("org") or entity_id)
        platforms = [p for p, d in result.get("platforms", {}).items()
                     if isinstance(d, dict) and d.get("found")]
        msg = f"Found on: {', '.join(platforms)}" if platforms else "No results found"
        self.notify.emit("✅ Enrichment Done", f"{value} — {msg}")
        self.refresh()
        self.data_changed.emit()

    @pyqtSlot(str, str)
    def _on_enrich_error(self, entity_id: str, error: str):
        self._active_workers.pop(entity_id, None)
        self.notify.emit("❌ Enrichment Failed", error[:120])

    def _show_enrichment_status(self):
        if not self.case_id:
            QMessageBox.warning(self, "No Case", "Open a case first.")
            return
        from ui.enrichment_status import EnrichmentStatusDialog
        dlg = EnrichmentStatusDialog(self.db, self.case_id, parent=self)
        dlg.rerun_requested.connect(self._trigger_enrichment_by_id)
        dlg.exec()

    def _auto_extract(self):
        if not self.case_id:
            QMessageBox.warning(self, "No Case", "Open a case first.")
            return
        dlg = AutoExtractDialog(self.db, self.case_id, parent=self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self.refresh()
            self.data_changed.emit()

    def _link_entities(self):
        if not self.case_id:
            return
        ids = self._selected_ids()
        if len(ids) < 2:
            QMessageBox.information(self, "Link", "Select at least 2 entities to link.")
            return
        dlg = LinkDialog(self.db, self.case_id, preselected=ids, parent=self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self.refresh()
            self.data_changed.emit()


class EntityDialog(QDialog):
    def __init__(self, db, case_id, entity=None, parent=None):
        super().__init__(parent)
        self.db = db
        self.case_id = case_id
        self.entity = entity
        self.entity_result = None  # created/updated row, set on successful save
        self.setWindowTitle("Edit Entity" if entity else "Add Entity")
        self.setMinimumWidth(480)
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        form = QFormLayout()
        form.setSpacing(10)

        self.type_combo = QComboBox()
        self.type_combo.addItems(ENTITY_TYPES)
        if self.entity:
            self.type_combo.setCurrentText(self.entity["type"])
        self.type_combo.currentTextChanged.connect(self._on_type_changed)
        # Once the user manually picks a type, stop auto-suggesting
        self.type_combo.activated.connect(self._on_type_touched)
        self._type_touched = self.entity is not None

        self.name_edit = QLineEdit(self.entity["name"] if self.entity else "")
        self.name_edit.setPlaceholderText("Display name")

        self.value_edit = QLineEdit(self.entity["value"] if self.entity else "")
        self.value_edit.setPlaceholderText("Actual value (email, IP, hash, file path, etc.)")
        # ML auto-suggest entity type as you type the value
        self.value_edit.textChanged.connect(self._suggest_type)

        # Image/Document file picker row
        self._file_row = QHBoxLayout()
        self._file_btn = QPushButton("📁  Browse File")
        self._file_btn.setFixedHeight(30)
        self._file_btn.clicked.connect(self._browse_file)
        self._file_lbl = QLabel("No file selected")
        self._file_lbl.setStyleSheet("color: #90a4ae; font-size: 11px;")
        self._file_lbl.setTextFormat(Qt.TextFormat.PlainText)
        self._file_row.addWidget(self._file_btn)
        self._file_row.addWidget(self._file_lbl, 1)
        self._file_widget = QWidget()
        self._file_widget.setLayout(self._file_row)

        self.notes_edit = QTextEdit(self.entity["notes"] if self.entity else "")
        self.notes_edit.setPlaceholderText("Investigation notes...")
        self.notes_edit.setMaximumHeight(90)

        self.tags_edit = QLineEdit(", ".join(self.entity["tags"]) if self.entity else "")
        self.tags_edit.setPlaceholderText("tag1, tag2, tag3")

        self.source_edit = QLineEdit(self.entity.get("source", "") if self.entity else "")
        self.source_edit.setPlaceholderText("e.g., LinkedIn, Shodan, manual")

        self.conf_spin = QSpinBox()
        self.conf_spin.setRange(0, 100)
        self.conf_spin.setSuffix("%")
        self.conf_spin.setValue(self.entity["confidence"] if self.entity else 50)

        form.addRow("Type *", self.type_combo)
        form.addRow("Name *", self.name_edit)
        form.addRow("Value *", self.value_edit)
        self._file_form_row = form.rowCount()
        form.addRow("File", self._file_widget)
        self._form = form
        form.addRow("Notes", self.notes_edit)
        form.addRow("Tags", self.tags_edit)
        form.addRow("Source", self.source_edit)
        form.addRow("Confidence", self.conf_spin)
        layout.addLayout(form)

        btns = QHBoxLayout()
        btns.addStretch()
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        save = QPushButton("Save")
        save.setObjectName("btn_primary")
        save.clicked.connect(self._save)
        btns.addWidget(cancel)
        btns.addWidget(save)
        layout.addLayout(btns)

        # Show/hide file picker based on initial type
        self._on_type_changed(self.type_combo.currentText())

    def _on_type_changed(self, type_name: str):
        show = type_name in ("Image", "Document")
        self._file_widget.setVisible(show)
        label = self._form.labelForField(self._file_widget)
        if label:
            label.setVisible(show)

    def _on_type_touched(self, _index):
        self._type_touched = True

    def _suggest_type(self, text: str):
        """ML classifier suggests entity type from the value (until the user
        picks one manually)."""
        if self._type_touched or not text or len(text.strip()) < 4:
            return
        try:
            from core.ml.classifier import predict
            etype, conf = predict(text.strip())
            if conf >= 0.55 and etype in ENTITY_TYPES:
                idx = self.type_combo.findText(etype)
                if idx >= 0 and self.type_combo.currentIndex() != idx:
                    self.type_combo.setCurrentIndex(idx)
                    self.type_combo.setToolTip(
                        f"ML suggestion: {etype} ({conf:.0%} confidence)")
        except Exception:
            pass

    def _browse_file(self):
        t = self.type_combo.currentText()
        if t == "Image":
            filt = "Images (*.png *.jpg *.jpeg *.gif *.bmp *.webp);;All Files (*)"
        else:
            filt = "Documents (*.pdf *.docx *.doc *.txt *.xlsx *.pptx);;All Files (*)"
        path, _ = QFileDialog.getOpenFileName(self, "Select File", "", filt)
        if path:
            self._selected_file = path
            from pathlib import Path
            self._file_lbl.setText(Path(path).name)
            # Auto-fill value with path
            self.value_edit.setText(path)
            if not self.name_edit.text():
                self.name_edit.setText(Path(path).name)

    def _save(self):
        name = self.name_edit.text().strip()
        value = self.value_edit.text().strip()
        if not name or not value:
            QMessageBox.warning(self, "Validation", "Name and Value are required.")
            return
        # Warn when creating an entity that already exists in this case
        if not self.entity:
            existing = self.db.list_entities(self.case_id, search=value)
            if any(e["type"] == self.type_combo.currentText() and
                   e["value"] == value for e in existing):
                reply = QMessageBox.question(
                    self, "Duplicate",
                    "An entity with this type and value already exists in the case.\n"
                    "Add anyway?", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
                if reply != QMessageBox.StandardButton.Yes:
                    return
        tags = [t.strip() for t in self.tags_edit.text().split(",") if t.strip()]
        kwargs = dict(
            type_=self.type_combo.currentText(),
            name=name, value=value,
            notes=self.notes_edit.toPlainText().strip(),
            tags=tags,
            source=self.source_edit.text().strip(),
            confidence=self.conf_spin.value(),
        )
        if self.entity:
            self.db.update_entity(self.entity["id"],
                type=kwargs["type_"], name=kwargs["name"], value=kwargs["value"],
                notes=kwargs["notes"], tags=kwargs["tags"],
                source=kwargs["source"], confidence=kwargs["confidence"])
            self.entity_result = self.db.get_entity(self.entity["id"])
        else:
            self.entity_result = self.db.create_entity(self.case_id, **kwargs)
        self.accept()


class AutoExtractDialog(QDialog):
    def __init__(self, db, case_id, parent=None):
        super().__init__(parent)
        self.db = db
        self.case_id = case_id
        self.setWindowTitle("Auto-Extract IOCs")
        self.setMinimumSize(600, 500)
        self._extracted = []
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        layout.addWidget(QLabel("Paste raw text (emails, IPs, URLs, hashes, crypto addresses):"))
        self.text_edit = QTextEdit()
        self.text_edit.setPlaceholderText("Paste any raw text, logs, reports, chat exports...")
        self.text_edit.setMinimumHeight(150)
        layout.addWidget(self.text_edit)

        extract_btn = QPushButton("⚡ Extract")
        extract_btn.setObjectName("btn_primary")
        extract_btn.clicked.connect(self._do_extract)
        layout.addWidget(extract_btn)

        layout.addWidget(QLabel("Extracted entities (uncheck to skip):"))
        self.result_list = QListWidget()
        self.result_list.setAlternatingRowColors(True)
        layout.addWidget(self.result_list)

        self.status_label = QLabel("")
        self.status_label.setStyleSheet("color: #90a4ae; font-size: 12px;")
        layout.addWidget(self.status_label)

        btns = QHBoxLayout()
        btns.addStretch()
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        self.import_btn = QPushButton("Import Selected")
        self.import_btn.setObjectName("btn_success")
        self.import_btn.clicked.connect(self._import_selected)
        self.import_btn.setEnabled(False)
        btns.addWidget(cancel)
        btns.addWidget(self.import_btn)
        layout.addLayout(btns)

    def _do_extract(self):
        text = self.text_edit.toPlainText()
        self._extracted = extract(text)
        self.result_list.clear()
        if not self._extracted:
            self.status_label.setText("No IOCs found.")
            return
        for e in self._extracted:
            item = QListWidgetItem(f"[{e['type']}] {e['value']}")
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked)
            item.setForeground(QColor(ENTITY_COLORS.get(e["type"], "#9ca3af")))
            self.result_list.addItem(item)
        self.status_label.setText(f"Found {len(self._extracted)} IOCs")
        self.import_btn.setEnabled(True)

    def _import_selected(self):
        count = skipped = 0
        for i in range(self.result_list.count()):
            item = self.result_list.item(i)
            if item.checkState() == Qt.CheckState.Checked:
                e = self._extracted[i]
                row = self.db.create_entity(
                    self.case_id, e["type"], e["name"], e["value"],
                    tags=e["tags"], confidence=e["confidence"], source=e["source"]
                )
                if row.get("duplicate"):
                    skipped += 1
                else:
                    count += 1
        msg = f"Imported {count} entities."
        if skipped:
            msg += f" Skipped {skipped} duplicate(s) (already in case)."
        self.status_label.setText(msg)
        self.accept()


class LinkDialog(QDialog):
    def __init__(self, db, case_id, preselected=None, parent=None):
        super().__init__(parent)
        self.db = db
        self.case_id = case_id
        self.preselected = preselected or []
        self.setWindowTitle("Create Link")
        self.setMinimumWidth(420)
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        entities = self.db.list_entities(self.case_id)

        form = QFormLayout()
        self.source_combo = QComboBox()
        self.target_combo = QComboBox()
        for e in entities:
            label = f"[{e['type']}] {e['name'] or e['value']}"
            self.source_combo.addItem(label, e["id"])
            self.target_combo.addItem(label, e["id"])

        if len(self.preselected) >= 2:
            ids = [e["id"] for e in entities]
            if self.preselected[0] in ids:
                self.source_combo.setCurrentIndex(ids.index(self.preselected[0]))
            if self.preselected[1] in ids:
                self.target_combo.setCurrentIndex(ids.index(self.preselected[1]))

        self.label_edit = QLineEdit()
        self.label_edit.setPlaceholderText("e.g., owns, related-to, communicates-with")

        self.weight_spin = QSpinBox()
        self.weight_spin.setRange(1, 10)
        self.weight_spin.setValue(1)

        form.addRow("Source", self.source_combo)
        form.addRow("Target", self.target_combo)
        form.addRow("Label", self.label_edit)
        form.addRow("Weight", self.weight_spin)
        layout.addLayout(form)

        btns = QHBoxLayout()
        btns.addStretch()
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        save = QPushButton("Create Link")
        save.setObjectName("btn_primary")
        save.clicked.connect(self._save)
        btns.addWidget(cancel)
        btns.addWidget(save)
        layout.addLayout(btns)

    def _save(self):
        src = self.source_combo.currentData()
        tgt = self.target_combo.currentData()
        if src == tgt:
            QMessageBox.warning(self, "Error", "Source and target must be different.")
            return
        self.db.create_edge(self.case_id, src, tgt,
                            label=self.label_edit.text().strip(),
                            weight=self.weight_spin.value())
        se = self.db.get_entity(src)
        te = self.db.get_entity(tgt)
        if se and te:
            self.db.add_event(self.case_id, "link_created",
                              f"Link: {se['name']} → {te['name']}",
                              detail=self.label_edit.text().strip())
        self.accept()


class EntityDetailDialog(QDialog):
    edit_requested = pyqtSignal()

    def __init__(self, entity: dict, parent=None):
        super().__init__(parent)
        self.entity = entity
        self.setWindowTitle(f"🔍  {entity.get('name') or entity.get('value')}")
        self.setMinimumSize(720, 580)
        self._build_ui()

    def _build_ui(self):
        from core.enrichment import get_entity_status
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 16, 16, 16)
        lay.setSpacing(10)

        # ── Header row ────────────────────────────────────────────────
        header = QFrame()
        header.setStyleSheet("""
            QFrame {
                background-color: #0d1321;
                border: 1px solid #1a2540;
                border-left: 4px solid #42a5f5;
                border-radius: 6px;
            }
        """)
        hl = QHBoxLayout(header)
        hl.setContentsMargins(14, 10, 14, 10)

        color = ENTITY_COLORS.get(self.entity.get("type", ""), "#9ca3af")
        name_lbl = QLabel(self.entity.get("name") or self.entity.get("value"))
        name_lbl.setStyleSheet(f"font-size: 15px; font-weight: 800; color: {color};")
        name_lbl.setTextFormat(Qt.TextFormat.PlainText)

        type_lbl = QLabel(self.entity.get("type", ""))
        type_lbl.setStyleSheet(
            f"font-size: 11px; font-weight: 700; color: {color}; "
            f"background: #0b0f1a; border: 1px solid {color}; "
            f"border-radius: 4px; padding: 2px 8px;")

        conf = self.entity.get("confidence", 0)
        conf_color = "#2ea043" if conf >= 80 else "#d29922" if conf >= 50 else "#f85149"
        conf_lbl = QLabel(f"{conf}% confidence")
        conf_lbl.setStyleSheet(f"font-size: 11px; color: {conf_color}; font-weight: 700;")

        status = get_entity_status(self.entity["id"])
        s = status.get("status", "pending")
        s_icon = {"done": "✅", "running": "⏳", "failed": "❌", "pending": "⏸"}.get(s, "⏸")
        s_color = {"done": "#2ea043", "running": "#42a5f5", "failed": "#f85149", "pending": "#d29922"}.get(s, "#9ca3af")
        status_lbl = QLabel(f"{s_icon} {s.upper()}")
        status_lbl.setStyleSheet(f"font-size: 11px; color: {s_color}; font-weight: 700;")

        hl.addWidget(name_lbl)
        hl.addStretch()
        hl.addWidget(type_lbl)
        hl.addSpacing(8)
        hl.addWidget(conf_lbl)
        hl.addSpacing(8)
        hl.addWidget(status_lbl)
        lay.addWidget(header)

        # ── Value + Tags row ──────────────────────────────────────────
        meta_row = QHBoxLayout()
        val_lbl = QLabel(f"Value:  {self.entity.get('value', '')}")
        val_lbl.setTextFormat(Qt.TextFormat.PlainText)
        val_lbl.setStyleSheet("font-size: 12px; color: #90a4ae;")
        val_lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)

        tags = self.entity.get("tags", [])
        tags_lbl = QLabel("  ".join(f"#{t}" for t in tags[:12]))
        tags_lbl.setTextFormat(Qt.TextFormat.PlainText)
        tags_lbl.setStyleSheet("font-size: 10px; color: #1565c0;")
        tags_lbl.setWordWrap(True)

        meta_row.addWidget(val_lbl)
        meta_row.addStretch()
        lay.addLayout(meta_row)
        lay.addWidget(tags_lbl)

        # ── Notes / OSINT data ────────────────────────────────────────
        notes_lbl = QLabel("OSINT COLLECTED DATA")
        notes_lbl.setStyleSheet(
            "font-size: 9px; font-weight: 700; color: #90a4ae; letter-spacing: 2px;")
        lay.addWidget(notes_lbl)

        self.notes_view = QTextEdit()
        self.notes_view.setReadOnly(True)
        self.notes_view.setFont(QFont("Monospace", 10))
        self.notes_view.setStyleSheet("""
            QTextEdit {
                background-color: #060a12;
                color: #7ec8e3;
                border: 1px solid #1a2540;
                border-radius: 6px;
                padding: 10px;
                font-family: 'Courier New', monospace;
                font-size: 11px;
            }
        """)
        notes = self.entity.get("notes", "")
        self.notes_view.setPlainText(notes if notes else "No OSINT data collected yet.")
        lay.addWidget(self.notes_view, 1)

        # ── Buttons ───────────────────────────────────────────────────
        btns = QHBoxLayout()

        copy_btn = QPushButton("⧉  Copy Notes")
        copy_btn.setFixedHeight(32)
        copy_btn.clicked.connect(
            lambda: QApplication.clipboard().setText(self.notes_view.toPlainText()))

        edit_btn = QPushButton("✏️  Edit Entity")
        edit_btn.setFixedHeight(32)
        edit_btn.clicked.connect(lambda: (self.accept(), self.edit_requested.emit()))

        close_btn = QPushButton("Close")
        close_btn.setFixedHeight(32)
        close_btn.clicked.connect(self.accept)

        btns.addWidget(copy_btn)
        btns.addStretch()
        btns.addWidget(edit_btn)
        btns.addWidget(close_btn)
        lay.addLayout(btns)
