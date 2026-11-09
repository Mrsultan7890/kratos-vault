"""
Case Report Generator — self-contained HTML report + PDF export (via Qt).

HTML opens in any browser; PDF uses QTextDocument's rich-text engine so no
extra dependency (weasyprint/latex) is needed.
"""
import html as _html
from datetime import datetime
from pathlib import Path

from core.enrichment import get_all_status, should_enrich
from ui.theme import STATUS_COLORS, PRIORITY_COLORS


def _esc(s) -> str:
    return _html.escape(str(s if s is not None else ""))


def _risk_note(conf: int) -> str:
    if conf >= 80:
        return "high"
    if conf >= 50:
        return "medium"
    return "low"


def build_case_report(db, case_id: str) -> str:
    """Return the full HTML document for a case report."""
    case = db.get_case(case_id)
    entities = db.list_entities(case_id)
    edges = db.list_edges(case_id)
    events = db.list_events(case_id)
    notes = db.list_notes(case_id)
    media_meta = db.list_media(case_id)
    audit = db.list_audit(case_id)
    status = get_all_status()

    sc = STATUS_COLORS.get(case["status"], "#888")
    pc = PRIORITY_COLORS.get(case["priority"], "#888")
    now = datetime.now().strftime("%Y-%m-%d %H:%M")

    # ── Entity table ──────────────────────────────────────────────────
    ent_rows = []
    for e in entities:
        st = status.get(e["id"], {}).get("status", "pending")
        badge = {"done": "✅", "failed": "❌", "running": "⏳", "pending": "⏸"}.get(st, "⏸")
        tags = ", ".join(f"<code>{_esc(t)}</code>" for t in e["tags"][:8])
        ent_rows.append(f"""
        <tr>
          <td><b>{_esc(e['name'] or e['value'])}</b><br>
              <span class="muted">{_esc(e['value'])}</span></td>
          <td>{_esc(e['type'])}</td>
          <td>{tags}</td>
          <td>{e['confidence']}%</td>
          <td>{_esc(e.get('source', ''))}</td>
          <td>{badge} {st}</td>
        </tr>""")

    # ── Connections ───────────────────────────────────────────────────
    names = {e["id"]: (e["name"] or e["value"], e["type"]) for e in entities}
    edge_rows = []
    for ed in edges:
        s = names.get(ed["source"], ("?", ""))
        t = names.get(ed["target"], ("?", ""))
        edge_rows.append(f"<tr><td>{_esc(s[0])} <span class='muted'>({_esc(s[1])})</span></td>"
                         f"<td>{_esc(ed.get('label', 'linked'))}</td>"
                         f"<td>{_esc(t[0])} <span class='muted'>({_esc(t[1])})</span></td></tr>")
    if not edge_rows:
        edge_rows = "<tr><td colspan='3' class='muted'>No connections mapped yet.</td></tr>"

    # ── Media table ───────────────────────────────────────────────────
    media_rows = []
    for m in media_meta:
        exif = m.get("exif", {})
        gps = (f"{exif['gps_latitude']:.5f}, {exif['gps_longitude']:.5f}"
               if "gps_latitude" in exif else "—")
        media_rows.append(f"""
        <tr><td>{_esc(m['name'])}</td><td>{_esc(m.get('mime_type', ''))}</td>
        <td>{m['size'] / 1024:.1f} KB</td>
        <td><code>{m['hash_sha256'][:32]}…</code></td><td>{gps}</td></tr>""")
    if not media_rows:
        media_rows = "<tr><td colspan='5' class='muted'>No media attached.</td></tr>"

    # ── Notes ─────────────────────────────────────────────────────────
    notes_html = ""
    for n in notes:
        notes_html += f"""
        <div class="note">
          <h3>📝 {_esc(n['title'])}</h3>
          <pre>{_esc(n['content'])}</pre>
        </div>"""
    if not notes_html:
        notes_html = "<p class='muted'>No notes recorded.</p>"

    # ── Timeline (latest first, cap 100) ─────────────────────────────
    tl_rows = []
    for ev in events[:100]:
        tl_rows.append(f"<tr><td>{ev['created'][:16].replace('T', ' ')}</td>"
                       f"<td>{_esc(ev['title'])}</td>"
                       f"<td class='muted'>{_esc(ev.get('detail', ''))}</td></tr>")

    # ── Chain of custody summary ──────────────────────────────────────
    ok, broken = db.verify_audit_chain(case_id)
    chain = ("✅ verified intact" if ok
             else f"🔴 BROKEN at entry {broken} — treat evidence as compromised")
    audit_rows = []
    for a in audit[-50:]:
        audit_rows.append(f"<tr><td>{a['ts'][:19].replace('T', ' ')}</td>"
                          f"<td>{_esc(a['action'])}</td>"
                          f"<td class='muted'>{_esc(a['details'])}</td></tr>")

    enrich_done = sum(1 for e in entities
                      if status.get(e["id"], {}).get("status") == "done")
    enrichable = [e for e in entities if should_enrich(e)]

    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8">
