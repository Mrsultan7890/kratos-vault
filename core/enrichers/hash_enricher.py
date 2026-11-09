import os
import requests
from core.enrichers._net import new_session

SESSION = new_session({"User-Agent": "Mozilla/5.0"})

VT_API  = "https://www.virustotal.com/api/v3/files/{}"
MB_API  = "https://mb-api.abuse.ch/api/v1/"
# CIRCL hashlookup — free, NO API key ever (run by CERT.lu)
HASHLOOKUP_API = "https://hashlookup.circl.lu/lookup/{alg}/{hash}"


def run(hash_value: str) -> dict:
    hash_value = hash_value.strip().lower()
    result = {
        "hash": hash_value, "found": False,
        "tags": ["hash-osint"], "platforms": {}, "screenshots": [], "notes": ""
    }
    hash_type = _detect_type(hash_value)
    result["hash_type"] = hash_type
    result["tags"].append(hash_type.lower())

    result["platforms"]["hashlookup"] = _hashlookup(hash_value, hash_type)
    result["platforms"]["malwarebazaar"] = _malwarebazaar(hash_value)
    result["platforms"]["virustotal"] = _virustotal(hash_value)
    for p in result["platforms"].values():
        if p.get("found"):
            result["found"] = True

    result["notes"] = _build_notes(result)
    return result


def _detect_type(h: str) -> str:
    if len(h) == 32:  return "MD5"
    if len(h) == 40:  return "SHA1"
    if len(h) == 64:  return "SHA256"
    return "UNKNOWN"


def _hashlookup(hash_value: str, hash_type: str) -> dict:
    """CIRCL hashlookup (keyless) — known-file database from CIRCL + shadowserver.
    Tells you if a hash belongs to a KNOWN file (installer, malware family, etc.)."""
    if hash_type == "UNKNOWN":
        return {"found": False, "note": "Unsupported hash length (use MD5/SHA1/SHA256)"}
    try:
        r = SESSION.get(
            HASHLOOKUP_API.format(alg=hash_type.lower(), hash=hash_value),
            timeout=15
        )
        if r.status_code == 404:
            return {"found": False,
                    "note": "Not in CIRCL known-file database (unknown file)"}
        if r.status_code != 200:
            return {"found": False, "error": f"HTTP {r.status_code}"}
        d = r.json()
        return {
            "found":      True,
            "file_names": d.get("FileName", []),
            "type":       d.get("Typetag", ""),
            "size":       d.get("Size", 0),
            "md5":        d.get("MD5", ""),
            "sha1":       d.get("SHA1", ""),
            "sha256":     d.get("SHA256", ""),
            "source":     d.get("source", []),
            "lookup_url": f"https://hashlookup.circl.lu/lookup/{hash_type.lower()}/{hash_value}",
        }
    except Exception as e:
        return {"found": False, "error": str(e)[:100]}


def _virustotal(hash_value: str) -> dict:
    """VirusTotal lookup — needs a free API key in the VT_API_KEY env var."""
    api_key = os.environ.get("VT_API_KEY", "").strip()
    if not api_key:
        return {"found": False,
                "note": "VirusTotal needs an API key — set VT_API_KEY env var "
                        "(free signup: virustotal.com). Manual check: "
                        f"https://www.virustotal.com/gui/file/{hash_value}"}
    try:
        r = SESSION.get(
            VT_API.format(hash_value),
            headers={"x-apikey": api_key},
            timeout=15
        )
        if r.status_code == 200:
            d = r.json().get("data", {})
            attrs = d.get("attributes", {})
            stats = attrs.get("last_analysis_stats", {})
            return {
                "found":        True,
                "malicious":    stats.get("malicious", 0),
                "suspicious":   stats.get("suspicious", 0),
                "harmless":     stats.get("harmless", 0),
                "undetected":   stats.get("undetected", 0),
                "name":         attrs.get("meaningful_name", ""),
                "type":         attrs.get("type_description", ""),
                "size":         attrs.get("size", 0),
                "first_seen":   attrs.get("first_submission_date", ""),
                "last_seen":    attrs.get("last_submission_date", ""),
                "vt_url":       f"https://www.virustotal.com/gui/file/{hash_value}",
            }
        elif r.status_code == 404:
            return {"found": False, "note": "Not in VirusTotal database"}
        return {"found": False, "error": f"HTTP {r.status_code}"}
    except Exception as e:
        return {"found": False, "error": str(e)[:100]}


