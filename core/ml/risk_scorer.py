"""
Risk Scoring Engine — XGBoost + NetworkX graph features
Scores each entity 0-100 based on:
  - Graph centrality (degree, betweenness, pagerank)
  - Entity type weight
  - Connection count
  - Confidence level
  - Tag signals (auto-extracted, suspicious keywords)

Training uses randomly generated GRAPHS run through the SAME _extract_features
used at prediction time, so training and inference distributions always match.
The pickle stores a MODEL_VERSION; if code changes the feature pipeline,
the model retrains automatically instead of serving stale predictions.
"""
import numpy as np
import pickle
from typing import List, Dict, Tuple
from pathlib import Path
import networkx as nx

_MODEL_PATH = Path.home() / ".kratos_vault" / "risk_model.pkl"
_MODEL_VERSION = 3  # bump when features/labels change → auto-retrain
_model = None
_model_version = None

# Base risk weights per entity type
_TYPE_WEIGHTS = {
    "Person":       0.8,
    "IP":           0.9,
    "Crypto":       0.95,
    "Hash":         0.7,
    "Email":        0.6,
    "Phone":        0.6,
    "URL":          0.75,
    "Domain":       0.7,
    "Handle":       0.5,
    "Address":      0.4,
    "Document":     0.6,
    "Image":        0.3,
    "Organization": 0.5,
    "Other":        0.3,
}

_SUSPICIOUS_TAGS = {"suspicious", "malware", "c2", "phishing", "tor", "btc", "eth",
                    "auto-extracted", "darkweb", "leaked", "breach"}
_SUSPICIOUS_SOURCES = {"shodan", "virustotal", "darkweb", "breach", "leak"}


def _label(entity: Dict, G: nx.DiGraph, pagerank: Dict, betweenness: Dict) -> float:
    """Transparent ground-truth heuristic used as training target —
    the same factors _explain_score reports to the investigator."""
    eid = entity["id"]
    degree = G.degree(eid) if eid in G else 0
    pr = pagerank.get(eid, 0.0)
    bw = betweenness.get(eid, 0.0)
    type_w = _TYPE_WEIGHTS.get(entity.get("type", "Other"), 0.3)
    confidence = entity.get("confidence", 50) / 100.0
    tags = set(t.lower() for t in entity.get("tags", []))
    suspicious = len(tags & _SUSPICIOUS_TAGS)
    source = entity.get("source", "").lower()
    sus_source = 1.0 if any(s in source for s in _SUSPICIOUS_SOURCES) else 0.0

    score = (
        min(degree, 15) / 15 * 30 +          # connectivity
        min(pr * 100, 50) / 50 * 20 +        # centrality
        min(bw * 100, 50) / 50 * 10 +        # bridging power
        type_w * 15 +                        # entity type danger
        confidence * 10 +                    # how sure we are
        min(suspicious, 4) / 4 * 10 +        # suspicious tags
        sus_source * 5                       # suspicious source
    )
    return float(np.clip(score, 0, 100))


def _build_graph(entities: List[Dict], edges: List[Dict]) -> nx.DiGraph:
    G = nx.DiGraph()
    for e in entities:
        G.add_node(e["id"])
    for ed in edges:
        if ed["source"] in G and ed["target"] in G:
            G.add_edge(ed["source"], ed["target"], weight=ed.get("weight", 1))
    return G


def _extract_features(entity: Dict, G: nx.DiGraph,
                       pagerank: Dict, betweenness: Dict) -> np.ndarray:
    eid = entity["id"]
    degree       = G.degree(eid) if eid in G else 0
    in_degree    = G.in_degree(eid) if eid in G else 0
    out_degree   = G.out_degree(eid) if eid in G else 0
    pr           = pagerank.get(eid, 0.0)
    bw           = betweenness.get(eid, 0.0)
    type_w       = _TYPE_WEIGHTS.get(entity.get("type", "Other"), 0.3)
    confidence   = entity.get("confidence", 50) / 100.0
    linked_count = len(entity.get("linked_to", []))

    tags = set(t.lower() for t in entity.get("tags", []))
    suspicious_tag_count = len(tags & _SUSPICIOUS_TAGS)

    source = entity.get("source", "").lower()
    suspicious_source = 1.0 if any(s in source for s in _SUSPICIOUS_SOURCES) else 0.0

    return np.array([
        degree, in_degree, out_degree,
        pr * 100, bw * 100,
        type_w, confidence,
        linked_count,
        suspicious_tag_count,
        suspicious_source,
    ], dtype=np.float32)


def _random_entity(rng, eid: str) -> Dict:
    """Random but realistic entity for training."""
    etype = rng.choice(list(_TYPE_WEIGHTS.keys()))
    n_tags = rng.integers(0, 5)
    tags = list(rng.choice(list(_SUSPICIOUS_TAGS), size=n_tags,
                           replace=False)) if n_tags else []
    if rng.random() < 0.4:
        tags.append("auto-extracted")
    sources = ["", "manual", "linkedin", "instagram", "whois", "ghunt",
               "shodan", "virustotal", "darkweb", "breach"]
    return {
        "id": eid,
        "type": etype,
        "confidence": int(rng.integers(0, 101)),
        "tags": tags,
        "source": rng.choice(sources),
        "linked_to": [],
    }


