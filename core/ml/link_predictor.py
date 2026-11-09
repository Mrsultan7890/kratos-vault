"""
Link Prediction Engine — NetworkX graph algorithms
Predicts likely connections between entities using:
  - Jaccard Coefficient
  - Adamic-Adar Index
  - Common Neighbors
  - Preferential Attachment
No external model file needed.
"""
from typing import List, Dict, Tuple
import networkx as nx


def predict_links(
    entities: List[Dict],
    edges: List[Dict],
    top_n: int = 20,
    min_score: float = 0.01
) -> List[Dict]:
    """
    Predict likely missing links between entities.
    Returns list of predicted links sorted by score:
    [
      {
        "source": entity_dict,
        "target": entity_dict,
        "score": 0.45,
        "method": "Adamic-Adar",
        "reason": "3 common neighbors"
      },
      ...
    ]
    """
    if len(entities) < 3:
        return []

    id_map = {e["id"]: e for e in entities}
    G = nx.Graph()

    for e in entities:
        G.add_node(e["id"])
    for ed in edges:
        if ed["source"] in id_map and ed["target"] in id_map:
            G.add_edge(ed["source"], ed["target"])

    existing = {(ed["source"], ed["target"]) for ed in edges}
    existing |= {(ed["target"], ed["source"]) for ed in edges}

    candidates = [
        (u, v) for u in G.nodes() for v in G.nodes()
        if u < v and not G.has_edge(u, v) and (u, v) not in existing
    ]

    if not candidates:
        return []

    # Compute multiple scores
    jaccard  = {(u, v): s for u, v, s in nx.jaccard_coefficient(G, candidates)}
    adamic   = {(u, v): s for u, v, s in nx.adamic_adar_index(G, candidates)}
    pref_att = {(u, v): s for u, v, s in nx.preferential_attachment(G, candidates)}

    # Normalize preferential attachment
    max_pa = max(pref_att.values()) if pref_att else 1
    max_pa = max_pa or 1

    results = []
    for u, v in candidates:
        j_score = jaccard.get((u, v), 0)
        a_score = adamic.get((u, v), 0)
        pa_score = pref_att.get((u, v), 0) / max_pa

        # Common neighbors
        common = list(nx.common_neighbors(G, u, v))
        cn_count = len(common)

        # Combined score
        combined = (j_score * 0.35 + min(a_score / 5, 1.0) * 0.40 + pa_score * 0.25)

        if combined < min_score and cn_count == 0:
            continue

        # Determine best method
        if a_score >= j_score * 5:
            method = "Adamic-Adar"
        elif j_score > 0:
            method = "Jaccard"
        else:
            method = "Preferential Attachment"

        reason = _build_reason(cn_count, j_score, a_score, id_map[u], id_map[v])

        results.append({
            "source":   id_map[u],
            "target":   id_map[v],
            "score":    round(combined, 4),
            "method":   method,
            "reason":   reason,
            "common_neighbors": [id_map[n]["name"] for n in common if n in id_map],
        })

    results.sort(key=lambda x: x["score"], reverse=True)
    return results[:top_n]


def _build_reason(cn: int, j: float, a: float,
                  entity_a: Dict, entity_b: Dict) -> str:
    parts = []
    if cn > 0:
        parts.append(f"{cn} common neighbor(s)")
    if j > 0.3:
        parts.append(f"high Jaccard ({j:.2f})")
    if entity_a.get("type") == entity_b.get("type"):
        parts.append(f"same type ({entity_a['type']})")
    # Check tag overlap
    tags_a = set(entity_a.get("tags", []))
    tags_b = set(entity_b.get("tags", []))
    shared_tags = tags_a & tags_b - {"auto-extracted"}
    if shared_tags:
        parts.append(f"shared tags: {', '.join(list(shared_tags)[:3])}")
    return " | ".join(parts) if parts else "Graph proximity"


def get_graph_stats(entities: List[Dict], edges: List[Dict]) -> Dict:
    """Return graph-level statistics."""
    if not entities:
        return {}

    id_map = {e["id"]: e for e in entities}
    G = nx.Graph()
    for e in entities:
        G.add_node(e["id"])
    for ed in edges:
        if ed["source"] in id_map and ed["target"] in id_map:
            G.add_edge(ed["source"], ed["target"])

    stats = {
        "nodes":      G.number_of_nodes(),
        "edges":      G.number_of_edges(),
        "density":    round(nx.density(G), 4),
        "components": nx.number_connected_components(G),
        "avg_degree": round(sum(d for _, d in G.degree()) / max(G.number_of_nodes(), 1), 2),
    }

    if G.number_of_nodes() > 0:
        try:
            pr = nx.pagerank(G) if G.number_of_edges() > 0 else {}
            if pr:
                top_id = max(pr, key=pr.get)
                stats["most_central"] = id_map.get(top_id, {}).get("name", top_id)
                stats["top_pagerank"] = round(pr[top_id], 4)
        except Exception:
            pass

    return stats
