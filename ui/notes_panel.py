from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QListWidget, QListWidgetItem, QTextEdit, QLineEdit,
    QDialog, QFormLayout, QMessageBox, QSplitter, QFrame
)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFont


class NotesPanel(QWidget):
    data_changed = pyqtSignal()
    def __init__(self, db, parent=None):
        super().__init__(parent)
        self.db = db
        self.case_id = None
        self._current_note_id = None
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        title = QLabel("Investigation Notes")
        title.setObjectName("section_title")
        layout.addWidget(title)

        splitter = QSplitter(Qt.Orientation.Horizontal)

        # Left: note list
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(6)

        tb = QHBoxLayout()
        self.btn_new = QPushButton("+ New Note")
        self.btn_new.setObjectName("btn_primary")
        self.btn_new.clicked.connect(self._new_note)
        self.btn_delete = QPushButton("Delete")
        self.btn_delete.setObjectName("btn_danger")
        self.btn_delete.clicked.connect(self._delete_note)
        tb.addWidget(self.btn_new)
        tb.addWidget(self.btn_delete)
        left_layout.addLayout(tb)

        self.note_list = QListWidget()
        self.note_list.currentItemChanged.connect(self._load_note)
        left_layout.addWidget(self.note_list)
        splitter.addWidget(left)

        # Right: editor
        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(6)

        self.title_edit = QLineEdit()
        self.title_edit.setPlaceholderText("Note title...")
        self.title_edit.setStyleSheet("font-size: 15px; font-weight: bold;")

        self.tags_edit = QLineEdit()
        self.tags_edit.setPlaceholderText("Tags: tag1, tag2")

        self.content_edit = QTextEdit()
        self.content_edit.setPlaceholderText("Write your investigation notes here...")
        self.content_edit.setFont(QFont("Courier New", 11))

        self.btn_save = QPushButton("Save Note")
        self.btn_save.setObjectName("btn_success")
        self.btn_save.clicked.connect(self._save_note)

        right_layout.addWidget(self.title_edit)
        right_layout.addWidget(self.tags_edit)
        right_layout.addWidget(self.content_edit)
        right_layout.addWidget(self.btn_save)
        splitter.addWidget(right)

        splitter.setSizes([220, 580])
        layout.addWidget(splitter)

    def set_case(self, case_id):
        self.case_id = case_id
        self._current_note_id = None
        self.title_edit.clear()
        self.tags_edit.clear()
        self.content_edit.clear()
        self.refresh()

    def refresh(self):
        self.note_list.clear()
        if not self.case_id:
            return
        notes = self.db.list_notes(self.case_id)
        for n in notes:
            item = QListWidgetItem(n["title"])
            item.setData(Qt.ItemDataRole.UserRole, n["id"])
            self.note_list.addItem(item)

    def _load_note(self, item):
        if not item:
            return
        nid = item.data(Qt.ItemDataRole.UserRole)
        notes = self.db.list_notes(self.case_id)
        note = next((n for n in notes if n["id"] == nid), None)
        if note:
            self._current_note_id = nid
            self.title_edit.setText(note["title"])
            self.tags_edit.setText(", ".join(note["tags"]))
            self.content_edit.setPlainText(note["content"])

    def _new_note(self):
        if not self.case_id:
            QMessageBox.warning(self, "No Case", "Open a case first.")
            return
        self._current_note_id = None
        self.title_edit.setText("New Note")
        self.tags_edit.clear()
        self.content_edit.clear()
        self.title_edit.setFocus()
        self.title_edit.selectAll()

    def _save_note(self):
        if not self.case_id:
            return
        title = self.title_edit.text().strip()
        if not title:
            QMessageBox.warning(self, "Validation", "Title is required.")
            return
        tags = [t.strip() for t in self.tags_edit.text().split(",") if t.strip()]
        content = self.content_edit.toPlainText()
        if self._current_note_id:
            self.db.update_note(self._current_note_id, title=title, content=content, tags=tags)
        else:
            note = self.db.create_note(self.case_id, title, content, tags)
            self._current_note_id = note["id"]
        self.refresh()
        self.data_changed.emit()

    def _delete_note(self):
        if not self._current_note_id:
            return
        reply = QMessageBox.question(self, "Delete", "Delete this note?",
                                     QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if reply == QMessageBox.StandardButton.Yes:
            self.db.delete_note(self._current_note_id)
            self._current_note_id = None
            self.title_edit.clear()
            self.tags_edit.clear()
            self.content_edit.clear()
            self.refresh()
            self.data_changed.emit()
