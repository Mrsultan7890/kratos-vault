import html

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QTableWidget, QTableWidgetItem, QHeaderView, QMessageBox,
    QAbstractItemView, QFileDialog, QDialog, QTextEdit,
    QScrollArea, QGridLayout, QFrame, QSizePolicy, QApplication
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QSize
from PyQt6.QtGui import QPixmap, QImage, QColor
from core.crypto import hash_bytes
from core.exif_parser import extract_exif
import os


class MediaUploadWorker(QThread):
    progress = pyqtSignal(str)
    done = pyqtSignal(int, int)  # imported, skipped

    def __init__(self, db, case_id, paths):
        super().__init__()
        self.db = db
        self.case_id = case_id
        self.paths = paths

    def run(self):
        imported = skipped = 0
        for path in self.paths:
            if self.isInterruptionRequested():
                break
            try:
                with open(path, "rb") as f:
                    data = f.read()
                sha256 = hash_bytes(data)
                exif = extract_exif(data)
                name = os.path.basename(path)
                mime = self._mime(path)
                result = self.db.create_media(
                    self.case_id, name, mime, len(data), sha256, data, exif)
                if result is None:
                    skipped += 1
                    self.progress.emit(f"Skipped duplicate: {name}")
                else:
                    imported += 1
                    self.progress.emit(f"Imported: {name}")
            except Exception as ex:
                self.progress.emit(f"Error: {path} — {ex}")
                skipped += 1
        self.done.emit(imported, skipped)

    def _mime(self, path):
        ext = os.path.splitext(path)[1].lower()
        return {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png",
                ".gif": "image/gif", ".bmp": "image/bmp", ".webp": "image/webp",
                ".tiff": "image/tiff", ".tif": "image/tiff"}.get(ext, "application/octet-stream")


