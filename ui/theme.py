DARK_THEME = """
/* ── Base ─────────────────────────────────────────────────────────── */
QMainWindow, QWidget {
    background-color: #0b0f1a;
    color: #b0bec5;
    font-family: 'Inter', 'Segoe UI', 'Ubuntu', sans-serif;
    font-size: 13px;
}
QDialog {
    background-color: #111827;
    color: #b0bec5;
    font-family: 'Inter', 'Segoe UI', 'Ubuntu', sans-serif;
    font-size: 13px;
}

/* ── Menu Bar ─────────────────────────────────────────────────────── */
QMenuBar {
    background-color: #0d1321;
    border-bottom: 1px solid #1a2540;
    padding: 2px 8px;
    color: #546e7a;
    font-size: 12px;
    letter-spacing: 0.3px;
}
QMenuBar::item { padding: 5px 12px; border-radius: 4px; }
QMenuBar::item:selected { background-color: #1a2540; color: #90caf9; }
QMenu {
    background-color: #111827;
    border: 1px solid #1a2540;
    border-radius: 8px;
    padding: 6px 4px;
}
QMenu::item { padding: 7px 22px; border-radius: 4px; color: #90a4ae; }
QMenu::item:selected { background-color: #1565c0; color: #ffffff; }
QMenu::separator { height: 1px; background: #1a2540; margin: 4px 10px; }

/* ── Tab Widget ───────────────────────────────────────────────────── */
QTabWidget::pane {
    border: 1px solid #1a2540;
    border-top: 2px solid #1565c0;
    background-color: #0b0f1a;
    border-radius: 0 0 8px 8px;
}
QTabBar::tab {
    background-color: #0d1321;
    color: #90a4ae;
    padding: 9px 22px;
    border: 1px solid #1a2540;
    border-bottom: none;
    margin-right: 3px;
    border-radius: 6px 6px 0 0;
    font-size: 12px;
    font-weight: 600;
    letter-spacing: 0.4px;
    min-width: 80px;
}
QTabBar::tab:selected {
    background-color: #0b0f1a;
    color: #42a5f5;
    border-top: 2px solid #1565c0;
}
QTabBar::tab:hover:!selected {
    background-color: #111827;
    color: #607d8b;
}

/* ── Tables ───────────────────────────────────────────────────────── */
QTableWidget {
    background-color: #0b0f1a;
    alternate-background-color: #0d1321;
    gridline-color: #141e30;
    border: 1px solid #1a2540;
    border-radius: 8px;
    selection-background-color: #0d2b4e;
    selection-color: #90caf9;
    outline: none;
    show-decoration-selected: 1;
}
QTableWidget::item {
    padding: 8px 12px;
    border: none;
    color: #90a4ae;
}
QTableWidget::item:selected {
    background-color: #0d2b4e;
    color: #90caf9;
}
QTableWidget::item:hover {
    background-color: #111827;
}
QHeaderView {
    background-color: #0d1321;
}
QHeaderView::section {
    background-color: #0d1321;
    color: #90a4ae;
    padding: 9px 12px;
    border: none;
    border-bottom: 1px solid #1a2540;
    border-right: 1px solid #141e30;
    font-weight: 700;
    font-size: 10px;
    text-transform: uppercase;
    letter-spacing: 1.2px;
}
QHeaderView::section:last { border-right: none; }
QHeaderView::section:hover { color: #546e7a; }

/* ── Buttons ──────────────────────────────────────────────────────── */
QPushButton {
    background-color: #111827;
    color: #90a4ae;
    border: 1px solid #1a2540;
    border-radius: 7px;
    padding: 7px 18px;
    font-weight: 600;
    font-size: 12px;
    letter-spacing: 0.3px;
    outline: none;
}
QPushButton:hover {
    background-color: #1a2540;
    color: #90a4ae;
    border-color: #263a5e;
}
QPushButton:pressed {
    background-color: #0d1321;
    border-color: #1565c0;
    color: #42a5f5;
}
QPushButton:disabled {
    background-color: #0d1321;
    color: #1e2d3d;
    border-color: #141e30;
}
QPushButton#btn_primary {
    background: qlineargradient(x1:0,y1:0,x2:0,y2:1,
        stop:0 #1976d2, stop:1 #1565c0);
    border: 1px solid #1565c0;
    color: #ffffff;
    font-weight: 700;
}
QPushButton#btn_primary:hover {
    background: qlineargradient(x1:0,y1:0,x2:0,y2:1,
        stop:0 #42a5f5, stop:1 #1976d2);
    border-color: #42a5f5;
}
QPushButton#btn_primary:pressed {
    background-color: #0d47a1;
    border-color: #0d47a1;
}
QPushButton#btn_danger {
    background-color: #1a0a0a;
    border: 1px solid #4a1010;
    color: #ef9a9a;
    font-weight: 700;
}
QPushButton#btn_danger:hover {
    background-color: #4a1010;
    border-color: #ef5350;
    color: #ffffff;
}
QPushButton#btn_success {
    background-color: #0a1a0f;
    border: 1px solid #1b5e20;
    color: #a5d6a7;
    font-weight: 700;
}
QPushButton#btn_success:hover {
    background-color: #1b5e20;
    border-color: #66bb6a;
    color: #ffffff;
}
QPushButton#btn_warning {
    background-color: #1a1200;
    border: 1px solid #4a3000;
    color: #ffe082;
    font-weight: 700;
}
QPushButton#btn_warning:hover {
    background-color: #4a3000;
    border-color: #ffb300;
    color: #ffffff;
}

/* ── Inputs ───────────────────────────────────────────────────────── */
QLineEdit, QTextEdit, QPlainTextEdit, QSpinBox {
    background-color: #0d1321;
    color: #90a4ae;
    border: 1px solid #1a2540;
    border-radius: 7px;
    padding: 8px 12px;
    selection-background-color: #1565c0;
    selection-color: #ffffff;
}
QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus, QSpinBox:focus {
    border-color: #1565c0;
    background-color: #0f1929;
    color: #b0bec5;
}
QLineEdit:hover, QTextEdit:hover {
    border-color: #263a5e;
}
QSpinBox::up-button, QSpinBox::down-button {
    background-color: #1a2540;
    border: none;
    width: 16px;
}
QComboBox {
    background-color: #0d1321;
    color: #90a4ae;
    border: 1px solid #1a2540;
    border-radius: 7px;
    padding: 7px 12px;
    min-width: 80px;
}
QComboBox:focus { border-color: #1565c0; }
QComboBox:hover { border-color: #263a5e; color: #b0bec5; }
QComboBox::drop-down { border: none; width: 22px; }
QComboBox QAbstractItemView {
    background-color: #111827;
    border: 1px solid #1a2540;
    border-radius: 6px;
    selection-background-color: #1565c0;
    selection-color: #ffffff;
    outline: none;
    padding: 4px;
    color: #90a4ae;
}

/* ── List Widget ──────────────────────────────────────────────────── */
QListWidget {
    background-color: #0b0f1a;
    border: 1px solid #1a2540;
    border-radius: 8px;
    outline: none;
    color: #90a4ae;
}
QListWidget::item {
    padding: 9px 14px;
    border-radius: 5px;
    margin: 2px 5px;
}
QListWidget::item:selected {
    background-color: #0d2b4e;
    color: #42a5f5;
}
QListWidget::item:hover:!selected {
    background-color: #111827;
    color: #b0bec5;
}

/* ── Scrollbars ───────────────────────────────────────────────────── */
QScrollBar:vertical {
    background-color: transparent;
    width: 5px;
    border: none;
    margin: 0;
}
QScrollBar::handle:vertical {
    background-color: #1a2540;
    border-radius: 3px;
    min-height: 30px;
}
QScrollBar::handle:vertical:hover { background-color: #263a5e; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar:horizontal {
    background-color: transparent;
    height: 5px;
    border: none;
}
QScrollBar::handle:horizontal {
    background-color: #1a2540;
    border-radius: 3px;
    min-width: 30px;
}
QScrollBar::handle:horizontal:hover { background-color: #263a5e; }
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0; }

/* ── Splitter ─────────────────────────────────────────────────────── */
QSplitter::handle {
    background-color: #1a2540;
    width: 1px;
    height: 1px;
}
QSplitter::handle:hover { background-color: #1565c0; }

/* ── Labels ───────────────────────────────────────────────────────── */
QLabel#section_title {
    font-size: 15px;
    font-weight: 700;
    color: #cfd8dc;
    letter-spacing: 0.3px;
    padding: 0 0 8px 0;
}
QLabel#stat_value {
    font-size: 20px;
    font-weight: 800;
    padding: 0;
    margin: 0;
}
QLabel#stat_label {
    font-size: 9px;
    color: #90a4ae;
    text-transform: uppercase;
    letter-spacing: 1.5px;
    font-weight: 700;
    padding: 0;
    margin: 0;
}

/* ── Frames ───────────────────────────────────────────────────────── */
QFrame#stat_card {
    background-color: #0d1321;
    border: 1px solid #1a2540;
    border-radius: 8px;
    padding: 0;
}
QFrame#stat_card:hover { border-color: #263a5e; }
QFrame#sidebar {
    background-color: #0d1321;
    border-right: 1px solid #1a2540;
}
QFrame#toolbar_frame {
    background-color: #0d1321;
    border-bottom: 1px solid #1a2540;
}

/* ── Status Bar ───────────────────────────────────────────────────── */
QStatusBar {
    background-color: #0d1321;
    border-top: 1px solid #1a2540;
    color: #90a4ae;
    font-size: 11px;
    padding: 2px 10px;
    letter-spacing: 0.3px;
}
QStatusBar::item { border: none; }

/* ── Tooltip ──────────────────────────────────────────────────────── */
QToolTip {
    background-color: #111827;
    color: #90caf9;
    border: 1px solid #1565c0;
    padding: 6px 12px;
    border-radius: 5px;
    font-size: 12px;
}

/* ── GroupBox ─────────────────────────────────────────────────────── */
QGroupBox {
    border: 1px solid #1a2540;
    border-radius: 8px;
    margin-top: 14px;
    padding-top: 12px;
    color: #90a4ae;
    font-size: 10px;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 1.2px;
}
QGroupBox::title {
    subcontrol-origin: margin;
    left: 14px;
    padding: 0 6px;
    background-color: #0b0f1a;
}

/* ── Progress Bar ─────────────────────────────────────────────────── */
QProgressBar {
    background-color: #0d1321;
    border: none;
    border-radius: 2px;
    text-align: center;
    color: transparent;
    height: 3px;
}
QProgressBar::chunk {
    background: qlineargradient(x1:0,y1:0,x2:1,y2:0,
        stop:0 #1565c0, stop:0.5 #42a5f5, stop:1 #1565c0);
    border-radius: 2px;
}

/* ── CheckBox ─────────────────────────────────────────────────────── */
QCheckBox {
    spacing: 8px;
    color: #90a4ae;
}
QCheckBox::indicator {
    width: 15px;
    height: 15px;
    border: 1px solid #263a5e;
    border-radius: 3px;
    background-color: #0d1321;
}
QCheckBox::indicator:checked {
    background-color: #1565c0;
    border-color: #42a5f5;
}
QCheckBox::indicator:hover { border-color: #42a5f5; }
"""

