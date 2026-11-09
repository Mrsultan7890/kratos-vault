# Kratos Vault — ML Model Card

## 1. Risk Scorer (`core/ml/risk_scorer.py`)

| | |
|---|---|
| Model | XGBoost Regressor (150 trees, depth 4) |
| Output | Risk score 0–100 + level (Critical/High/Medium/Low) |
| Features (10) | degree, in/out-degree, PageRank×100, betweenness×100, entity-type weight, confidence/100, linked_count, suspicious-tag count, suspicious-source flag |
| Training data | 600 random graphs (~6000 entities). Features computed by the **same** `_extract_features` used at inference (no train/serve skew). Labels from transparent `_label` heuristic (connectivity 30%, centrality 20%, bridging 10%, type 15%, confidence 10%, tags 10%, source 5%). |
| Storage | `~/.kratos_vault/risk_model.pkl` with `{"version": N, "model": ...}` — auto-retrains when `MODEL_VERSION` changes |
| Limitations | This is an experimental heuristic estimate, not a probability or validated risk assessment. Labels are synthetic/heuristic, not real investigation outcomes; no empirical predictive validity is claimed. Verify every factor independently. Retrain periodically via `python -c "from core.ml.risk_scorer import retrain; retrain()"` only after defining and evaluating suitable real-case labels. Suspicious-tag list is static English-only. |

## 2. Entity Type Classifier (`core/ml/classifier.py`)

| | |
|---|---|
| Model | TF-IDF (char_wb 2–4 grams) + LogisticRegression |
| Output | Entity type + confidence (0–1) |
| Classes | Email, Phone, IP, Domain, URL, Hash, Crypto, Handle, Person, Address, Document, Image |
| Training data | Handwritten examples in `_TRAINING_DATA` (~60 rows); structural features (regex flags for @, digits, hex, file extensions) appended to text |
| Use | Auto-suggests Type in the Add-Entity dialog when confidence ≥ 55%; user override always wins |
| Storage | `~/.kratos_vault/entity_classifier.pkl` (versioned, auto-retrains) |
| Limitations | Small training set; Person/Address detection is weak (intended as a suggestion, not ground truth) |

## 3. NER Engine (`core/ml/ner_engine.py`)

| | |
|---|---|
| Model | spaCy `en_core_web_sm` + regex fallback |
| Output | Person / Organization / Address / Other entities + regex IOCs (Email, Phone, URL, IP, Hash, Crypto incl. bech32) |
| Failure mode | If the spaCy model is missing, regex extraction still runs; a clear error (`NERModelError`) is raised only where spaCy is required |

## 4. Image Analyzer (`core/ml/image_analyzer.py`)

| | |
|---|---|
| Models | YOLOv8n (80 COCO classes, conf ≥ 0.35) + OpenCV haar cascade `haarcascade_frontalface_default.xml` |
| Output | Objects with bbox+confidence, face count + face boxes, relevant-object list, risk flags (weapons, faces) |
| Storage | `~/.kratos_vault/yolov8n.pt`; cascades ship with opencv-python |
| Failure mode | Model file missing → `model_missing: True` + how-to note instead of empty result; cascade missing → face count 0 |
| Limitations | Haar cascade detects only frontal faces (no profile/occluded); YOLO conf 0.35 may miss small objects; weapons beyond COCO classes (e.g. rifles labelled as knives) are fuzzy |

## 5. Dedup Engine (`core/ml/dedup_engine.py`)

| | |
|---|---|
| Model | sentence-transformers `all-MiniLM-L6-v2` (384-dim embeddings) |
| Output | Entity pairs with cosine similarity ≥ threshold (user-adjustable 60–95% in ML panel, default 82%) |
| Limitations | O(n²) pair comparisons — fine for ≤ a few hundred entities; embeddings favour literal text similarity over semantics of different writing styles |