def _train_model():
    """
    Train XGBoost on synthetic cases whose features are produced by the REAL
    feature extractor applied to random graphs — no train/serve skew.
    Labels come from the transparent _label heuristic.
    """
    import xgboost as xgb

    X_list, y_list = [], []
    rng = np.random.default_rng(42)

    for _ in range(600):                    # 600 random graphs ≈ 6000 entities
        n = int(rng.integers(5, 40))
        G = nx.DiGraph()
        G.add_nodes_from(str(i) for i in range(n))
        p_edge = rng.uniform(0.05, 0.35)
        for i in range(n):
            for j in range(n):
                if i != j and rng.random() < p_edge:
                    G.add_edge(str(i), str(j))

        pagerank = nx.pagerank(G) if G.number_of_edges() else {}
        betweenness = nx.betweenness_centrality(G)

        for i in range(n):
            ent = _random_entity(rng, str(i))
            ent["linked_to"] = list(G.successors(str(i)))[:10]
            X_list.append(_extract_features(ent, G, pagerank, betweenness))
            y_list.append(_label(ent, G, pagerank, betweenness))

    X = np.array(X_list, dtype=np.float32)
    y = np.array(y_list, dtype=np.float32)

    model = xgb.XGBRegressor(
        n_estimators=150, max_depth=4, learning_rate=0.08,
        subsample=0.8, colsample_bytree=0.8,
        random_state=42, verbosity=0
    )
    model.fit(X, y)

    _MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(_MODEL_PATH, "wb") as f:
        pickle.dump({"version": _MODEL_VERSION, "model": model}, f)
    return model


def _get_model():
    global _model, _model_version
    if _model is not None:
        return _model
    if _MODEL_PATH.exists():
        try:
            with open(_MODEL_PATH, "rb") as f:
                blob = pickle.load(f)
            # New format: {"version": int, "model": obj}. Old format (bare
            # model) or older version → retrain instead of stale predictions.
            if isinstance(blob, dict) and blob.get("version") == _MODEL_VERSION:
                _model = blob["model"]
                _model_version = blob["version"]
                return _model
        except Exception:
            pass
    _model = _train_model()
    _model_version = _MODEL_VERSION
    return _model


def retrain():
    """Force retrain and save model."""
    global _model, _model_version
    _model = _train_model()
    _model_version = _MODEL_VERSION
    return _model


def score_entities(entities: List[Dict], edges: List[Dict]) -> List[Dict]:
    """
    Score all entities and return sorted list with risk scores.
    Returns: [{"entity": {...}, "risk_score": 0-100, "risk_level": "Critical/High/Medium/Low", "factors": [...]}, ...]
    """
    if not entities:
        return []

    model = _get_model()
    G = _build_graph(entities, edges)

    # Graph metrics
    try:
        pagerank = nx.pagerank(G, alpha=0.85) if G.number_of_edges() > 0 else {}
    except Exception:
        pagerank = {}
    try:
        betweenness = nx.betweenness_centrality(G) if G.number_of_nodes() > 1 else {}
    except Exception:
        betweenness = {}

    results = []
    for entity in entities:
        features = _extract_features(entity, G, pagerank, betweenness)
        raw_score = float(model.predict(features.reshape(1, -1))[0])
        score = int(np.clip(raw_score, 0, 100))

        if score >= 75:
            level = "Critical"
            color = "#da3633"
        elif score >= 55:
            level = "High"
            color = "#f85149"
        elif score >= 35:
            level = "Medium"
            color = "#d29922"
        else:
            level = "Low"
            color = "#2ea043"

        factors = _explain_score(entity, G, pagerank, betweenness)

        results.append({
            "entity":     entity,
            "risk_score": score,
            "risk_level": level,
            "color":      color,
            "factors":    factors,
        })

    results.sort(key=lambda x: x["risk_score"], reverse=True)
    return results


def _explain_score(entity: Dict, G: nx.DiGraph,
                   pagerank: Dict, betweenness: Dict) -> List[str]:
    factors = []
    eid = entity["id"]
    degree = G.degree(eid) if eid in G else 0
    if degree >= 5:
        factors.append(f"High connectivity ({degree} connections)")
    pr = pagerank.get(eid, 0)
    if pr > 0.05:
        factors.append(f"High PageRank ({pr:.3f})")
    type_w = _TYPE_WEIGHTS.get(entity.get("type", "Other"), 0.3)
    if type_w >= 0.8:
        factors.append(f"High-risk entity type ({entity.get('type')})")
    tags = set(t.lower() for t in entity.get("tags", []))
    suspicious = tags & _SUSPICIOUS_TAGS
    if suspicious:
        factors.append(f"Suspicious tags: {', '.join(suspicious)}")
    source = entity.get("source", "").lower()
    if any(s in source for s in _SUSPICIOUS_SOURCES):
        factors.append(f"Suspicious source: {source}")
    if not factors:
        factors.append("Low risk profile")
    return factors
