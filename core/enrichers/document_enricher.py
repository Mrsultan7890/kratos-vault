from pathlib import Path


def run(file_path: str) -> dict:
    path = Path(file_path)
    result = {
        "file": file_path, "found": False,
        "tags": ["document-osint"], "platforms": {}, "screenshots": [], "notes": ""
    }
    if not path.exists():
        result["notes"] = f"File not found: {file_path}"
        return result

    result["found"] = True
    suffix = path.suffix.lower()

    if suffix == ".pdf":
        result["platforms"]["pdf"] = _extract_pdf(path)
    elif suffix in (".docx", ".doc"):
        result["platforms"]["docx"] = _extract_docx(path)
    elif suffix in (".xlsx", ".xls"):
        result["platforms"]["xlsx"] = _extract_xlsx(path)
    else:
        result["platforms"]["text"] = _extract_text(path)

    result["platforms"]["hashes"] = _file_hashes(path)
    result["notes"] = _build_notes(result, path)
    return result


def _extract_pdf(path: Path) -> dict:
    try:
        import pymupdf as fitz
        doc = fitz.open(str(path))
        meta = doc.metadata
        text_pages = []
        for i, page in enumerate(doc):
            if i >= 3:  # first 3 pages only
                break
            text_pages.append(page.get_text()[:500])
        links = []
        for page in doc:
            for link in page.get_links():
                if link.get("uri"):
                    links.append(link["uri"])
        return {
            "found":      True,
            "title":      meta.get("title", ""),
            "author":     meta.get("author", ""),
            "creator":    meta.get("creator", ""),
            "producer":   meta.get("producer", ""),
            "created":    meta.get("creationDate", ""),
            "modified":   meta.get("modDate", ""),
            "pages":      doc.page_count,
            "text_preview": "\n---\n".join(text_pages),
            "links":      list(set(links))[:20],
        }
    except Exception as e:
        return {"found": False, "error": str(e)[:100]}


def _extract_docx(path: Path) -> dict:
    try:
        import docx
        doc = docx.Document(str(path))
        core = doc.core_properties
        text = "\n".join(p.text for p in doc.paragraphs[:20] if p.text.strip())
        return {
            "found":        True,
            "title":        core.title or "",
            "author":       core.author or "",
            "last_modified_by": core.last_modified_by or "",
            "created":      str(core.created or ""),
            "modified":     str(core.modified or ""),
            "revision":     core.revision or 0,
            "text_preview": text[:1000],
        }
    except Exception as e:
        return {"found": False, "error": str(e)[:100]}


def _extract_xlsx(path: Path) -> dict:
    try:
        import openpyxl
        wb = openpyxl.load_workbook(str(path), read_only=True, data_only=True)
        props = wb.properties
        sheets = wb.sheetnames
        return {
            "found":    True,
            "title":    props.title or "",
            "creator":  props.creator or "",
            "modified": str(props.modified or ""),
            "created":  str(props.created or ""),
            "sheets":   sheets,
        }
    except Exception as e:
        return {"found": False, "error": str(e)[:100]}


def _extract_text(path: Path) -> dict:
    try:
        text = path.read_text(errors="ignore")[:2000]
        return {"found": True, "text_preview": text}
    except Exception as e:
        return {"found": False, "error": str(e)[:100]}


def _file_hashes(path: Path) -> dict:
    import hashlib
    try:
        data = path.read_bytes()
        return {
            "found":  True,
            "md5":    hashlib.md5(data).hexdigest(),
            "sha1":   hashlib.sha1(data).hexdigest(),
            "sha256": hashlib.sha256(data).hexdigest(),
            "size":   len(data),
        }
    except Exception as e:
        return {"found": False, "error": str(e)[:100]}


def _build_notes(r: dict, path: Path) -> str:
    lines = [f"=== Document OSINT: {path.name} ===",
             f"  Extension   : {path.suffix}",
             f"  Size        : {path.stat().st_size} bytes"]

    h = r["platforms"].get("hashes", {})
    if h.get("found"):
        lines += ["\n--- File Hashes ---",
                  f"  MD5         : {h.get('md5','')}",
                  f"  SHA1        : {h.get('sha1','')}",
                  f"  SHA256      : {h.get('sha256','')}"]

    for key in ("pdf", "docx", "xlsx"):
        d = r["platforms"].get(key, {})
        if d.get("found"):
            lines += [f"\n--- Metadata ({key.upper()}) ---"]
            for field in ("title","author","creator","producer","last_modified_by",
                          "created","modified","revision","pages","sheets"):
                if d.get(field):
                    lines.append(f"  {field:<20}: {d[field]}")
            if d.get("links"):
                lines.append(f"  Embedded Links ({len(d['links'])}):")
                for lnk in d["links"][:10]:
                    lines.append(f"    - {lnk}")
            if d.get("text_preview"):
                lines += ["\n--- Text Preview (first 3 pages) ---",
                          d["text_preview"][:800]]

    return "\n".join(lines)
