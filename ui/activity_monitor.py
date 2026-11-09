from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QScrollArea, QFrame, QSizePolicy
)
from PyQt6.QtCore import Qt, pyqtSlot, QTimer, QDateTime
from PyQt6.QtGui import QColor, QFont


class ActivityCard(QFrame):
    """One card per active enrichment job."""

    def __init__(self, entity_id: str, value: str, parent=None):
        super().__init__(parent)
        self.entity_id = entity_id
        self.value     = value
        self._start_ts = QDateTime.currentDateTime()
        self.setObjectName("activity_card")
        self.setStyleSheet("""
            QFrame#activity_card {
                background-color: #0d1321;
                border: 1px solid #1a2540;
                border-left: 3px solid #1565c0;
                border-radius: 6px;
                margin: 2px 0;
            }
        """)
        self._build()

    def _build(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 8, 10, 8)
        lay.setSpacing(4)

        # Row 1 — entity value + elapsed
        row1 = QHBoxLayout()
        self.lbl_value = QLabel(self.value[:48])
        self.lbl_value.setTextFormat(Qt.TextFormat.PlainText)
        self.lbl_value.setStyleSheet("font-size: 12px; font-weight: 700; color: #90caf9;")
        self.lbl_elapsed = QLabel("0s")
        self.lbl_elapsed.setStyleSheet("font-size: 11px; color: #90a4ae;")
        row1.addWidget(self.lbl_value)
        row1.addStretch()
        row1.addWidget(self.lbl_elapsed)
        lay.addLayout(row1)

        # Row 2 — current phase
        self.lbl_phase = QLabel("⏳  Starting...")
        self.lbl_phase.setTextFormat(Qt.TextFormat.PlainText)
        self.lbl_phase.setStyleSheet("font-size: 11px; color: #546e7a;")
        lay.addWidget(self.lbl_phase)

        # Row 3 — sub-step (which service/platform)
        self.lbl_step = QLabel("")
        self.lbl_step.setTextFormat(Qt.TextFormat.PlainText)
        self.lbl_step.setStyleSheet("font-size: 10px; color: #90a4ae; padding-left: 4px;")
        lay.addWidget(self.lbl_step)

        # Elapsed timer
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(1000)

    def set_phase(self, phase: str):
        self.lbl_phase.setText(f"⚙️  {phase}")

    def set_step(self, step: str):
        self.lbl_step.setText(f"  ↳  {step}")

    def set_done(self, platforms_found: list):
        self._timer.stop()
        self.setStyleSheet("""
            QFrame#activity_card {
                background-color: #0a1a0f;
                border: 1px solid #1b5e20;
                border-left: 3px solid #4caf50;
                border-radius: 6px;
                margin: 2px 0;
            }
        """)
        found_str = ", ".join(platforms_found) if platforms_found else "no results"
        self.lbl_phase.setText(f"✅  Done — {found_str}")
        self.lbl_phase.setStyleSheet("font-size: 11px; color: #a5d6a7;")
        self.lbl_step.setText("")

    def set_error(self, error: str):
        self._timer.stop()
        self.setStyleSheet("""
            QFrame#activity_card {
                background-color: #1a0a0a;
                border: 1px solid #4a1010;
                border-left: 3px solid #ef5350;
                border-radius: 6px;
                margin: 2px 0;
            }
        """)
        self.lbl_phase.setText(f"❌  {error[:60]}")
        self.lbl_phase.setStyleSheet("font-size: 11px; color: #ef9a9a;")
        self.lbl_step.setText("")

    def _tick(self):
        secs = self._start_ts.secsTo(QDateTime.currentDateTime())
        if secs < 60:
            self.lbl_elapsed.setText(f"{secs}s")
        else:
            self.lbl_elapsed.setText(f"{secs // 60}m {secs % 60}s")


