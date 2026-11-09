"""
Deduplication Engine — sentence-transformers all-MiniLM-L6-v2
Finds semantically similar entities that might be the same subject.
"""
from typing import List, Dict, Tuple
import numpy as np

_model = None
_MODEL_NAME = "all-MiniLM-L6-v2"


def _get_model():
    global _model
    if _model is None:
        from sentence_transformers import SentenceTransformer
        _model = SentenceTransformer(_MODEL_NAME)
    return _model


def _cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b) + 1e-9))


def find_duplicates(
    entities: List[Dict],
    threshold: float = 0.82
) -> List[Dict]:
    """
    Compare all entity values using embeddings.
    Returns list of duplicate groups:
    [
      {
        "entity_a": {...},
        "entity_b": {...},
        "similarity": 0.91,
        "reason": "High semantic similarity"
      },
      ...
    ]
    """
    if len(entities) < 2:
        return []

    model = _get_model()
    texts = [f"{e['type']} {e['name']} {e['value']}" for e in entities]
    embeddings = model.encode(texts, batch_size=64, show_progress_bar=False)

    duplicates = []
    seen_pairs = set()

    for i in range(len(entities)):
        for j in range(i + 1, len(entities)):
            pair_key = (entities[i]["id"], entities[j]["id"])
            if pair_key in seen_pairs:
                continue
            seen_pairs.add(pair_key)

            sim = _cosine_similarity(embeddings[i], embeddings[j])
            if sim >= threshold:
                reason = _explain_similarity(entities[i], entities[j], sim)
                duplicates.append({
                    "entity_a":  entities[i],
                    "entity_b":  entities[j],
                    "similarity": round(sim, 3),
                    "reason":    reason,
                })

    # Sort by similarity descending
    duplicates.sort(key=lambda x: x["similarity"], reverse=True)
    return duplicates


def _explain_similarity(a: Dict, b: Dict, sim: float) -> str:
    if a["value"].lower() == b["value"].lower():
        return "Exact value match"
    if a["type"] == b["type"]:
        return f"Same type ({a['type']}), similarity {sim:.0%}"
    return f"Cross-type similarity {sim:.0%} — possible same subject"


def embed_text(text: str) -> np.ndarray:
    """Embed a single text string."""
    return _get_model().encode(text, show_progress_bar=False)


def batch_embed(texts: List[str]) -> np.ndarray:
    """Embed multiple texts."""
    return _get_model().encode(texts, batch_size=64, show_progress_bar=False)
