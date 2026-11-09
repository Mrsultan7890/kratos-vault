from pathlib import Path
from core.enrichers._net import new_session

SESSION = new_session({"User-Agent": "Mozilla/5.0"})


def run(file_path: str) -> dict:
    path = Path(file_path)
    result = {
        "file": file_path, "found": False,
        "tags": ["image-osint"], "platforms": {}, "screenshots": [], "notes": ""
    }
    if not path.exists():
        result["notes"] = f"File not found: {file_path}"
        return result

    result["found"] = True
    result["platforms"]["exif"]    = _extract_exif(path)
    result["platforms"]["yolo"]    = _yolo_analyze(path)
    result["platforms"]["tineye"]  = _tineye_search(path)
    result["notes"] = _build_notes(result, path)
    return result


def _extract_exif(path: Path) -> dict:
    try:
        from core.exif_parser import extract_exif
        data = extract_exif(str(path))
        return {"found": bool(data), **data}
    except Exception as e:
        return {"found": False, "error": str(e)[:100]}


def _yolo_analyze(path: Path) -> dict:
    try:
        from core.ml.image_analyzer import analyze_image
        result = analyze_image(path.read_bytes())
        return {"found": True, **result}
    except Exception as e:
        return {"found": False, "error": str(e)[:100]}


def _tineye_search(path: Path) -> dict:
    """TinEye reverse image search. The official API needs a paid key —
    this attempt may fail; the manual URL is always provided."""
    try:
        # TinEye free tier: upload image bytes
        with open(path, "rb") as f:
            r = SESSION.post(
                "https://tineye.com/api/v1/result_json/",
                files={"image": (path.name, f, "image/jpeg")},
                timeout=30
            )
        if r.status_code == 200:
            d = r.json()
            matches = d.get("matches", [])
            return {
                "found":        len(matches) > 0,
                "match_count":  len(matches),
                "matches":      [{"url": m.get("image_url",""), "domain": m.get("domain","")}
                                 for m in matches[:5]],
            }
        return {"found": False,
                "error": f"HTTP {r.status_code} — TinEye API needs a paid key. "
                         f"Manual check: https://tineye.com/search (upload the image)"}
    except Exception as e:
        return {"found": False, "error": str(e)[:100]}


def _build_notes(r: dict, path: Path) -> str:
    lines = [f"=== Image OSINT: {path.name} ===",
             f"  File Size   : {path.stat().st_size} bytes",
             f"  File Path   : {path}"]

    ex = r["platforms"].get("exif", {})
    if ex.get("found"):
        lines.append("\n--- EXIF Metadata ---")
        for k, v in ex.items():
            if k not in ("found", "error") and v:
                lines.append(f"  {k:<20}: {str(v)[:100]}")

    y = r["platforms"].get("yolo", {})
    if y.get("found"):
        lines += ["\n--- YOLO Object Detection ---",
                  f"  Objects     : {y.get('summary','')}",
                  f"  Face Count  : {y.get('face_count',0)}"]
        if y.get("risk_flags"):
            lines.append(f"  Risk Flags  : {', '.join(y.get('risk_flags',[]))}")

    t = r["platforms"].get("tineye", {})
    if t.get("found"):
        lines += [f"\n--- TinEye Reverse Search ---",
                  f"  Matches     : {t.get('match_count',0)}"]
        for m in t.get("matches", []):
            lines.append(f"    - {m.get('domain','')} : {m.get('url','')[:80]}")
    elif t.get("error") or t.get("note"):
        lines += ["\n--- TinEye Reverse Search (unavailable) ---",
                  f"  {t.get('error') or t.get('note')}"]

    return "\n".join(lines)