class MediaPanel(QWidget):
    data_changed = pyqtSignal()
    def __init__(self, db, parent=None):
        super().__init__(parent)
        self.db = db
        self.case_id = None
        self._workers = set()
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        # Toolbar
        tb = QHBoxLayout()
        title = QLabel("Media & Metadata")
        title.setObjectName("section_title")
        tb.addWidget(title)
        tb.addStretch()

        self.btn_upload = QPushButton("+ Upload Files")
        self.btn_upload.setObjectName("btn_primary")
        self.btn_upload.clicked.connect(self._upload)

        self.btn_view = QPushButton("View EXIF")
        self.btn_view.clicked.connect(self._view_exif)

        self.btn_delete = QPushButton("Delete")
        self.btn_delete.setObjectName("btn_danger")
        self.btn_delete.clicked.connect(self._delete_selected)

        self.btn_copy_hash = QPushButton("Copy Hash")
        self.btn_copy_hash.clicked.connect(self._copy_hash)

        self.btn_analyze = QPushButton("🤖 Analyze")
        self.btn_analyze.setObjectName("btn_warning")
        self.btn_analyze.setToolTip("Run YOLOv8n object detection + face detection")
        self.btn_analyze.clicked.connect(self._analyze_image)

        for btn in [self.btn_upload, self.btn_view, self.btn_analyze, self.btn_copy_hash, self.btn_delete]:
            tb.addWidget(btn)
        layout.addLayout(tb)

        # Table
        self.table = QTableWidget()
        self.table.setColumnCount(7)
        self.table.setHorizontalHeaderLabels(
            ["Thumbnail", "Filename", "Size", "SHA-256", "GPS", "Date Taken", "Added"])
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.setRowHeight(0, 64)
        self.table.verticalHeader().setDefaultSectionSize(64)
        self.table.doubleClicked.connect(self._view_exif)
        layout.addWidget(self.table)

        self.status_label = QLabel("0 files")
        self.status_label.setStyleSheet("color: #90a4ae; font-size: 12px;")
        layout.addWidget(self.status_label)

    def set_case(self, case_id):
        self.case_id = case_id
        self.refresh()

    def refresh(self):
        if not self.case_id:
            self.table.setRowCount(0)
            return
        media_list = self.db.list_media(self.case_id)
        self.table.setRowCount(len(media_list))
        self._media = media_list
        for row, m in enumerate(media_list):
            # Thumbnail — only decode image mimes; others get an icon
            thumb_label = QLabel()
            thumb_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            pix = self._load_thumbnail(m["id"], m.get("mime_type", ""))
            if pix is not None:
                thumb_label.setPixmap(pix)
            else:
                thumb_label.setText("📄")
            self.table.setCellWidget(row, 0, thumb_label)

            exif = m.get("exif", {})
            gps = ""
            if "gps_latitude" in exif and "gps_longitude" in exif:
                gps = f"{exif['gps_latitude']:.5f}, {exif['gps_longitude']:.5f}"

            date_taken = (exif.get("DateTimeOriginal") or
                          exif.get("dateTimeOriginal") or
                          exif.get("DateTime") or "")

            size_str = self._fmt_size(m["size"])
            hash_short = m["hash_sha256"][:32] + "..."

            items = [
                None,  # thumbnail widget
                QTableWidgetItem(m["name"]),
                QTableWidgetItem(size_str),
                QTableWidgetItem(hash_short),
                QTableWidgetItem(gps),
                QTableWidgetItem(str(date_taken)[:19]),
                QTableWidgetItem(m["created"][:10]),
            ]
            items[1].setData(Qt.ItemDataRole.UserRole, m["id"])
            items[1].setToolTip(f"{m['name']}\n{m.get('mime_type', '')}")
            items[3].setToolTip(m["hash_sha256"])
            if gps:
                items[4].setForeground(QColor("#2ea043"))

            for col, item in enumerate(items):
                if item is not None:
                    item.setTextAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
                    self.table.setItem(row, col, item)

        self.status_label.setText(f"{len(media_list)} files")

    def _load_thumbnail(self, media_id, mime_type=""):
        """Decode only image rows into thumbnails; non-images get an icon.
        (QImageReader-by-device segfaults in this PyQt6 build — use QPixmap.)"""
        if mime_type and not mime_type.startswith("image/"):
            return None
        raw = self.db.get_media_data(media_id)
        if not raw:
            return None
        pix = QPixmap()
        if not pix.loadFromData(raw):
            return None
        return pix.scaled(80, 60, Qt.AspectRatioMode.KeepAspectRatio,
                          Qt.TransformationMode.SmoothTransformation)

    def _selected_id(self):
        row = self.table.currentRow()
        if row < 0:
            return None
        item = self.table.item(row, 1)
        return item.data(Qt.ItemDataRole.UserRole) if item else None

    def _upload(self):
        if not self.case_id:
            QMessageBox.warning(self, "No Case", "Open a case first.")
            return
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Select Media Files", "",
            "Images (*.jpg *.jpeg *.png *.gif *.bmp *.webp *.tiff *.tif);;All Files (*)")
        if not paths:
            return
        self.btn_upload.setEnabled(False)
        self.btn_upload.setText("Uploading...")
        self._worker = MediaUploadWorker(self.db, self.case_id, paths)
        self._worker.progress.connect(self.status_label.setText)
        self._worker.done.connect(self._upload_done)
        self._worker.finished.connect(lambda w=self._worker: self._workers.discard(w))
        self._workers.add(self._worker)
        self._worker.start()

    def wait_for_workers(self):
        for worker in tuple(self._workers):
            worker.requestInterruption()
            worker.wait()

    def _upload_done(self, imported, skipped):
        self.btn_upload.setEnabled(True)
        self.btn_upload.setText("+ Upload Files")
        self.refresh()
        self.data_changed.emit()
        msg = f"Imported {imported} file(s)."
        if skipped:
            msg += f" Skipped {skipped} duplicate(s)."
        self.status_label.setText(msg)

    def _view_exif(self):
        mid = self._selected_id()
        if not mid:
            return
        media = next((m for m in self._media if m["id"] == mid), None)
        if not media:
            return
        dlg = ExifDialog(media, db=self.db, parent=self)
        dlg.exec()

    def _delete_selected(self):
        mid = self._selected_id()
        if not mid:
            return
        reply = QMessageBox.question(self, "Delete", "Delete this media file?",
                                     QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if reply == QMessageBox.StandardButton.Yes:
            self.db.delete_media(mid)
            self.refresh()
            self.data_changed.emit()

    def _copy_hash(self):
        mid = self._selected_id()
        if not mid:
            return
        media = next((m for m in self._media if m["id"] == mid), None)
        if media:
            QApplication.clipboard().setText(media["hash_sha256"])

    def _analyze_image(self):
        mid = self._selected_id()
        if not mid:
            QMessageBox.information(self, "Select", "Select a media file first.")
            return
        raw = self.db.get_media_data(mid)
        if not raw:
            return
        self.btn_analyze.setEnabled(False)
        self.btn_analyze.setText("Analyzing...")
        self._analyzing_bytes = raw
        from PyQt6.QtCore import QThread, pyqtSignal

        class AnalyzeWorker(QThread):
            done = pyqtSignal(dict)
            err  = pyqtSignal(str)
            def __init__(self, data):
                super().__init__()
                self._data = data
            def run(self):
                try:
                    from core.ml.image_analyzer import analyze_image
                    self.done.emit(analyze_image(self._data))
                except Exception as e:
                    self.err.emit(str(e))

        self._analyze_worker = AnalyzeWorker(raw)
        self._analyze_worker.done.connect(self._show_analysis)
        self._analyze_worker.err.connect(lambda e: (
            QMessageBox.critical(self, "Error", e),
            self.btn_analyze.setEnabled(True),
            self.btn_analyze.setText("🤖 Analyze")))
        self._analyze_worker.finished.connect(lambda: (
            self.btn_analyze.setEnabled(True),
            self.btn_analyze.setText("🤖 Analyze")))
        self._analyze_worker.start()

    def _show_analysis(self, result):
        from PyQt6.QtWidgets import QDialog, QVBoxLayout, QTextEdit, QPushButton, QScrollArea
        dlg = QDialog(self)
        dlg.setWindowTitle("Image Analysis — YOLOv8n + Face Detection")
        dlg.setMinimumSize(640, 560)
        lay = QVBoxLayout(dlg)

        # Annotated image (YOLO boxes + face boxes)
        raw = getattr(self, "_analyzing_bytes", None)
        if raw and not result.get("model_missing"):
            try:
                from core.ml.image_analyzer import draw_detections
                annotated = draw_detections(raw, result.get("objects", []),
                                            result.get("face_boxes", []))
                img_widget = QLabel()
                img_widget.setAlignment(Qt.AlignmentFlag.AlignCenter)
                pix = QPixmap()
                pix.loadFromData(annotated)
                img_widget.setPixmap(pix)
                scroll = QScrollArea()
                scroll.setWidgetResizable(True)
                scroll.setWidget(img_widget)
                lay.addWidget(scroll, 1)
            except Exception:
                pass

        txt = QTextEdit()
        txt.setReadOnly(True)
        txt.setMaximumHeight(180)
        lines = []
        lines.append(f"Summary:  {result['summary']}")
        lines.append(f"Faces:    {result.get('face_count', 0)}")
        if result["risk_flags"]:
            lines.append("\nRisk Flags:")
            for f in result["risk_flags"]:
                lines.append(f"  {f}")
        if result["objects"]:
            lines.append(f"\nDetected Objects ({len(result['objects'])}):")
            for obj in result["objects"]:
                lines.append(f"  {obj['label']:<20} conf: {obj['confidence']:.0%}")
        txt.setPlainText("\n".join(lines))
        lay.addWidget(txt)
        close = QPushButton("Close")
        close.clicked.connect(dlg.accept)
        lay.addWidget(close)
        dlg.exec()

    def _fmt_size(self, size):
        for unit in ["B", "KB", "MB", "GB"]:
            if size < 1024:
                return f"{size:.1f} {unit}"
            size /= 1024
        return f"{size:.1f} TB"


class ExifDialog(QDialog):
    def __init__(self, media, db, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"EXIF — {media['name']}")
        self.setMinimumSize(560, 580)
        self.setStyleSheet("""
            QDialog { background-color: #0d1321; }
            QLabel  { color: #90a4ae; }
        """)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)

        # ── Thumbnail ──────────────────────────────────────────────
        raw = db.get_media_data(media["id"]) if db else None
        if raw:
            pix = QPixmap()
            pix.loadFromData(raw)
            if not pix.isNull():
                thumb = QLabel()
                thumb.setAlignment(Qt.AlignmentFlag.AlignCenter)
                thumb.setStyleSheet(
                    "background:#0b0f1a; border:1px solid #1a2540;"
                    "border-radius:6px; padding:4px;")
                thumb.setPixmap(pix.scaled(
                    520, 220,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation))
                layout.addWidget(thumb)

        # ── File info ──────────────────────────────────────────────
        info_frame = QFrame()
        info_frame.setStyleSheet(
            "background:#0b0f1a; border:1px solid #1a2540;"
            "border-radius:6px; padding:8px;")
        info_lay = QVBoxLayout(info_frame)
        info_lay.setContentsMargins(10, 8, 10, 8)
        info_lay.setSpacing(4)

        name_lbl = QLabel(f"<b style='color:#64b5f6;'>{html.escape(media['name'])}</b>")
        name_lbl.setTextFormat(Qt.TextFormat.RichText)
        size_lbl = QLabel(
            f"Size: {self._fmt(media['size'])}  |  "
            f"Type: {media.get('mime_type','unknown')}")
        size_lbl.setStyleSheet("color:#546e7a; font-size:11px;")
        hash_lbl = QLabel(f"SHA-256: {media['hash_sha256']}")
        hash_lbl.setStyleSheet(
            "color:#90a4ae; font-size:10px; font-family:monospace;")
        hash_lbl.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse)
        hash_lbl.setWordWrap(True)
        for w in [name_lbl, size_lbl, hash_lbl]:
            info_lay.addWidget(w)
        layout.addWidget(info_frame)

        # ── EXIF / GPS ─────────────────────────────────────────────
        exif = media.get("exif", {})
        text = QTextEdit()
        text.setReadOnly(True)
        text.setStyleSheet(
            "background:#0b0f1a; border:1px solid #1a2540;"
            "border-radius:6px; color:#78909c;"
            "font-family:'Courier New',monospace; font-size:11px;")

        lines = []

        # GPS block first
        if "gps_latitude" in exif:
            lines.append("━━━  GPS LOCATION  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
            lines.append(f"  Latitude   : {exif['gps_latitude']}")
            lines.append(f"  Longitude  : {exif['gps_longitude']}")
            if "gps_maps_url" in exif:
                lines.append(f"  Maps URL   : {exif['gps_maps_url']}")
            lines.append("")

        # Priority keys
        priority = [
            ("DateTimeOriginal", "Date Taken"),
            ("DateTime",         "Date Modified"),
            ("Make",             "Camera Make"),
            ("Model",            "Camera Model"),
            ("Software",         "Software"),
            ("ExifImageWidth",   "Width"),
            ("ExifImageLength",  "Height"),
            ("FocalLength",      "Focal Length"),
            ("ISOSpeedRatings",  "ISO"),
            ("ExposureTime",     "Exposure"),
            ("FNumber",          "F-Number"),
            ("Flash",            "Flash"),
            ("GPSAltitude",      "Altitude"),
        ]
        found_priority = [(lbl, exif[k]) for k, lbl in priority if k in exif]
        if found_priority:
            lines.append("━━━  CAMERA INFO  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
            for lbl, val in found_priority:
                lines.append(f"  {lbl:<18}: {val}")
            lines.append("")

        # All remaining tags
        skip_keys = {k for k, _ in priority} | {"gps_latitude","gps_longitude","gps_maps_url"}
        remaining = {k: v for k, v in sorted(exif.items()) if k not in skip_keys}
        if remaining:
            lines.append("━━━  ALL EXIF TAGS  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
            for k, v in remaining.items():
                lines.append(f"  {k:<28}: {str(v)[:80]}")

        if not lines:
            lines = ["  No EXIF metadata found in this file."]

        text.setPlainText("\n".join(lines))
        layout.addWidget(text)

        # ── Buttons ────────────────────────────────────────────────
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        if "gps_maps_url" in exif:
            copy_gps = QPushButton("📋 Copy GPS")
            copy_gps.clicked.connect(
                lambda: QApplication.clipboard().setText(
                    f"{exif['gps_latitude']},{exif['gps_longitude']}"))
            btn_row.addWidget(copy_gps)
        copy_hash = QPushButton("📋 Copy Hash")
        copy_hash.clicked.connect(
            lambda: QApplication.clipboard().setText(media["hash_sha256"]))
        close_btn = QPushButton("Close")
        close_btn.setObjectName("btn_primary")
        close_btn.clicked.connect(self.accept)
        btn_row.addWidget(copy_hash)
        btn_row.addWidget(close_btn)
        layout.addLayout(btn_row)

    def _fmt(self, size):
        for u in ["B","KB","MB","GB"]:
            if size < 1024: return f"{size:.1f} {u}"
            size /= 1024
        return f"{size:.1f} TB"