<title>Case Report — {_esc(case['name'])}</title>
<style>
  body {{ font-family: -apple-system, 'Segoe UI', sans-serif; margin: 40px auto;
         max-width: 900px; color: #1a1a2e; line-height: 1.5; }}
  h1 {{ border-bottom: 3px solid #1565c0; padding-bottom: 8px; }}
  h2 {{ color: #1565c0; margin-top: 32px; border-bottom: 1px solid #ddd; padding-bottom: 4px; }}
  table {{ border-collapse: collapse; width: 100%; margin: 12px 0; font-size: 13px; }}
  th {{ background: #0d2b4e; color: #fff; text-align: left; padding: 7px 10px; }}
  td {{ border-bottom: 1px solid #e3e8ef; padding: 7px 10px; vertical-align: top; }}
  tr:nth-child(even) td {{ background: #f6f8fa; }}
  code {{ background: #eef1f5; padding: 1px 5px; border-radius: 3px; font-size: 12px; }}
  .muted {{ color: #6b7280; font-size: 12px; }}
  .meta {{ background: #f0f7ff; border: 1px solid #cfe3ff; border-radius: 8px;
          padding: 14px 18px; margin: 16px 0; }}
  .note {{ background: #fbfbfd; border: 1px solid #e3e8ef; border-radius: 8px;
          padding: 4px 18px; margin: 12px 0; }}
  pre {{ white-space: pre-wrap; font-family: 'Consolas', monospace; font-size: 12px; }}
  .badge-ok {{ color: #15803d; font-weight: 700; }}
  .badge-bad {{ color: #b91c1c; font-weight: 700; }}
  .footer {{ margin-top: 40px; color: #9ca3af; font-size: 11px;
            border-top: 1px solid #ddd; padding-top: 8px; }}
</style></head><body>

<h1>⬡ Case Report — {_esc(case['name'])}</h1>
<div class="meta">
  <b>Status:</b> <span style="color:{sc}">{_esc(case['status'])}</span> &nbsp;·&nbsp;
  <b>Priority:</b> <span style="color:{pc}">{_esc(case['priority'])}</span> &nbsp;·&nbsp;
  <b>Generated:</b> {now}
  <br><b>Description:</b> {_esc(case.get('description', '')) or '<span class="muted">none</span>'}
</div>

<h2>📌 Overview</h2>
<table>
  <tr><th>Entities</th><th>Connections</th><th>Media</th><th>Events</th><th>Notes</th></tr>
  <tr><td>{len(entities)}</td><td>{len(edges)}</td><td>{len(media_meta)}</td>
      <td>{len(events)}</td><td>{len(notes)}</td></tr>
</table>
<p>OSINT enrichment coverage: <b>{enrich_done}/{len(enrichable)}</b> entities enriched.</p>

<h2>🔵 Entities ({len(entities)})</h2>
<table>
  <tr><th>Name / Value</th><th>Type</th><th>Tags</th><th>Confidence</th><th>Source</th><th>Enrichment</th></tr>
  {''.join(ent_rows) or '<tr><td colspan="6" class="muted">No entities.</td></tr>'}
</table>

<h2>🕸 Connections ({len(edges)})</h2>
<table>
  <tr><th>Source</th><th>Relation</th><th>Target</th></tr>
  {''.join(edge_rows)}
</table>

<h2>🖼 Media &amp; Metadata ({len(media_meta)})</h2>
<table>
  <tr><th>Filename</th><th>Type</th><th>Size</th><th>SHA-256</th><th>GPS</th></tr>
  {''.join(media_rows)}
</table>

<h2>📝 Notes</h2>
{notes_html}

<h2>⏱ Timeline (latest {min(len(events), 100)} of {len(events)})</h2>
<table>
  <tr><th>Time</th><th>Event</th><th>Detail</th></tr>
  {''.join(tl_rows) or '<tr><td colspan="3" class="muted">No events.</td></tr>'}
</table>

<h2>🛡 Chain of Custody — {'<span class="badge-ok">INTEGRITY OK</span>' if ok else '<span class="badge-bad">TAMPERED</span>'}</h2>
<p>Audit chain: <b>{chain}</b> ({len(audit)} entries)</p>
<table>
  <tr><th>Time</th><th>Action</th><th>Details</th></tr>
  {''.join(audit_rows)}
</table>

<div class="footer">
  Generated by Kratos Vault v2.1 — OSINT Case Manager · {_now_stamp()} ·
  Case ID: {_esc(case_id)}
</div>
</body></html>"""


def _now_stamp() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M")


def save_html_report(db, case_id: str, path: str) -> str:
    html = build_case_report(db, case_id)
    Path(path).write_text(html, encoding="utf-8")
    return path


def save_pdf_report(db, case_id: str, path: str) -> str:
    """Render the HTML report to PDF with Qt's rich-text engine."""
    from PyQt6.QtGui import (QPdfWriter, QPageLayout, QPageSize,
                             QTextDocument, QFont)
    from PyQt6.QtCore import QMarginsF
    html = build_case_report(db, case_id)

    writer = QPdfWriter(path)
    layout = QPageLayout(QPageSize(QPageSize.PageSizeId.A4),
                         QPageLayout.Orientation.Portrait,
                         QMarginsF(15, 15, 15, 15), QPageLayout.Unit.Millimeter)
    writer.setPageLayout(layout)
    doc = QTextDocument()
    doc.setDocumentMargin(0)
    doc.setHtml(html)
    doc.setDefaultFont(QFont("Segoe UI", 9))
    doc.print(writer)
    return path
