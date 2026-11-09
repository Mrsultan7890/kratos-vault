from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView,
    QTabWidget, QTextEdit, QProgressBar, QMessageBox, QSlider
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QColor


class MLWorker(QThread):
    result = pyqtSignal(str, object)
    error  = pyqtSignal(str, str)

    def __init__(self, task, *args):
        super().__init__()
        self.task = task
        self.args = args

    def run(self):
        try:
            if self.task == "ner":
                from core.ml.ner_engine import extract_entities
                self.result.emit("ner", extract_entities(self.args[0]))
            elif self.task == "dedup":
                from core.ml.dedup_engine import find_duplicates
                threshold = self.args[1] if len(self.args) > 1 else 0.82
                self.result.emit("dedup", find_duplicates(self.args[0], threshold))
            elif self.task == "risk":
                from core.ml.risk_scorer import score_entities
                self.result.emit("risk", score_entities(self.args[0], self.args[1]))
            elif self.task == "links":
                from core.ml.link_predictor import predict_links, get_graph_stats
                self.result.emit("links", {
                    "links": predict_links(self.args[0], self.args[1]),
                    "stats": get_graph_stats(self.args[0], self.args[1])
                })
        except Exception as e:
            self.error.emit(self.task, str(e))


class MLPanel(QWidget):
    data_changed = pyqtSignal()
    def __init__(self, db, parent=None):
        super().__init__(parent)
        self.db = db
        self.case_id = None
        self._worker = None
        self._workers = set()
        self._ner_results = []
        self._dedup_results = []
        self._links_results = []
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        title = QLabel("ML Intelligence")
        title.setObjectName("section_title")
        layout.addWidget(title)

        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.setFixedHeight(4)
        self.progress.hide()
        layout.addWidget(self.progress)

        tabs = QTabWidget()
        tabs.addTab(self._build_ner_tab(),   "🧠 NER Extract")
        tabs.addTab(self._build_dedup_tab(), "🔍 Deduplication")
        tabs.addTab(self._build_risk_tab(),  "⚠ Risk Scoring")
        tabs.addTab(self._build_links_tab(), "🔗 Link Prediction")
        layout.addWidget(tabs)

    def set_case(self, case_id):
        self.case_id = case_id

    # ── NER ──────────────────────────────────────────────────────────────
    def _build_ner_tab(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setSpacing(8)
        lay.addWidget(QLabel("Paste raw text — spaCy NER + regex extracts entities automatically:"))

        self.ner_input = QTextEdit()
        self.ner_input.setPlaceholderText(
            "Paste reports, chat logs, emails, articles...\n"
            "Extracts: Person, Org, Location, Email, Phone, IP, URL, Hash, Crypto")
        self.ner_input.setMaximumHeight(130)
        lay.addWidget(self.ner_input)

        tb = QHBoxLayout()
        self.btn_ner_run = QPushButton("⚡ Run NER")
        self.btn_ner_run.setObjectName("btn_primary")
        self.btn_ner_run.clicked.connect(self._run_ner)
        self.btn_ner_import = QPushButton("Import Selected")
        self.btn_ner_import.setObjectName("btn_success")
        self.btn_ner_import.clicked.connect(self._import_ner)
        self.btn_ner_import.setEnabled(False)
        self.ner_status = QLabel("")
        self.ner_status.setStyleSheet("color:#8b949e;font-size:12px;")
        tb.addWidget(self.btn_ner_run)
        tb.addWidget(self.btn_ner_import)
        tb.addWidget(self.ner_status)
        tb.addStretch()
        lay.addLayout(tb)

        self.ner_table = QTableWidget()
        self.ner_table.setColumnCount(4)
        self.ner_table.setHorizontalHeaderLabels(["✓", "Type", "Value", "Source"])
        self.ner_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.ner_table.setAlternatingRowColors(True)
        self.ner_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        lay.addWidget(self.ner_table)
        return w

    # ── Dedup ─────────────────────────────────────────────────────────────
    def _build_dedup_tab(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setSpacing(8)
        info = QLabel(
            "Finds entities that may refer to the same subject using MiniLM-L6-v2 embeddings.\n"
            "Adjust the similarity threshold on the right, then select pairs to link them.")
        info.setStyleSheet("color:#8b949e;font-size:12px;")
        lay.addWidget(info)

        tb = QHBoxLayout()
        self.btn_dedup_run = QPushButton("🔍 Find Duplicates")
        self.btn_dedup_run.setObjectName("btn_primary")
        self.btn_dedup_run.clicked.connect(self._run_dedup)
        self.btn_dedup_link = QPushButton("Link Selected Pairs")
        self.btn_dedup_link.setObjectName("btn_warning")
        self.btn_dedup_link.clicked.connect(self._link_dedup_pairs)
        self.btn_dedup_link.setEnabled(False)
        self.dedup_status = QLabel("")
        self.dedup_status.setStyleSheet("color:#8b949e;font-size:12px;")
        tb.addWidget(self.btn_dedup_run)
        tb.addWidget(self.btn_dedup_link)
        tb.addWidget(self.dedup_status)
        tb.addStretch()

        tb.addWidget(QLabel("Threshold:"))
        self.dedup_slider = QSlider(Qt.Orientation.Horizontal)
        self.dedup_slider.setRange(60, 95)
        self.dedup_slider.setValue(82)
        self.dedup_slider.setMaximumWidth(140)
        self.dedup_slider.setTickPosition(QSlider.TickPosition.TicksBelow)
        self.dedup_slider.setTickInterval(5)
        self.dedup_slider.valueChanged.connect(
            lambda v: self.dedup_threshold_lbl.setText(f"{v}%"))
        self.dedup_threshold_lbl = QLabel("82%")
        self.dedup_threshold_lbl.setStyleSheet("color:#e6edf3;font-size:12px;font-weight:700;")
        self.dedup_threshold_lbl.setMinimumWidth(34)
        self.dedup_slider.setToolTip(
            "Similarity above this = possible duplicate.\n"
            "Lower (60-70%) finds loose matches, higher (85%+) only near-identical.")
        tb.addWidget(self.dedup_slider)
        tb.addWidget(self.dedup_threshold_lbl)
        lay.addLayout(tb)

        self.dedup_table = QTableWidget()
        self.dedup_table.setColumnCount(5)
        self.dedup_table.setHorizontalHeaderLabels(
            ["✓", "Entity A", "Entity B", "Similarity", "Reason"])
        self.dedup_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.dedup_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.dedup_table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        self.dedup_table.setAlternatingRowColors(True)
        self.dedup_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        lay.addWidget(self.dedup_table)
        self._dedup_results = []
        return w

    # ── Risk ──────────────────────────────────────────────────────────────
    def _build_risk_tab(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setSpacing(8)
        info = QLabel(
            "Experimental heuristic estimate (not a probability or validated risk assessment).\n"
            "Trained on synthetic graphs and heuristic labels; verify factors independently.")
        info.setStyleSheet("color:#8b949e;font-size:12px;")
        lay.addWidget(info)

        tb = QHBoxLayout()
        self.btn_risk_run = QPushButton("⚠ Score All Entities")
        self.btn_risk_run.setObjectName("btn_primary")
        self.btn_risk_run.clicked.connect(self._run_risk)
        self.risk_status = QLabel("")
        self.risk_status.setStyleSheet("color:#8b949e;font-size:12px;")
        tb.addWidget(self.btn_risk_run)
        tb.addWidget(self.risk_status)
        tb.addStretch()
        lay.addLayout(tb)

        self.risk_table = QTableWidget()
        self.risk_table.setColumnCount(5)
        self.risk_table.setHorizontalHeaderLabels(
            ["Entity", "Type", "Risk Score", "Level", "Factors"])
        self.risk_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.risk_table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        self.risk_table.setAlternatingRowColors(True)
        self.risk_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        lay.addWidget(self.risk_table)
        return w

    # ── Link Prediction ───────────────────────────────────────────────────
    def _build_links_tab(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setSpacing(8)
        info = QLabel(
            "Predicts missing links using Jaccard, Adamic-Adar & Preferential Attachment.\n"
            "Check predictions and add them as real edges.")
        info.setStyleSheet("color:#8b949e;font-size:12px;")
        lay.addWidget(info)

        tb = QHBoxLayout()
        self.btn_links_run = QPushButton("🔗 Predict Links")
        self.btn_links_run.setObjectName("btn_primary")
        self.btn_links_run.clicked.connect(self._run_links)
        self.btn_links_add = QPushButton("Add Selected as Edges")
        self.btn_links_add.setObjectName("btn_success")
        self.btn_links_add.clicked.connect(self._add_predicted_links)
        self.btn_links_add.setEnabled(False)
        self.links_status = QLabel("")
        self.links_status.setStyleSheet("color:#8b949e;font-size:12px;")
        tb.addWidget(self.btn_links_run)
        tb.addWidget(self.btn_links_add)
        tb.addWidget(self.links_status)
        tb.addStretch()
        lay.addLayout(tb)

        self.stats_label = QLabel("")
        self.stats_label.setStyleSheet(
            "color:#e6edf3;font-size:12px;background:#161b22;"
            "border:1px solid #30363d;border-radius:4px;padding:6px;")
        lay.addWidget(self.stats_label)

        self.links_table = QTableWidget()
        self.links_table.setColumnCount(5)
        self.links_table.setHorizontalHeaderLabels(
            ["✓", "Source", "Target", "Score", "Reason"])
        self.links_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.links_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.links_table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        self.links_table.setAlternatingRowColors(True)
        self.links_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        lay.addWidget(self.links_table)
        return w

    # ── Worker helpers ────────────────────────────────────────────────────
    def _start_worker(self, task, *args):
        self.progress.show()
        self._worker = MLWorker(task, *args)
        self._worker.result.connect(self._on_result)
        self._worker.error.connect(self._on_error)
        self._worker.finished.connect(self.progress.hide)
        self._worker.finished.connect(lambda w=self._worker: self._workers.discard(w))
        self._workers.add(self._worker)
        self._worker.start()

    def wait_for_workers(self):
        for worker in tuple(self._workers):
            worker.requestInterruption()
            worker.wait()

    def _on_error(self, task, msg):
        self.progress.hide()
        QMessageBox.critical(self, f"ML Error ({task})", msg)

    def _on_result(self, task, data):
        if task == "ner":
            self._show_ner(data)
        elif task == "dedup":
            self._show_dedup(data)
        elif task == "risk":
            self._show_risk(data)
        elif task == "links":
            self._show_links(data)

    # ── NER handlers ──────────────────────────────────────────────────────
    def _run_ner(self):
        if not self.case_id:
            QMessageBox.warning(self, "No Case", "Open a case first.")
            return
        text = self.ner_input.toPlainText().strip()
        if not text:
            QMessageBox.warning(self, "Empty", "Paste some text first.")
            return
        self.btn_ner_run.setEnabled(False)
        self._start_worker("ner", text)
        self._worker.finished.connect(lambda: self.btn_ner_run.setEnabled(True))

    def _show_ner(self, results):
        self._ner_results = results
        self.ner_table.setRowCount(len(results))
        from ui.theme import ENTITY_COLORS
        for row, e in enumerate(results):
            chk = QTableWidgetItem()
            chk.setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled)
            chk.setCheckState(Qt.CheckState.Checked)
            type_item = QTableWidgetItem(e["type"])
            type_item.setForeground(QColor(ENTITY_COLORS.get(e["type"], "#9ca3af")))
            for col, item in enumerate([
                chk,
                type_item,
                QTableWidgetItem(e["value"]),
                QTableWidgetItem(e.get("source", "")),
            ]):
                self.ner_table.setItem(row, col, item)
        self.ner_status.setText(f"Found {len(results)} entities")
        self.btn_ner_import.setEnabled(len(results) > 0)

    def _import_ner(self):
        count = skipped = 0
        for row in range(self.ner_table.rowCount()):
            chk = self.ner_table.item(row, 0)
            if chk and chk.checkState() == Qt.CheckState.Checked:
                e = self._ner_results[row]
                created = self.db.create_entity(
                    self.case_id, e["type"], e["name"], e["value"],
                    notes=e.get("notes", ""), tags=e.get("tags", []),
                    confidence=e.get("confidence", 75), source=e.get("source", ""))
                if created.get("duplicate"):
                    skipped += 1
                else:
                    count += 1
        msg = f"Imported {count} entities"
        if skipped:
            msg += f", skipped {skipped} duplicate(s)"
        self.ner_status.setText(msg)
        if count > 0:
            self.data_changed.emit()

    # ── Dedup handlers ────────────────────────────────────────────────────
    def _run_dedup(self):
        if not self.case_id:
            QMessageBox.warning(self, "No Case", "Open a case first.")
            return
        entities = self.db.list_entities(self.case_id)
        if len(entities) < 2:
            QMessageBox.information(self, "Info", "Need at least 2 entities.")
            return
        self.btn_dedup_run.setEnabled(False)
        self._start_worker("dedup", entities, self.dedup_slider.value() / 100)
        self._worker.finished.connect(lambda: self.btn_dedup_run.setEnabled(True))

    def _show_dedup(self, results):
        self._dedup_results = results
        self.dedup_table.setRowCount(len(results))
        for row, r in enumerate(results):
            chk = QTableWidgetItem()
            chk.setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled)
            chk.setCheckState(Qt.CheckState.Checked)
            sim = r["similarity"]
            sim_item = QTableWidgetItem(f"{sim:.1%}")
            sim_item.setForeground(QColor(
                "#da3633" if sim >= 0.95 else "#d29922" if sim >= 0.88 else "#2ea043"))
            for col, item in enumerate([
                chk,
                QTableWidgetItem(f"[{r['entity_a']['type']}] {r['entity_a']['name']}"),
                QTableWidgetItem(f"[{r['entity_b']['type']}] {r['entity_b']['name']}"),
                sim_item,
                QTableWidgetItem(r["reason"]),
            ]):
                self.dedup_table.setItem(row, col, item)
        self.dedup_status.setText(f"{len(results)} potential duplicate pair(s)")
        self.btn_dedup_link.setEnabled(len(results) > 0)

    def _link_dedup_pairs(self):
        count = 0
        for row in range(self.dedup_table.rowCount()):
            chk = self.dedup_table.item(row, 0)
            if chk and chk.checkState() == Qt.CheckState.Checked:
                r = self._dedup_results[row]
                a, b = r["entity_a"], r["entity_b"]
                self.db.create_edge(self.case_id, a["id"], b["id"],
                                    label=f"similar ({r['similarity']:.0%})")
                self.db.add_event(self.case_id, "link_created",
                                  f"Dedup link: {a['name']} ↔ {b['name']}",
                                  detail=r["reason"])
                count += 1
        self.dedup_status.setText(f"Linked {count} pairs")
        if count > 0:
            self.data_changed.emit()

    # ── Risk handlers ─────────────────────────────────────────────────────
    def _run_risk(self):
        if not self.case_id:
            QMessageBox.warning(self, "No Case", "Open a case first.")
            return
        entities = self.db.list_entities(self.case_id)
        edges = self.db.list_edges(self.case_id)
        if not entities:
            QMessageBox.information(self, "Info", "No entities to score.")
            return
        self.btn_risk_run.setEnabled(False)
        self._start_worker("risk", entities, edges)
        self._worker.finished.connect(lambda: self.btn_risk_run.setEnabled(True))

    def _show_risk(self, results):
        self.risk_table.setRowCount(len(results))
        for row, r in enumerate(results):
            e = r["entity"]
            score_item = QTableWidgetItem(str(r["risk_score"]))
            level_item = QTableWidgetItem(r["risk_level"])
            score_item.setForeground(QColor(r["color"]))
            level_item.setForeground(QColor(r["color"]))
            for col, item in enumerate([
                QTableWidgetItem(e["name"] or e["value"]),
                QTableWidgetItem(e["type"]),
                score_item,
                level_item,
                QTableWidgetItem(" | ".join(r["factors"])),
            ]):
                item.setTextAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
                self.risk_table.setItem(row, col, item)
        self.risk_status.setText(f"Scored {len(results)} entities")

    # ── Link Prediction handlers ──────────────────────────────────────────
    def _run_links(self):
        if not self.case_id:
            QMessageBox.warning(self, "No Case", "Open a case first.")
            return
        entities = self.db.list_entities(self.case_id)
        edges = self.db.list_edges(self.case_id)
        if len(entities) < 3:
            QMessageBox.information(self, "Info", "Need at least 3 entities.")
            return
        self.btn_links_run.setEnabled(False)
        self._start_worker("links", entities, edges)
        self._worker.finished.connect(lambda: self.btn_links_run.setEnabled(True))

    def _show_links(self, data):
        self._links_results = data["links"]
        stats = data["stats"]
        if stats:
            self.stats_label.setText(
                f"Nodes: {stats.get('nodes',0)}  |  "
                f"Edges: {stats.get('edges',0)}  |  "
                f"Density: {stats.get('density',0)}  |  "
                f"Components: {stats.get('components',0)}  |  "
                f"Avg Degree: {stats.get('avg_degree',0)}  |  "
                f"Most Central: {stats.get('most_central','—')}")

        self.links_table.setRowCount(len(self._links_results))
        for row, r in enumerate(self._links_results):
            chk = QTableWidgetItem()
            chk.setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled)
            chk.setCheckState(Qt.CheckState.Unchecked)
            score_item = QTableWidgetItem(f"{r['score']:.4f}")
            score_item.setForeground(QColor(
                "#2ea043" if r["score"] > 0.3 else "#d29922" if r["score"] > 0.1 else "#8b949e"))
            for col, item in enumerate([
                chk,
                QTableWidgetItem(f"[{r['source']['type']}] {r['source']['name']}"),
                QTableWidgetItem(f"[{r['target']['type']}] {r['target']['name']}"),
                score_item,
                QTableWidgetItem(r["reason"]),
            ]):
                self.links_table.setItem(row, col, item)
        self.links_status.setText(f"{len(self._links_results)} predicted link(s)")
        self.btn_links_add.setEnabled(len(self._links_results) > 0)

    def _add_predicted_links(self):
        count = 0
        for row in range(self.links_table.rowCount()):
            chk = self.links_table.item(row, 0)
            if chk and chk.checkState() == Qt.CheckState.Checked:
                r = self._links_results[row]
                self.db.create_edge(
                    self.case_id,
                    r["source"]["id"], r["target"]["id"],
                    label=f"predicted ({r['score']:.2f})")
                self.db.add_event(
                    self.case_id, "link_created",
                    f"Predicted: {r['source']['name']} → {r['target']['name']}",
                    detail=r["reason"])
                count += 1
        self.links_status.setText(f"Added {count} predicted edge(s)")
        if count > 0:
            self.data_changed.emit()