# ── Entity colors ─────────────────────────────────────────────────────
ENTITY_COLORS = {
    "Person":       "#7986cb",   # indigo
    "Email":        "#4db6ac",   # teal
    "Phone":        "#ffb74d",   # orange
    "Address":      "#e57373",   # red
    "IP":           "#ff8a65",   # deep orange
    "Domain":       "#4dd0e1",   # cyan
    "URL":          "#64b5f6",   # blue
    "Crypto":       "#f06292",   # pink
    "Handle":       "#ba68c8",   # purple
    "Hash":         "#aed581",   # light green
    "Document":     "#78909c",   # blue grey
    "Image":        "#ce93d8",   # light purple
    "Organization": "#4db6ac",   # teal
    "Other":        "#546e7a",   # grey
}

ENTITY_TYPES = list(ENTITY_COLORS.keys())

STATUS_COLORS = {
    "Active":   "#4caf50",
    "Closed":   "#ef5350",
    "Pending":  "#ffb300",
    "Archived": "#546e7a",
}

PRIORITY_COLORS = {
    "Critical": "#ef5350",
    "High":     "#ff7043",
    "Medium":   "#ffb300",
    "Low":      "#4caf50",
}

RISK_COLORS = {
    "Critical": "#ef5350",
    "High":     "#ff7043",
    "Medium":   "#ffb300",
    "Low":      "#4caf50",
}
