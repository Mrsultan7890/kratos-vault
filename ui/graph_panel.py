from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QComboBox, QSlider, QCheckBox, QFrame, QLineEdit, QMenu, QMessageBox,
    QApplication
)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QAction
import networkx as nx
import matplotlib
matplotlib.use("QtAgg")
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
import matplotlib.patches as mpatches
from ui.theme import ENTITY_COLORS


class GraphPanel(QWidget):
    enrich_requested = pyqtSignal(str)  # entity_id — MainWindow wires to enrichment

    def __init__(self, db, parent=None):
        super().__init__(parent)
        self.db = db
        self.case_id = None
        self._pos = {}       # node id -> (x, y) for click hit-testing
        self._highlight = ""
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        # Toolbar
        tb = QHBoxLayout()
        title = QLabel("Link Analysis Graph")
        title.setObjectName("section_title")
        tb.addWidget(title)
        tb.addStretch()

        self.layout_combo = QComboBox()
        self.layout_combo.addItems(["Spring", "Kamada-Kawai", "Circular", "Shell", "Spectral", "Random"])
        self.layout_combo.currentIndexChanged.connect(self.refresh)

        self.btn_refresh = QPushButton("↺ Refresh")
        self.btn_refresh.clicked.connect(self.refresh)

        self.btn_auto_link = QPushButton("⚡ Auto-Link")
        self.btn_auto_link.setObjectName("btn_warning")
        self.btn_auto_link.setToolTip("Auto-link entities sharing common values")
        self.btn_auto_link.clicked.connect(self._auto_link)

        self.btn_export = QPushButton("Export PNG")
        self.btn_export.clicked.connect(self._export_png)

        self.show_labels = QCheckBox("Labels")
        self.show_labels.setChecked(True)
        self.show_labels.stateChanged.connect(self.refresh)

        self.show_edge_labels = QCheckBox("Edge Labels")
        self.show_edge_labels.setChecked(True)
        self.show_edge_labels.stateChanged.connect(self.refresh)

        self.highlight_edit = QLineEdit()
        self.highlight_edit.setPlaceholderText("Highlight nodes…")
        self.highlight_edit.setMaximumWidth(160)
        self.highlight_edit.setClearButtonEnabled(True)
        self.highlight_edit.textChanged.connect(self._set_highlight)

        self.btn_export = QPushButton("Export PNG")
        self.btn_export.clicked.connect(self._export_png)

        for w in [QLabel("Layout:"), self.layout_combo, self.show_labels,
                  self.show_edge_labels, self.highlight_edit,
                  self.btn_auto_link, self.btn_refresh, self.btn_export]:
            tb.addWidget(w)
        layout.addLayout(tb)

        # Canvas
        self.figure = Figure(facecolor="#0a0e17", tight_layout=True)
        self.canvas = FigureCanvas(self.figure)
        self.canvas.setMinimumHeight(400)
        self.canvas.mpl_connect("button_press_event", self._on_canvas_click)
        layout.addWidget(self.canvas)

        self.status_label = QLabel("No graph data")
        self.status_label.setStyleSheet("color: #90a4ae; font-size: 12px; font-family: monospace;")
        layout.addWidget(self.status_label)

    def set_case(self, case_id):
        self.case_id = case_id
        self.refresh()

    def _set_highlight(self, text):
        self._highlight = text
        self.refresh()

    def refresh(self):
        self.figure.clear()
        if not self.case_id:
            self.canvas.draw()
            return

        entities = self.db.list_entities(self.case_id)
        edges = self.db.list_edges(self.case_id)

        if not entities:
            ax = self.figure.add_subplot(111)
            ax.set_facecolor("#0a0e17")
            self.figure.patch.set_facecolor("#0a0e17")
            ax.text(0.5, 0.5, "No entities to display", ha="center", va="center",
                    color="#2d4a6b", fontsize=14, transform=ax.transAxes,
                    fontfamily="monospace")
            ax.axis("off")
            self.canvas.draw()
            self.status_label.setText("  0 nodes  ·  0 edges")
            return

        G = nx.DiGraph()
        id_map = {e["id"]: e for e in entities}

        for e in entities:
            G.add_node(e["id"], label=e["name"] or e["value"], type=e["type"])

        edge_labels = {}
        for ed in edges:
            if ed["source"] in id_map and ed["target"] in id_map:
                G.add_edge(ed["source"], ed["target"], weight=ed.get("weight", 1))
                if ed.get("label"):
                    edge_labels[(ed["source"], ed["target"])] = ed["label"]

        layout_name = self.layout_combo.currentText()
        try:
            if layout_name == "Spring":
                pos = nx.spring_layout(G, k=2.5, iterations=50, seed=42)
            elif layout_name == "Kamada-Kawai":
                pos = nx.kamada_kawai_layout(G)
            elif layout_name == "Circular":
                pos = nx.circular_layout(G)
            elif layout_name == "Shell":
                pos = nx.shell_layout(G)
            elif layout_name == "Spectral":
                pos = nx.spectral_layout(G) if len(G) > 2 else nx.spring_layout(G)
            else:
                pos = nx.random_layout(G, seed=42)
        except Exception:
            pos = nx.spring_layout(G, seed=42)

        ax = self.figure.add_subplot(111)
        ax.set_facecolor("#0a0e17")
        self.figure.patch.set_facecolor("#0a0e17")

        nx.draw_networkx_edges(G, pos, ax=ax, edge_color="#1e2d3d",
                               arrows=True, arrowsize=12, width=1.5,
                               connectionstyle="arc3,rad=0.08",
                               node_size=[500 + 150 * G.degree(n) for n in G.nodes()],
                               alpha=0.8)

        # Highlight: matching nodes pop, others fade
        hl = (self._highlight or "").lower().strip()
        node_colors, node_sizes, node_alphas = [], [], []
        for n in G.nodes():
            ntype = G.nodes[n].get("type", "Other")
            nlabel = G.nodes[n].get("label", "")
            matched = hl and (hl in nlabel.lower() or hl in ntype.lower())
            node_colors.append(ENTITY_COLORS.get(ntype, "#64748b"))
            node_sizes.append((700 if matched else 500) + 150 * G.degree(n))
            node_alphas.append(1.0 if (not hl or matched) else 0.18)

        for alpha in sorted(set(node_alphas)):
            idx = [i for i, a in enumerate(node_alphas) if a == alpha]
            nodes_here = [list(G.nodes())[i] for i in idx]
            nx.draw_networkx_nodes(
                G, pos, ax=ax, nodelist=nodes_here,
                node_color=[node_colors[i] for i in idx],
                node_size=[node_sizes[i] for i in idx],
                alpha=alpha, linewidths=1.5, edgecolors="#0a0e17")

        if self.show_labels.isChecked():
            labels = {n: G.nodes[n].get("label", n)[:18] for n in G.nodes()}
            nx.draw_networkx_labels(G, pos, labels, ax=ax,
                                    font_color="#cdd6f4", font_size=8,
                                    font_family="monospace")

        if self.show_edge_labels.isChecked() and edge_labels:
            nx.draw_networkx_edge_labels(G, pos, edge_labels, ax=ax,
                                         font_color="#2d4a6b", font_size=7,
                                         font_family="monospace")

        # Legend
        seen_types = list(set(G.nodes[n].get("type", "Other") for n in G.nodes()))
        patches = [mpatches.Patch(color=ENTITY_COLORS.get(t, "#64748b"), label=t)
                   for t in seen_types]
        if patches:
            ax.legend(handles=patches, loc="upper left", framealpha=0.5,
                      facecolor="#0d1117", edgecolor="#1e2d3d",
                      labelcolor="#7c8fa6", fontsize=8)

        ax.axis("off")
        self.canvas.draw()
        self._pos = dict(pos)  # keep for click hit-testing
        self.status_label.setText(
            f"  {G.number_of_nodes()} nodes  ·  {G.number_of_edges()} edges"
            + (f"  ·  highlight: '{hl}'"
               if hl else "  ·  right-click a node for actions"))

    # ── Node interaction ─────────────────────────────────────────────
    def _node_at(self, x, y):
        """Nearest node within a small screen radius, else None."""
        if not self._pos:
            return None
        import math
        ax = self.figure.axes[0] if self.figure.axes else None
        if ax is None:
            return None
        (x0, x1), (y0, y1) = ax.get_xlim(), ax.get_ylim()
        tol_x = (x1 - x0) * 0.035
        tol_y = (y1 - y0) * 0.035
        best, best_d = None, float("inf")
        for node, (nx_, ny_) in self._pos.items():
            d = math.hypot(nx_ - x, ny_ - y)
            if d < best_d:
                best, best_d = node, d
        if best is None:
            return None
        bx, by = self._pos[best]
        if abs(bx - x) <= tol_x and abs(by - y) <= tol_y:
            return best
        return None

    def _on_canvas_click(self, event):
        if event.button != 3 or event.xdata is None:
            return
        node = self._node_at(event.xdata, event.ydata)
        if not node:
            return
        self._show_node_menu(node, event.guiEvent.globalPosition().toPoint())

    def _show_node_menu(self, node_id: str, global_pos):
        entity = self.db.get_entity(node_id)
        if not entity:
            return
        menu = QMenu(self)
        title = QAction(f"{entity['name'] or entity['value']}", menu)
        title.setEnabled(False)
        menu.addAction(title)
        menu.addSeparator()

        act_details = QAction("🔍 View details", menu)
        act_details.triggered.connect(
            lambda: self._open_details(entity))
        menu.addAction(act_details)

        act_enrich = QAction("⚡ Enrich now", menu)
        act_enrich.triggered.connect(lambda: self.enrich_requested.emit(node_id))
        menu.addAction(act_enrich)

        act_copy = QAction("⧉ Copy value", menu)
        act_copy.triggered.connect(
            lambda: QApplication.clipboard().setText(entity["value"]))
        menu.addAction(act_copy)

        menu.addSeparator()
        act_delete = QAction("✕ Delete entity", menu)
        act_delete.triggered.connect(lambda: self._delete_node(entity))
        menu.addAction(act_delete)

        menu.exec(global_pos)

    def _open_details(self, entity):
        from ui.entities_panel import EntityDetailDialog
        dlg = EntityDetailDialog(entity, parent=self)
        dlg.exec()

    def _delete_node(self, entity):
        reply = QMessageBox.question(
            self, "Delete",
            f"Delete entity '{entity['name'] or entity['value']}' and its links?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if reply == QMessageBox.StandardButton.Yes:
            self.db.delete_entity(entity["id"])
            self.refresh()

    def _auto_link(self):
        if not self.case_id:
            return
        entities = self.db.list_entities(self.case_id)
        existing_edges = self.db.list_edges(self.case_id)
        existing_pairs = {(e["source"], e["target"]) for e in existing_edges}
        existing_pairs |= {(t, s) for s, t in existing_pairs}  # treat reverse as existing
        count = 0
        for i in range(len(entities)):
            for j in range(i + 1, len(entities)):
                a, b = entities[i], entities[j]
                va, vb = (a["value"] or "").lower(), (b["value"] or "").lower()
                if not va or not vb:
                    continue
                linked = False
                if va == vb:
                    linked = True
                elif len(va) > 6 and (va in vb or vb in va):
                    linked = True
                if linked and (a["id"], b["id"]) not in existing_pairs:
                    self.db.create_edge(self.case_id, a["id"], b["id"], label="matches")
                    existing_pairs.add((a["id"], b["id"]))
                    count += 1
        self.db.add_event(self.case_id, "auto_link", f"Auto-linked {count} connections")
        self.refresh()
        self.status_label.setText(f"Auto-linked {count} new connections")

    def _export_png(self):
        from PyQt6.QtWidgets import QFileDialog
        path, _ = QFileDialog.getSaveFileName(self, "Export Graph", "graph.png", "PNG (*.png)")
        if path:
            self.figure.savefig(path, dpi=150, bbox_inches="tight",
                                facecolor="#0a0e17")
