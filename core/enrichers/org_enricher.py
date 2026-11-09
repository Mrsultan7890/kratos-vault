import os
import requests
from core.enrichers._net import new_session

SESSION = new_session({"User-Agent": "Mozilla/5.0"})


def run(org_name: str) -> dict:
    result = {
        "org": org_name, "found": False,
        "tags": ["org-osint"], "platforms": {}, "screenshots": [], "notes": ""
    }
    result["platforms"]["wikidata"]      = _wikidata(org_name)
    result["platforms"]["opencorporates"] = _opencorporates(org_name)
    result["platforms"]["dorks"]          = _generate_dorks(org_name)

    for p in result["platforms"].values():
        if p.get("found"):
            result["found"] = True

    result["notes"] = _build_notes(result)
    return result


def _wikidata(org_name: str) -> dict:
    """Wikidata search (keyless) — official Wikimedia knowledge base.
    Finds the org's canonical record, type and description."""
    try:
        r = SESSION.get(
            "https://www.wikidata.org/w/api.php",
            params={"action": "wbsearchentities", "search": org_name,
                    "language": "en", "format": "json", "limit": 5},
            timeout=15
        )
        if r.status_code != 200:
            return {"found": False, "error": f"HTTP {r.status_code}"}
        matches = r.json().get("search", [])
        entities = [{
            "id":          m.get("id", ""),
            "label":       m.get("label", ""),
            "description": m.get("description", ""),
            "url":         m.get("concepturi", f"https://www.wikidata.org/wiki/{m.get('id','')}"),
        } for m in matches]
        return {"found": bool(entities), "entities": entities}
    except Exception as e:
        return {"found": False, "error": str(e)[:100]}


def _opencorporates(org_name: str) -> dict:
    try:
        params = {"q": org_name, "format": "json", "per_page": 5}
        token = os.environ.get("OPENCORPORATES_API_TOKEN", "").strip()
        if token:
            params["api_token"] = token
        r = SESSION.get(
            "https://api.opencorporates.com/v0.4/companies/search",
            params=params,
            timeout=15
        )
        if r.status_code in (401, 403):
            return {"found": False,
                    "note": "OpenCorporates search needs an API token — set "
                            "OPENCORPORATES_API_TOKEN env var. Manual check: "
                            f"https://opencorporates.com/companies?q={org_name}"}
        if r.status_code != 200:
            return {"found": False, "error": f"HTTP {r.status_code}"}
        data = r.json()
        companies = data.get("results", {}).get("companies", [])
        if not companies:
            return {"found": False, "note": "No companies found"}
        results = []
        for c in companies[:5]:
            co = c.get("company", {})
            results.append({
                "name":           co.get("name", ""),
                "company_number": co.get("company_number", ""),
                "jurisdiction":   co.get("jurisdiction_code", ""),
                "status":         co.get("current_status", ""),
                "incorporation":  co.get("incorporation_date", ""),
                "registered_addr":co.get("registered_address_in_full", ""),
                "url":            co.get("opencorporates_url", ""),
            })
        return {"found": True, "companies": results}
    except Exception as e:
        return {"found": False, "error": str(e)[:100]}


def _generate_dorks(org_name: str) -> dict:
    q = org_name.replace(" ", "+")
    dorks = {
        "linkedin":   f"https://www.google.com/search?q=site:linkedin.com+\"{org_name}\"",
        "employees":  f"https://www.google.com/search?q=site:linkedin.com/in+\"{org_name}\"",
        "emails":     f"https://www.google.com/search?q=\"@{org_name.lower().replace(' ','')}.com\"",
        "documents":  f"https://www.google.com/search?q=site:{org_name.lower().replace(' ','')}.com+filetype:pdf",
        "pastebin":   f"https://www.google.com/search?q=site:pastebin.com+\"{org_name}\"",
        "github":     f"https://github.com/search?q={q}&type=repositories",
        "twitter":    f"https://twitter.com/search?q={q}",
    }
    return {"found": True, "dorks": dorks}


def _build_notes(r: dict) -> str:
    lines = [f"=== Organization OSINT: {r['org']} ==="]
    wd = r["platforms"].get("wikidata", {})
    if wd.get("found"):
        lines.append(f"\n--- Wikidata ({len(wd.get('entities',[]))} matches) ---")
        for m in wd.get("entities", [])[:5]:
            lines.append(f"\n  Entity      : {m['label']} ({m['id']})")
            if m.get("description"):
                lines.append(f"  Description : {m['description']}")
            lines.append(f"  URL         : {m['url']}")
    oc = r["platforms"].get("opencorporates", {})
    if oc.get("found"):
        lines.append(f"\n--- OpenCorporates ({len(oc.get('companies',[]))} results) ---")
        for co in oc.get("companies", []):
            lines += [f"\n  Company     : {co.get('name','')}",
                      f"  Number      : {co.get('company_number','')}",
                      f"  Jurisdiction: {co.get('jurisdiction','')}",
                      f"  Status      : {co.get('status','')}",
                      f"  Incorporated: {co.get('incorporation','')}",
                      f"  Address     : {co.get('registered_addr','')}",
                      f"  URL         : {co.get('url','')}"]
    elif oc.get("note"):
        lines += [f"\n--- OpenCorporates (skipped) ---", f"  {oc['note']}"]
    d = r["platforms"].get("dorks", {})
    if d.get("found"):
        lines.append("\n--- Google Dorks (open in browser) ---")
        for name, url in d.get("dorks", {}).items():
            lines.append(f"  {name:<12}: {url}")
    return "\n".join(lines)