def _malwarebazaar(hash_value: str) -> dict:
    """MalwareBazaar — completely free, no key needed."""
    try:
        r = SESSION.post(
            MB_API,
            data={"query": "get_info", "hash": hash_value},
            timeout=15
        )
        d = r.json()
        if d.get("query_status") == "ok":
            info = d.get("data", [{}])[0]
            return {
                "found":        True,
                "file_name":    info.get("file_name", ""),
                "file_type":    info.get("file_type", ""),
                "file_size":    info.get("file_size", 0),
                "mime_type":    info.get("mime_type", ""),
                "first_seen":   info.get("first_seen", ""),
                "last_seen":    info.get("last_seen", ""),
                "tags":         info.get("tags", []),
                "signature":    info.get("signature", ""),
                "reporter":     info.get("reporter", ""),
                "mb_url":       f"https://bazaar.abuse.ch/sample/{hash_value}/",
            }
        return {"found": False, "note": d.get("query_status", "not found")}
    except Exception as e:
        return {"found": False, "error": str(e)[:100]}


def _build_notes(r: dict) -> str:
    lines = [f"=== Hash OSINT: {r['hash']} ===",
             f"  Type        : {r.get('hash_type','')}"]
    hl = r["platforms"].get("hashlookup", {})
    if hl.get("found"):
        names = ", ".join(hl.get("file_names", [])[:5]) or "(no filename)"
        lines += ["\n--- CIRCL Hashlookup (known file) ---",
                  f"  File Name(s): {names}",
                  f"  Type        : {hl.get('type','')}",
                  f"  Size        : {hl.get('size',0)} bytes",
                  f"  Sources     : {', '.join(map(str, hl.get('source', [])))}"]
    elif hl.get("note"):
        lines += ["\n--- CIRCL Hashlookup ---", f"  {hl['note']}"]
    vt = r["platforms"].get("virustotal", {})
    if vt.get("found"):
        mal = vt.get("malicious", 0)
        flag = "🔴 MALICIOUS" if mal > 3 else "🟡 SUSPICIOUS" if mal > 0 else "🟢 CLEAN"
        lines += [f"\n--- VirusTotal --- {flag}",
                  f"  Malicious   : {mal}/{mal + vt.get('harmless',0) + vt.get('undetected',0)}",
                  f"  File Name   : {vt.get('name','')}",
                  f"  File Type   : {vt.get('type','')}",
                  f"  Size        : {vt.get('size',0)} bytes",
                  f"  First Seen  : {vt.get('first_seen','')}",
                  f"  VT URL      : {vt.get('vt_url','')}"]
    elif vt.get("note"):
        lines += [f"\n--- VirusTotal (skipped) ---",
                  f"  {vt['note']}"]
    mb = r["platforms"].get("malwarebazaar", {})
    if mb.get("found"):        lines += ["\n--- MalwareBazaar ---",
                  f"  File Name   : {mb.get('file_name','')}",
                  f"  File Type   : {mb.get('file_type','')}",
                  f"  MIME Type   : {mb.get('mime_type','')}",
                  f"  Signature   : {mb.get('signature','')}",
                  f"  First Seen  : {mb.get('first_seen','')}",
                  f"  Tags        : {', '.join(mb.get('tags',[]))}",
                  f"  MB URL      : {mb.get('mb_url','')}"]
    return "\n".join(lines)
