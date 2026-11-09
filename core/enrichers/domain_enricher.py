import requests
from core.enrichers._net import new_session

SESSION = new_session({"User-Agent": "Mozilla/5.0"})


def run(domain: str) -> dict:
    domain = domain.strip().lower()
    if domain.startswith("www."):
        domain = domain[4:]
    result = {
        "domain": domain, "found": True,
        "tags": ["domain-osint"], "platforms": {}, "screenshots": [], "notes": ""
    }
    result["platforms"]["whois"]  = _whois(domain)
    result["platforms"]["dns"]    = _dns(domain)
    result["platforms"]["crtsh"]  = _crtsh(domain)
    result["platforms"]["urlscan"] = _urlscan(domain)
    result["notes"] = _build_notes(result)
    return result


def _whois(domain: str) -> dict:
    try:
        import whois
        w = whois.whois(domain)
        return {
            "found":        True,
            "registrar":    str(w.registrar or ""),
            "creation_date":str(w.creation_date or ""),
            "expiry_date":  str(w.expiration_date or ""),
            "updated_date": str(w.updated_date or ""),
            "name_servers": [str(n) for n in (w.name_servers or [])],
            "status":       str(w.status or ""),
            "country":      str(w.country or ""),
            "org":          str(w.org or ""),
            "emails":       list({str(e) for e in (w.emails if isinstance(w.emails, list) else [w.emails] if w.emails else [])}),
        }
    except Exception as e:
        return {"found": False, "error": str(e)[:100]}


def _dns(domain: str) -> dict:
    try:
        import dns.resolver
        out = {"found": True}
        for rtype in ["A", "AAAA", "MX", "NS", "TXT", "CNAME"]:
            try:
                out[rtype] = [str(r) for r in dns.resolver.resolve(domain, rtype, lifetime=5)]
            except Exception:
                out[rtype] = []
        return out
    except Exception as e:
        return {"found": False, "error": str(e)[:100]}


def _crtsh(domain: str) -> dict:
    """crt.sh — free SSL certificate transparency log."""
    try:
        r = SESSION.get(
            f"https://crt.sh/?q=%.{domain}&output=json",
            timeout=15
        )
        if r.status_code != 200:
            return {"found": False}
        certs = r.json()
        subdomains = sorted({
            c["name_value"].strip().lower()
            for c in certs
            if domain in c.get("name_value", "")
        })
        issuers = list({c.get("issuer_ca_id") for c in certs})
        return {
            "found":      True,
            "cert_count": len(certs),
            "subdomains": subdomains[:50],
            "first_seen": min((c.get("not_before","") for c in certs), default=""),
            "last_seen":  max((c.get("not_after","") for c in certs), default=""),
        }
    except Exception as e:
        return {"found": False, "error": str(e)[:100]}


def _urlscan(domain: str) -> dict:
    try:
        r = SESSION.get(
            f"https://urlscan.io/api/v1/search/?q=domain:{domain}&size=5",
            timeout=15
        )
        if r.status_code == 200:
            results = r.json().get("results", [])
            return {
                "found":   len(results) > 0,
                "scans":   len(results),
                "latest":  results[0].get("result", "") if results else "",
            }
        return {"found": False}
    except Exception as e:
        return {"found": False, "error": str(e)[:100]}


def _build_notes(r: dict) -> str:
    lines = [f"=== Domain OSINT: {r['domain']} ==="]
    w = r["platforms"].get("whois", {})
    if w.get("found"):
        lines += ["\n--- WHOIS ---",
                  f"  Registrar   : {w.get('registrar','')}",
                  f"  Created     : {w.get('creation_date','')}",
                  f"  Expires     : {w.get('expiry_date','')}",
                  f"  Updated     : {w.get('updated_date','')}",
                  f"  Country     : {w.get('country','')}",
                  f"  Org         : {w.get('org','')}",
                  f"  Emails      : {', '.join(w.get('emails',[]))}",
                  f"  Nameservers : {', '.join(w.get('name_servers',[])[:4])}"]
    d = r["platforms"].get("dns", {})
    if d.get("found"):
        lines += ["\n--- DNS Records ---",
                  f"  A           : {', '.join(d.get('A',[]))}",
                  f"  AAAA        : {', '.join(d.get('AAAA',[]))}",
                  f"  MX          : {', '.join(d.get('MX',[])[:3])}",
                  f"  NS          : {', '.join(d.get('NS',[])[:3])}"]
        if d.get("TXT"):
            for txt in d["TXT"][:3]:
                lines.append(f"  TXT         : {txt[:120]}")
    c = r["platforms"].get("crtsh", {})
    if c.get("found"):
        lines += ["\n--- SSL Certificates (crt.sh) ---",
                  f"  Total Certs : {c.get('cert_count',0)}",
                  f"  First Seen  : {c.get('first_seen','')}",
                  f"  Last Seen   : {c.get('last_seen','')}",
                  f"  Subdomains  ({len(c.get('subdomains',[]))}) :"]
        for sub in c.get("subdomains", [])[:20]:
            lines.append(f"    - {sub}")
    u = r["platforms"].get("urlscan", {})
    if u.get("found"):
        lines += ["\n--- URLScan.io ---",
                  f"  Previous Scans: {u.get('scans',0)}",
                  f"  Latest Result : {u.get('latest','')}"]
    return "\n".join(lines)
