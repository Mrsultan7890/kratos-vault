from pathlib import Path
import html

from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QLabel, QFrame, QStackedWidget, QStatusBar,
    QDialog, QLineEdit, QMessageBox, QFileDialog, QApplication,
    QSizePolicy, QSpacerItem
)
from PyQt6.QtCore import Qt, pyqtSlot, QSize, QTimer
from PyQt6.QtGui import QAction, QFont, QColor, QPalette

from ui.theme import DARK_THEME, STATUS_COLORS, PRIORITY_COLORS, ENTITY_COLORS
from ui.cases_panel import CasesPanel
from ui.entities_panel import EntitiesPanel
from ui.graph_panel import GraphPanel
from ui.media_panel import MediaPanel
from ui.timeline_panel import TimelinePanel
from ui.notes_panel import NotesPanel
from ui.ml_panel import MLPanel
from ui.audit_panel import AuditPanel
from ui.activity_monitor import LiveActivityMonitor
from core import crypto as Crypto
from core.enrichment import EnrichmentAutoChecker, set_remote_lookups_enabled


NAV_ITEMS = [
    ("📁", "Cases",     0),
    ("🔵", "Entities",  1),
    ("🕸",  "Graph",     2),
    ("🖼",  "Media",     3),
    ("📝", "Notes",     4),
    ("⏱",  "Timeline",  5),
    ("🤖", "ML Intel",  6),
    ("🛡",  "Audit",     7),
]

NAV_BTN_STYLE = """
QPushButton {{
    text-align: left;
    padding: 10px 16px 10px 18px;
    border: none;
    border-left: 3px solid transparent;
    border-radius: 0;
    color: #90a4ae;
    font-size: 12px;
    font-weight: 600;
    background: transparent;
    letter-spacing: 0.3px;
}}
QPushButton:hover {{
    background-color: #0f1929;
    color: #b0bec5;
    border-left-color: #1a2540;
}}
QPushButton:checked {{
    background-color: #0d2b4e;
    color: #42a5f5;
    border-left-color: #1565c0;
    font-weight: 700;
}}
"""