class LiveActivityMonitor(QWidget):
    """
    Docked panel — shows real-time enrichment activity.
    Connect to EnrichmentWorker signals to update.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumWidth(300)
        self.setMaximumWidth(360)
        self._cards = {}   # entity_id -> ActivityCard
        self._build_ui()

        # Auto-clear finished cards after 30s
        self._cleanup_timer = QTimer(self)
        self._cleanup_timer.timeout.connect(self._cleanup_old)
        self._cleanup_timer.start(10_000)

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Header
        header = QFrame()
        header.setStyleSheet("""
            QFrame {
                background-color: #0d1321;
                border-bottom: 1px solid #1a2540;
            }
        """)
        header.setFixedHeight(42)
        hl = QHBoxLayout(header)
        hl.setContentsMargins(12, 0, 12, 0)

        title = QLabel("⚡  LIVE ACTIVITY")
        title.setStyleSheet(
            "font-size: 10px; font-weight: 800; color: #1565c0; letter-spacing: 2px;")

        self.lbl_count = QLabel("0 running")
        self.lbl_count.setStyleSheet("font-size: 10px; color: #90a4ae;")

        self.btn_clear = QPushButton("Clear")
        self.btn_clear.setFixedHeight(24)
        self.btn_clear.setFixedWidth(48)
        self.btn_clear.setStyleSheet("""
            QPushButton {
                background: transparent; border: 1px solid #1a2540;
                border-radius: 4px; color: #90a4ae; font-size: 10px;
            }
            QPushButton:hover { border-color: #263a5e; color: #546e7a; }
        """)
        self.btn_clear.clicked.connect(self._clear_finished)

        hl.addWidget(title)
        hl.addStretch()
        hl.addWidget(self.lbl_count)
        hl.addSpacing(8)
        hl.addWidget(self.btn_clear)
        root.addWidget(header)

        # Scroll area for cards
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setStyleSheet("""
            QScrollArea { border: none; background: transparent; }
            QWidget#scroll_content { background: transparent; }
        """)

        self._content = QWidget()
        self._content.setObjectName("scroll_content")
        self._content_lay = QVBoxLayout(self._content)
        self._content_lay.setContentsMargins(8, 8, 8, 8)
        self._content_lay.setSpacing(4)
        self._content_lay.addStretch()

        scroll.setWidget(self._content)
        root.addWidget(scroll)

        # Empty state label
        self._empty_lbl = QLabel("No active enrichments")
        self._empty_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty_lbl.setStyleSheet(
            "color: #90a4ae; font-size: 12px; padding: 20px;")
        self._content_lay.insertWidget(0, self._empty_lbl)

    # ── Public slots ──────────────────────────────────────────────────

    @pyqtSlot(str, str)
    def on_started(self, entity_id: str, value: str):
        if entity_id in self._cards:
            return
        card = ActivityCard(entity_id, value)
        self._cards[entity_id] = card
        # Insert before stretch
        idx = self._content_lay.count() - 1
        self._content_lay.insertWidget(idx, card)
        self._update_header()

    @pyqtSlot(str, str)
    def on_phase(self, entity_id: str, phase: str):
        if entity_id in self._cards:
            self._cards[entity_id].set_phase(phase)

    @pyqtSlot(str, str)
    def on_step(self, entity_id: str, step: str):
        if entity_id in self._cards:
            self._cards[entity_id].set_step(step)

    @pyqtSlot(str, dict)
    def on_finished(self, entity_id: str, result: dict):
        if entity_id not in self._cards:
            return
        platforms_found = [
            p for p, d in result.get("platforms", {}).items()
            if isinstance(d, dict) and d.get("found")
        ]
        self._cards[entity_id].set_done(platforms_found)
        self._cards[entity_id]._done_ts = QDateTime.currentDateTime()
        self._update_header()

    @pyqtSlot(str, str)
    def on_error(self, entity_id: str, error: str):
        if entity_id not in self._cards:
            return
        self._cards[entity_id].set_error(error)
        self._cards[entity_id]._done_ts = QDateTime.currentDateTime()
        self._update_header()

    # ── Internal ──────────────────────────────────────────────────────

    def _update_header(self):
        running = sum(
            1 for c in self._cards.values()
            if not hasattr(c, '_done_ts')
        )
        total = len(self._cards)
        if running:
            self.lbl_count.setText(f"{running} running")
            self.lbl_count.setStyleSheet("font-size: 10px; color: #42a5f5;")
        else:
            self.lbl_count.setText(f"{total} total")
            self.lbl_count.setStyleSheet("font-size: 10px; color: #90a4ae;")

        self._empty_lbl.setVisible(total == 0)

    def _clear_finished(self):
        to_remove = [
            eid for eid, c in self._cards.items()
            if hasattr(c, '_done_ts')
        ]
        for eid in to_remove:
            card = self._cards.pop(eid)
            self._content_lay.removeWidget(card)
            card.deleteLater()
        self._update_header()

    def _cleanup_old(self):
        """Auto-remove finished cards older than 30s."""
        now = QDateTime.currentDateTime()
        to_remove = [
            eid for eid, c in self._cards.items()
            if hasattr(c, '_done_ts') and c._done_ts.secsTo(now) > 30
        ]
        for eid in to_remove:
            card = self._cards.pop(eid)
            self._content_lay.removeWidget(card)
            card.deleteLater()
        self._update_header()