class MainWindow(QMainWindow):
    def __init__(self, db):
        super().__init__()
        self.db = db
        self.active_case_id = None
        self.active_case = None
        self._enrichment_workers = {}
        self._remote_enrichment_enabled = False
        self._shutting_down = False
        self.setWindowTitle("Kratos Vault  —  OSINT Case Manager")
        self.setMinimumSize(1080, 680)
        self.setStyleSheet(DARK_THEME)
        self._build_ui()
        self._build_menu()
        self._update_status()
        self._start_auto_checker()

    def _start_auto_checker(self):
        # Connect monitor to entities panel
        self.entities_panel.set_monitor(self._monitor)

        self._auto_checker = EnrichmentAutoChecker(self.db, interval_ms=60_000)
        self._auto_checker.enqueue.connect(self._enqueue_enrichment)
        self._auto_checker.status_update.connect(
            lambda msg: self.status_bar.showMessage(f"  {msg}", 8000))
        self._auto_checker.start()

    @pyqtSlot(str, str)
    def _maybe_show_monitor(self, title: str, message: str):
        """Auto-show monitor panel when enrichment starts."""
        if "Enriching" in title:
            self.btn_monitor.setChecked(True)
            self._toggle_activity(True)

    @pyqtSlot(str)
    def _enqueue_enrichment(self, entity_id: str):
        if not self._remote_enrichment_enabled:
            return
        self.entities_panel._trigger_enrichment_by_id(entity_id)

    def closeEvent(self, event):
        self.shutdown_workers()
        try:
            b = self.db.backup(keep=5)
            self.status_bar.showMessage(f"  Backup saved: {b.name}", 4000)
        except Exception as e:
            QMessageBox.warning(self, "Backup Failed",
                                f"The encrypted backup could not be saved:\n{e}")
        super().closeEvent(event)

    def shutdown_workers(self):
        if self._shutting_down:
            return
        self._shutting_down = True
        self._remote_enrichment_enabled = False
        set_remote_lookups_enabled(False)
        if hasattr(self, "_auto_checker"):
            self._auto_checker.stop()
            self._auto_checker.wait()
        if hasattr(self, "entities_panel"):
            self.entities_panel.wait_for_workers()
        if hasattr(self, "media_panel"):
            self.media_panel.wait_for_workers()
        if hasattr(self, "ml_panel"):
            self.ml_panel.wait_for_workers()

    # ── UI Build ──────────────────────────────────────────────────────
    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QHBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        root.addWidget(self._build_sidebar())
        root.addWidget(self._build_content())
        self._monitor = LiveActivityMonitor()
        self._monitor.setVisible(False)
        root.addWidget(self._monitor)

        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_bar.showMessage("Ready")
        self._switch_panel(0)

    def _build_sidebar(self):
        sidebar = QFrame()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(200)
        lay = QVBoxLayout(sidebar)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        # Logo block
        logo = QFrame()
        logo.setStyleSheet("""
            QFrame {
                background: qlineargradient(x1:0,y1:0,x2:0,y2:1,
                    stop:0 #0d1321, stop:1 #0b0f1a);
                border-bottom: 1px solid #1a2540;
            }
        """)
        logo.setFixedHeight(68)
        ll = QVBoxLayout(logo)
        ll.setContentsMargins(18, 12, 18, 12)
        ll.setSpacing(3)
        t1 = QLabel("⬡  KRATOS VAULT")
        t1.setStyleSheet("""
            font-size: 12px;
            font-weight: 800;
            color: #42a5f5;
            letter-spacing: 1.2px;
        """)
        t2 = QLabel("OSINT Intelligence Platform")
        t2.setStyleSheet("font-size: 9px; color: #90a4ae; letter-spacing: 1px; font-weight: 600;")
        t2.setWordWrap(True)
        ll.addWidget(t1)
        ll.addWidget(t2)
        lay.addWidget(logo)

        # Section label
        sec = QLabel("  NAVIGATION")
        sec.setStyleSheet("""
            font-size: 9px;
            font-weight: 700;
            color: #90a4ae;
            letter-spacing: 2px;
            padding: 12px 0 4px 18px;
        """)
        lay.addWidget(sec)

        # Nav buttons
        self._nav_buttons = []
        for icon, label, idx in NAV_ITEMS:
            btn = QPushButton(f"  {icon}   {label}")
            btn.setCheckable(True)
            btn.setStyleSheet(NAV_BTN_STYLE)
            btn.setFixedHeight(42)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(lambda checked, i=idx: self._switch_panel(i))
            lay.addWidget(btn)
            self._nav_buttons.append(btn)

        lay.addStretch()

        # Divider
        div = QFrame()
        div.setFrameShape(QFrame.Shape.HLine)
        div.setStyleSheet("background: #1e2d3d; max-height: 1px; margin: 0;")
        lay.addWidget(div)

        # Active case info block
        self.case_block = QFrame()
        self.case_block.setStyleSheet("""
            QFrame {
                background-color: #0d1321;
                border-top: 1px solid #1a2540;
            }
        """)
        self.case_block.setFixedHeight(80)
        cb_lay = QVBoxLayout(self.case_block)
        cb_lay.setContentsMargins(20, 12, 20, 12)
        cb_lay.setSpacing(4)

        case_sec = QLabel("ACTIVE CASE")
        case_sec.setStyleSheet(
            "font-size: 9px; font-weight: 700; color: #90a4ae; letter-spacing: 2px;")
        self.case_name_label = QLabel("None")
        self.case_name_label.setTextFormat(Qt.TextFormat.PlainText)
        self.case_name_label.setStyleSheet(
            "font-size: 12px; font-weight: 700; color: #90a4ae;")
        self.case_name_label.setWordWrap(True)
        self.case_status_label = QLabel("")
        self.case_status_label.setStyleSheet("font-size: 11px; color: #90a4ae;")
        cb_lay.addWidget(case_sec)
        cb_lay.addWidget(self.case_name_label)
        cb_lay.addWidget(self.case_status_label)
        lay.addWidget(self.case_block)

        return sidebar

    def _build_content(self):
        content = QWidget()
        self._content_root = content
        lay = QVBoxLayout(content)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        lay.addWidget(self._build_topbar())
        lay.addWidget(self._build_stats_bar())
        self._notif_bar = self._build_notif_bar()
        lay.addWidget(self._notif_bar)

        self.stack = QStackedWidget()
        self.cases_panel    = CasesPanel(self.db)
        self.entities_panel = EntitiesPanel(self.db)
        self.graph_panel    = GraphPanel(self.db)
        self.media_panel    = MediaPanel(self.db)
        self.notes_panel    = NotesPanel(self.db)
        self.timeline_panel = TimelinePanel(self.db)
        self.ml_panel       = MLPanel(self.db)
        self.audit_panel    = AuditPanel(self.db)

        for panel in [self.cases_panel, self.entities_panel, self.graph_panel,
                      self.media_panel, self.notes_panel, self.timeline_panel,
                      self.ml_panel, self.audit_panel]:
            self.stack.addWidget(panel)

        self.cases_panel.case_opened.connect(self._open_case)
        self.entities_panel.data_changed.connect(self._update_stats)
        self.entities_panel.notify.connect(self._show_notification)
        self.entities_panel.notify.connect(self._maybe_show_monitor)
        self.graph_panel.enrich_requested.connect(self.entities_panel._trigger_enrichment_by_id)
        self.media_panel.data_changed.connect(self._update_stats)
        self.notes_panel.data_changed.connect(self._update_stats)
        self.timeline_panel.data_changed.connect(self._update_stats)
        self.ml_panel.data_changed.connect(self._update_stats)
        lay.addWidget(self.stack)
        return content

    def _build_notif_bar(self):
        bar = QFrame()
        bar.setObjectName("notif_bar")
        bar.setFixedHeight(0)  # hidden by default
        bar.setStyleSheet("""
            QFrame#notif_bar {
                background-color: #0d2b4e;
                border-bottom: 1px solid #1565c0;
            }
        """)
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(20, 0, 16, 0)
        lay.setSpacing(10)
        self._notif_icon  = QLabel("")
        self._notif_icon.setStyleSheet("font-size: 14px;")
        self._notif_label = QLabel("")
        self._notif_label.setTextFormat(Qt.TextFormat.PlainText)
        self._notif_label.setStyleSheet("font-size: 12px; color: #90caf9; font-weight: 600;")
        lay.addWidget(self._notif_icon)
        lay.addWidget(self._notif_label)
        lay.addStretch()
        self._notif_timer = QTimer(self)
        self._notif_timer.setSingleShot(True)
        self._notif_timer.timeout.connect(self._hide_notification)
        return bar

    def _build_topbar(self):
        bar = QFrame()
        bar.setStyleSheet("""
            QFrame {
                background-color: #0d1321;
                border-bottom: 1px solid #1a2540;
            }
        """)
        bar.setFixedHeight(48)
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(20, 0, 16, 0)
        lay.setSpacing(8)

        self.page_title = QLabel("Cases")
        self.page_title.setStyleSheet("""
            font-size: 14px;
            font-weight: 700;
            color: #90a4ae;
            letter-spacing: 0.5px;
        """)
        lay.addWidget(self.page_title)
        lay.addStretch()

        self.btn_export = QPushButton("📤  Export")
        self.btn_export.setObjectName("btn_success")
        self.btn_export.setFixedHeight(32)
        self.btn_export.clicked.connect(self._export_case)

        self.btn_import = QPushButton("📥  Import")
        self.btn_import.setFixedHeight(32)
        self.btn_import.clicked.connect(self._import_case)

        self.btn_new_case = QPushButton("＋  New Case")
        self.btn_new_case.setObjectName("btn_primary")
        self.btn_new_case.setFixedHeight(32)
        self.btn_new_case.clicked.connect(
            lambda: (self._switch_panel(0), self.cases_panel._new_case()))

        self.btn_monitor = QPushButton("⚡  Activity")
        self.btn_monitor.setFixedHeight(32)
        self.btn_monitor.setCheckable(True)
        self.btn_monitor.setToolTip("Toggle live enrichment activity monitor")
        self.btn_monitor.clicked.connect(self._toggle_activity)

        self.btn_remote = QPushButton("🌐  Remote Lookups: Off")
        self.btn_remote.setCheckable(True)
        self.btn_remote.setFixedHeight(32)
        self.btn_remote.setToolTip(
            "Off by default. When enabled, selected indicators are sent to external OSINT services.")
        self.btn_remote.toggled.connect(self._set_remote_enrichment)

        for btn in [self.btn_import, self.btn_export, self.btn_monitor,
                    self.btn_remote, self.btn_new_case]:
            lay.addWidget(btn)

        return bar

    def _build_stats_bar(self):
        bar = QFrame()
        bar.setObjectName("toolbar_frame")
        bar.setMinimumHeight(80)
        bar.setMaximumHeight(90)
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(20, 8, 20, 8)
        lay.setSpacing(10)

        self._stat_widgets = {}
        stat_defs = [
            ("entities", "Entities",    "#42a5f5"),
            ("edges",    "Connections", "#7986cb"),
            ("media",    "Media",       "#f06292"),
            ("events",   "Events",      "#ffb74d"),
            ("notes",    "Notes",       "#4db6ac"),
        ]
        for key, label, color in stat_defs:
            card = QFrame()
            card.setObjectName("stat_card")
            card.setMinimumHeight(64)
            card.setMinimumWidth(110)
            cl = QHBoxLayout(card)
            cl.setContentsMargins(12, 10, 12, 10)
            cl.setSpacing(10)

            # Color accent bar
            accent = QFrame()
            accent.setFixedWidth(3)
            accent.setMinimumHeight(40)
            accent.setStyleSheet(f"background-color: {color}; border-radius: 2px;")
            cl.addWidget(accent)

            text_col = QVBoxLayout()
            text_col.setSpacing(2)
            text_col.setContentsMargins(0, 0, 0, 0)
            val = QLabel("0")
            val.setStyleSheet(
                f"font-size: 20px; font-weight: 800; color: {color};"
                f" padding: 0; margin: 0;")
            val.setMinimumHeight(26)
            lbl = QLabel(label.upper())
            lbl.setStyleSheet(
                "font-size: 9px; font-weight: 700; color: #90a4ae;"
                " letter-spacing: 1.5px; padding: 0; margin: 0;")
            lbl.setMinimumHeight(14)
            text_col.addWidget(val)
            text_col.addWidget(lbl)
            cl.addLayout(text_col)

            lay.addWidget(card)
            self._stat_widgets[key] = val

        lay.addStretch()
        return bar

    # ── Menu ──────────────────────────────────────────────────────────
    def _build_menu(self):
        mb = self.menuBar()
        file_menu = mb.addMenu("File")
        acts = [
            ("New Case",     "Ctrl+N", lambda: (self._switch_panel(0), self.cases_panel._new_case())),
            ("Export Case",  "Ctrl+E", self._export_case),
            ("Import Case",  "Ctrl+I", self._import_case),
            (None, None, None),
            ("Export Report (HTML)", "Ctrl+R", lambda: self._export_report("html")),
            ("Export Report (PDF)",  "Ctrl+Shift+R", lambda: self._export_report("pdf")),
            (None, None, None),
            ("Backup All Cases (Encrypted)", None, self._export_full_vault),
            ("Global Search", "Ctrl+Shift+F", self._global_search),
            (None, None, None),
            ("Quit",         "Ctrl+Q", self.close),
        ]
        for name, shortcut, slot in acts:
            if name is None:
                file_menu.addSeparator()
            else:
                a = QAction(name, self)
                if shortcut:
                    a.setShortcut(shortcut)
                a.triggered.connect(slot)
                file_menu.addAction(a)

        view_menu = mb.addMenu("View")
        for icon, label, idx in NAV_ITEMS:
            a = QAction(f"{icon}  {label}", self)
            a.triggered.connect(lambda checked, i=idx: self._switch_panel(i))
            view_menu.addAction(a)

        help_menu = mb.addMenu("Help")
        a = QAction("About Kratos Vault", self)
        a.triggered.connect(self._show_about)
        help_menu.addAction(a)

    # ── Panel switching ───────────────────────────────────────────────
    def _switch_panel(self, idx):
        self.stack.setCurrentIndex(idx)
        titles = ["Cases", "Entities", "Graph", "Media", "Notes", "Timeline", "ML Intel", "Audit"]
        if idx < len(titles):
            self.page_title.setText(titles[idx])
        for i, btn in enumerate(self._nav_buttons):
            btn.setChecked(i == idx)
        if idx == 2 and self.active_case_id:
            self.graph_panel.refresh()
        if idx == 6 and self.active_case_id:
            self.ml_panel.set_case(self.active_case_id)
        if idx == 7:
            self.audit_panel.refresh()

    # ── Case open ─────────────────────────────────────────────────────
    @pyqtSlot(str)
    def _open_case(self, case_id):
        self.active_case_id = case_id
        self.active_case = self.db.get_case(case_id)
        self.setWindowTitle(
            f"Kratos Vault — {self.active_case['name']}  ·  OSINT Case Manager")
        self.entities_panel.set_case(case_id)
        self.graph_panel.set_case(case_id)
        self.media_panel.set_case(case_id)
        self.notes_panel.set_case(case_id)
        self.timeline_panel.set_case(case_id)
        self.ml_panel.set_case(case_id)
        self.audit_panel.set_case(case_id)
        self._update_stats()
        self._update_case_info()
        self.status_bar.showMessage(f"  ●  Case: {self.active_case['name']}")
        self._switch_panel(1)

    def _update_stats(self):
        if not self.active_case_id:
            for w in self._stat_widgets.values():
                w.setText("0")
            return
        stats = self.db.case_stats(self.active_case_id)
        for key, widget in self._stat_widgets.items():
            widget.setText(str(stats.get(key, 0)))

    def _update_case_info(self):
        if self.active_case:
            name = self.active_case["name"]
            self.case_name_label.setText(name[:22] + "…" if len(name) > 22 else name)
            self.case_name_label.setStyleSheet(
                "font-size: 12px; font-weight: 700; color: #cdd6f4;")
            status = self.active_case["status"]
            priority = self.active_case["priority"]
            sc = STATUS_COLORS.get(status, "#4a5568")
            pc = PRIORITY_COLORS.get(priority, "#4a5568")
            self.case_status_label.setText(
                f'<span style="color:{sc}">● {html.escape(status)}</span>'
                f'  <span style="color:{pc}">▲ {html.escape(priority)}</span>')
            self.case_status_label.setTextFormat(Qt.TextFormat.RichText)
        else:
            self.case_name_label.setText("None")
            self.case_name_label.setStyleSheet(
                "font-size: 12px; font-weight: 700; color: #90a4ae;")
            self.case_status_label.setText("")

    @pyqtSlot(str, str)
    def _show_notification(self, title: str, message: str):
        icon = title.split()[0] if title else "ℹ️"
        text = title.split(" ", 1)[1] if " " in title else title
        self._notif_icon.setText(icon)
        self._notif_label.setText(f"{text}  {message}")
        self._notif_bar.setFixedHeight(34)
        self._notif_timer.start(6000)

    def _hide_notification(self):
        self._notif_bar.setFixedHeight(0)

    def _update_status(self):
        cases = self.db.list_cases()
        self.status_bar.showMessage(
            f"  Kratos Vault v2.1  |  {len(cases)} case(s) in encrypted vault  |  "
            f"Remote lookups {'enabled' if self._remote_enrichment_enabled else 'disabled'}")

    def _set_remote_enrichment(self, enabled: bool):
        if enabled:
            reply = QMessageBox.warning(
                self, "Enable Remote OSINT Lookups",
                "Enrichment can send entity values (such as emails, phone numbers, "
                "IP addresses, URLs, hashes, and usernames) to third-party services. "
                "DNS lookups may also use your configured system resolver. Review the "
                "service behavior and your authority to investigate before proceeding.\n\n"
                "This permission lasts only until the application closes.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No)
            if reply != QMessageBox.StandardButton.Yes:
                self.btn_remote.blockSignals(True)
                self.btn_remote.setChecked(False)
                self.btn_remote.blockSignals(False)
                return
        self._remote_enrichment_enabled = enabled
        set_remote_lookups_enabled(enabled)
        self.entities_panel.set_remote_enrichment_enabled(enabled)
        self.btn_remote.setText(f"🌐  Lookups {'On' if enabled else 'Off'}")
        self._update_topbar_layout()
        self.status_bar.showMessage(
            f"  Remote OSINT lookups {'enabled for this session' if enabled else 'disabled'}")
        if enabled and hasattr(self, "_auto_checker"):
            self._auto_checker.scan_now()

    def _toggle_activity(self, visible: bool):
        self._monitor.setVisible(visible)
        QTimer.singleShot(0, self._update_topbar_layout)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        QTimer.singleShot(0, self._update_topbar_layout)

    def _update_topbar_layout(self):
        if not hasattr(self, "_content_root") or not hasattr(self, "_monitor"):
            return
        compact = self._content_root.width() < 850
        for button in (self.btn_import, self.btn_export, self.btn_new_case):
            button.setVisible(not compact)
        self.btn_monitor.setText("⚡" if compact else "⚡  Activity")
        self.btn_remote.setText(
            "🌐" if compact else
            f"🌐  Remote Lookups: {'On' if self._remote_enrichment_enabled else 'Off'}")
        for button in (self.btn_monitor, self.btn_remote):
            if compact:
                button.setFixedWidth(42)
            else:
                button.setMinimumWidth(0)
                button.setMaximumWidth(16777215)

    # ── Export / Import ───────────────────────────────────────────────
    def _export_case(self):
        if not self.active_case_id:
            QMessageBox.warning(self, "No Case", "Open a case first.")
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Export Case",
            f"{self.active_case['name'].replace(' ', '_')}.kv",
            "Kratos Vault (*.kv)")
        if not path:
            return
        dlg = PasswordDialog("Set export password:", parent=self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        password = dlg.password()
        if len(password) < 12:
            QMessageBox.warning(self, "Error", "Use an export password of at least 12 characters.")
            return
        try:
            data = self.db.export_case(self.active_case_id)
            encrypted = Crypto.encrypt(data, password)
            with open(path, "wb") as f:
                f.write(encrypted)
            self.db.add_event(self.active_case_id, "export", f"Case exported: {path}")
            QMessageBox.information(self, "Export", f"Case exported successfully.\n{path}")
        except Exception as e:
            QMessageBox.critical(self, "Export Failed", str(e))

    def _import_case(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Import Case", "",
            "Kratos Vault (*.kv *.kvv);;All Files (*)")
        if not path:
            return
        dlg = PasswordDialog("Enter decryption password:", parent=self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        password = dlg.password()
        try:
            if Path(path).stat().st_size > Crypto.MAX_ENCRYPTED_FILE_BYTES:
                raise ValueError("Selected export exceeds the 512 MiB import limit")
            with open(path, "rb") as f:
                raw = f.read()
            data = Crypto.decrypt(raw, password)
            if data.get("kind") == "full_vault":
                imported_ids = self.db.import_cases(data.get("cases"))
                self.cases_panel.refresh()
                QMessageBox.information(
                    self, "Import",
                    f"Full-vault backup restored ({len(imported_ids)} case(s)).")
            else:
                case_id = self.db.import_case(data)
                self.cases_panel.refresh()
                QMessageBox.information(self, "Import", "Case imported successfully.")
                self._open_case(case_id)
        except Exception as e:
            QMessageBox.critical(self, "Import Failed", str(e))

    # ── Report export ─────────────────────────────────────────────────
    def _export_report(self, fmt: str = "html"):
        if not self.active_case_id:
            QMessageBox.warning(self, "No Case", "Open a case first.")
            return
        from core.report import save_html_report, save_pdf_report
        base = self.active_case["name"].replace(" ", "_")
        if fmt == "pdf":
            path, _ = QFileDialog.getSaveFileName(
                self, "Export PDF Report", f"report_{base}.pdf", "PDF (*.pdf)")
            if not path:
                return
            try:
                save_pdf_report(self.db, self.active_case_id, path)
                QMessageBox.information(self, "Report", f"PDF report saved:\n{path}")
            except Exception as e:
                QMessageBox.critical(self, "Report Failed", str(e))
        else:
            path, _ = QFileDialog.getSaveFileName(
                self, "Export HTML Report", f"report_{base}.html", "HTML (*.html)")
            if not path:
                return
            try:
                save_html_report(self.db, self.active_case_id, path)
                self.db._audit(self.active_case_id, "report_exported",
                               target=path, details="html")
                QMessageBox.information(self, "Report", f"HTML report saved:\n{path}")
            except Exception as e:
                QMessageBox.critical(self, "Report Failed", str(e))

    # ── Global search ─────────────────────────────────────────────────
    def _global_search(self):
        from ui.search_dialog import GlobalSearchDialog
        dlg = GlobalSearchDialog(self.db, self, parent=self)
        dlg.case_open_requested.connect(self._open_case)
        dlg.show()

    # ── Encrypted full-vault backup ───────────────────────────────────
    def _export_full_vault(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "Encrypted Full-Vault Backup",
            f"kratos_vault_backup_{__import__('datetime').date.today().isoformat()}.kvv",
            "Kratos Vault Backup (*.kvv)")
        if not path:
            return
        dlg = PasswordDialog("Set backup password:", parent=self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        password = dlg.password()
        if len(password) < 12:
            QMessageBox.warning(self, "Error", "Use a backup password of at least 12 characters.")
            return
        try:
            payload = self.db.export_all_cases()
            encrypted = Crypto.encrypt(payload, password)
            with open(path, "wb") as f:
                f.write(encrypted)
            QMessageBox.information(
                self, "Backup",
                f"Full vault encrypted and saved ({len(payload['cases'])} case(s)):\n{path}")
        except Exception as e:
            QMessageBox.critical(self, "Backup Failed", str(e))

    def _show_about(self):
        QMessageBox.about(self, "About Kratos Vault",
            "<b style='color:#00b4d8;font-size:16px;'>Kratos Vault v2.1</b><br><br>"
            "<b>OSINT Case Management System</b><br><br>"
            "• SQLCipher-encrypted local vault + AES-256-GCM exports<br>"
            "• Remote OSINT lookups are off until explicitly enabled<br>"
            "• SQLite-compatible local database with cascade delete<br>"
            "• NetworkX graph analysis + 6 layout algorithms<br>"
            "• EXIF/GPS metadata extraction<br>"
            "• IOC auto-extraction (Email, IP, URL, Hash, Crypto)<br>"
            "• spaCy NER entity extraction<br>"
            "• MiniLM-L6-v2 semantic deduplication<br>"
            "• XGBoost risk scoring<br>"
            "• YOLOv8n image object detection<br>"
            "• NetworkX link prediction<br><br>"
            "<span style='color:#4a5568;'>External lookups send selected indicators to third-party services.</span>")


# ── Password Dialog ────────────────────────────────────────────────────
class PasswordDialog(QDialog):
    def __init__(self, prompt="Password:", parent=None):
        super().__init__(parent)
        self.setWindowTitle("Authentication")
        self.setMinimumWidth(360)
        self.setStyleSheet("""
            QDialog {
                background-color: #0d1117;
                border: 1px solid #1e2d3d;
                border-radius: 10px;
            }
        """)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 24, 24, 24)
        lay.setSpacing(16)

        title = QLabel("🔐  " + prompt)
        title.setStyleSheet("font-size: 14px; font-weight: 700; color: #cdd6f4;")
        lay.addWidget(title)

        self._edit = QLineEdit()
        self._edit.setEchoMode(QLineEdit.EchoMode.Password)
        self._edit.setPlaceholderText("Enter password...")
        self._edit.setFixedHeight(40)
        lay.addWidget(self._edit)

        btns = QHBoxLayout()
        btns.setSpacing(8)
        cancel = QPushButton("Cancel")
        cancel.setFixedHeight(36)
        cancel.clicked.connect(self.reject)
        ok = QPushButton("Confirm")
        ok.setObjectName("btn_primary")
        ok.setFixedHeight(36)
        ok.clicked.connect(self.accept)
        self._edit.returnPressed.connect(self.accept)
        btns.addWidget(cancel)
        btns.addWidget(ok)
        lay.addLayout(btns)

    def password(self):
        return self._edit.text()


class VaultPasswordDialog(QDialog):
    def __init__(self, existing: bool, plaintext_migration: bool = False, parent=None):
        super().__init__(parent)
        self.existing = existing
        self.setWindowTitle("Unlock Vault" if existing else "Protect Local Vault")
        self.setMinimumWidth(420)
        lay = QVBoxLayout(self)
        lay.setSpacing(12)
        title = QLabel(
            "Unlock your encrypted local vault" if existing else
            "Set a password for your local vault")
        title.setObjectName("section_title")
        lay.addWidget(title)
        if plaintext_migration:
            notice = "An existing unencrypted vault was found. It will be encrypted before opening."
        elif existing:
            notice = "The vault is encrypted at rest. A lost password cannot be recovered."
        else:
            notice = "Choose 12+ characters. Your password is not stored and cannot be recovered."
        description = QLabel(notice)
        description.setWordWrap(True)
        lay.addWidget(description)
        self.password_edit = QLineEdit()
        self.password_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.password_edit.setPlaceholderText("Vault password")
        lay.addWidget(self.password_edit)
        self.confirm_edit = None
        if not existing:
            self.confirm_edit = QLineEdit()
            self.confirm_edit.setEchoMode(QLineEdit.EchoMode.Password)
            self.confirm_edit.setPlaceholderText("Confirm vault password")
            lay.addWidget(self.confirm_edit)
        buttons = QHBoxLayout()
        buttons.addStretch()
        cancel = QPushButton("Quit")
        cancel.clicked.connect(self.reject)
        self.accept_button = QPushButton("Unlock" if existing else "Create Encrypted Vault")
        self.accept_button.setObjectName("btn_primary")
        self.accept_button.clicked.connect(self._accept_if_valid)
        self.password_edit.returnPressed.connect(self._accept_if_valid)
        buttons.addWidget(cancel)
        buttons.addWidget(self.accept_button)
        lay.addLayout(buttons)
        self.password_edit.setFocus()

    def _accept_if_valid(self):
        password = self.password_edit.text()
        if not password:
            QMessageBox.warning(self, "Vault Password", "A password is required.")
            return
        if not self.existing:
            if len(password) < 12:
                QMessageBox.warning(
                    self, "Vault Password", "Use at least 12 characters for the vault password.")
                return
            if self.confirm_edit.text() != password:
                QMessageBox.warning(self, "Vault Password", "The passwords do not match.")
                return
        self.accept()

    def password(self):
        return self.password_edit.text()
