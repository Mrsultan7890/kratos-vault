import os
import socket
import requests
from core.enrichers._net import new_session

SESSION = new_session({"User-Agent": "Mozilla/5.0"})


def run(ip: str) -> dict:
    result = {
        "ip": ip, "found": False,
        "tags": ["ip-osint"], "platforms": {}, "screenshots": [], "notes": ""
    }
    result["platforms"]["ipapi"]   = _ipapi(ip)
    result["platforms"]["rdns"]    = _reverse_dns(ip)
    result["platforms"]["dnsbl"]   = _dnsbl_check(ip)
    result["platforms"]["abuseipdb"] = _abuseipdb(ip)
    if result["platforms"]["ipapi"].get("found"):
        result["found"] = True
        result["tags"] += result["platforms"]["ipapi"].get("tags", [])
    if result["platforms"]["dnsbl"].get("listed"):
        result["found"] = True
        result["tags"].append("blacklisted")
    result["notes"] = _build_notes(result)
    return result


def _ipapi(ip: str) -> dict:
    try:
        r = SESSION.get(f"http://ip-api.com/json/{ip}?fields=66846719", timeout=10)
        d = r.json()
        if d.get("status") == "success":
            tags = [f"country-{d.get('countryCode','').lower()}",
                    f"isp-{d.get('isp','').lower().replace(' ','-')[:30]}"]
            if d.get("proxy"):  tags.append("proxy")
            if d.get("hosting"): tags.append("hosting")
            if d.get("mobile"):  tags.append("mobile")
            return {
                "found":        True,
                "country":      d.get("country", ""),
                "country_code": d.get("countryCode", ""),
                "region":       d.get("regionName", ""),
                "city":         d.get("city", ""),
                "zip":          d.get("zip", ""),
                "lat":          d.get("lat"),
                "lon":          d.get("lon"),
                "timezone":     d.get("timezone", ""),
                "isp":          d.get("isp", ""),
                "org":          d.get("org", ""),
                "asn":          d.get("as", ""),
                "is_proxy":     d.get("proxy", False),
                "is_hosting":   d.get("hosting", False),
                "is_mobile":    d.get("mobile", False),
                "maps_url":     f"https://www.google.com/maps?q={d.get('lat')},{d.get('lon')}",
                "tags":         [t for t in tags if t],
            }
        return {"found": False, "error": d.get("message", "failed")}
    except Exception as e:
        return {"found": False, "error": str(e)[:100]}


def _reverse_dns(ip: str) -> dict:
    try:
        hostname = socket.gethostbyaddr(ip)[0]
        return {"found": True, "hostname": hostname}
    except Exception:
        return {"found": False}


_DNSBL_ZONES = {
    "zen.spamhaus.org": {
        "127.0.0.2": "SBL — spam / malicious",
        "127.0.0.3": "XBL — exploited host",
        "127.0.0.4": "SBL — spamdrop",
        "127.0.0.10": "PBL — ISP policy (should not send mail)",
        "127.0.0.11": "PBL — ISP policy (mobile/dynamic)",
    },
    "dnsbl.dronebl.org": {
        "127.0.0.3":  "DroneBL — poller/botnet",
        "127.0.0.5":  "DroneBL — drone",
        "127.0.0.6":  "DroneBL — scanner",
        "127.0.0.7":  "DroneBL — malicious host",
        "127.0.0.8":  "DroneBL —spam source",
        "127.0.0.10": "DroneBL — proxy",
        "127.0.0.13": "DroneBL — brute force",
        "127.0.0.14": "DroneBL — open proxy",
        "127.0.0.15": "DroneBL — open relay",
        "127.0.0.16": "DroneBL — crawler",
        "127.0.0.17": "DroneBL — botnet controller",
    },
}


def _is_private_ip(ip: str) -> bool:
    try:
        parts = [int(p) for p in ip.split(".")]
        if len(parts) != 4:
            return True
        if parts[0] in (10, 127) or (parts[0] == 192 and parts[1] == 168):
            return True
        if parts[0] == 172 and 16 <= parts[1] <= 31:
            return True
        if parts[0] == 169 and parts[1] == 254:
            return True
        return False
    except ValueError:
        return True


def _dnsbl_check(ip: str) -> dict:
    """Keyless IP reputation — DNS blocklist lookups (Spamhaus ZEN + DroneBL).
    Every listed IP means the address has been seen in abuse/botnet/spam activity."""
    if _is_private_ip(ip):
        return {"listed": False, "note": "Private/reserved IP — blocklist lookup skipped"}
    reversed_ip = ".".join(reversed(ip.split(".")))
    listings, zones_checked = [], 0
    for zone, codes in _DNSBL_ZONES.items():
        query = f"{reversed_ip}.{zone}"
        try:
            import dns.resolver
            answers = dns.resolver.resolve(query, "A", lifetime=6)
            zones_checked += 1
            for a in answers:
                code = str(a)
                if code.startswith("127.255.255"):
                    continue  # Spamhaus query-error sentinel, not a listing
                reason = codes.get(code, f"Listed (code {code})")
                listings.append(f"{zone}: {reason}")
        except Exception:
            zones_checked += 1  # NXDOMAIN / timeout = not listed on this zone
    out = {"listed": bool(listings), "zones": zones_checked}
    if listings:
        out["listings"] = listings
    return out


def _abuseipdb(ip: str) -> dict:
    """AbuseIPDB — needs a free API key in the ABUSEIPDB_API_KEY env var."""
    api_key = os.environ.get("ABUSEIPDB_API_KEY", "").strip()
    if not api_key:
        return {"found": False,
                "note": "AbuseIPDB needs an API key — set ABUSEIPDB_API_KEY env var "
                        "(free signup: abuseipdb.com). Manual check: "
                        f"https://www.abuseipdb.com/check/{ip}"}
    try:
        r = SESSION.get(
            f"https://api.abuseipdb.com/api/v2/check",
            params={"ipAddress": ip, "maxAgeInDays": 90},
            headers={"Key": api_key, "Accept": "application/json"},
            timeout=10
        )
        if r.status_code == 200:
            d = r.json().get("data", {})
            return {
                "found":          True,
                "abuse_score":    d.get("abuseConfidenceScore", 0),
                "total_reports":  d.get("totalReports", 0),
                "last_reported":  d.get("lastReportedAt", ""),
                "is_whitelisted": d.get("isWhitelisted", False),
            }
        return {"found": False}
    except Exception:
        return {"found": False}


def _build_notes(r: dict) -> str:
    lines = [f"=== IP OSINT: {r['ip']} ==="]
    g = r["platforms"].get("ipapi", {})
    if g.get("found"):
        lines += ["\n--- Geolocation (ip-api.com) ---",
                  f"  Country     : {g.get('country','')} ({g.get('country_code','')})",
                  f"  Region/City : {g.get('region','')} / {g.get('city','')}",
                  f"  ZIP         : {g.get('zip','')}",
                  f"  Coordinates : {g.get('lat')}, {g.get('lon')}",
                  f"  Timezone    : {g.get('timezone','')}",
                  f"  ISP         : {g.get('isp','')}",
                  f"  Org         : {g.get('org','')}",
                  f"  ASN         : {g.get('asn','')}",
                  f"  Proxy       : {'YES' if g.get('is_proxy') else 'NO'}",
                  f"  Hosting     : {'YES' if g.get('is_hosting') else 'NO'}",
                  f"  Maps        : {g.get('maps_url','')}"]
    rd = r["platforms"].get("rdns", {})
    if rd.get("found"):
        lines += ["\n--- Reverse DNS ---", f"  Hostname    : {rd.get('hostname','')}"]
    db_ = r["platforms"].get("dnsbl", {})
    if db_.get("listed"):
        lines += ["\n--- DNS Blocklists — 🔴 LISTED ---"]
        for l in db_.get("listings", []):
            lines.append(f"  ✗ {l}")
    elif db_.get("note"):
        lines += ["\n--- DNS Blocklists ---", f"  {db_['note']}"]
    elif "zones" in db_:
        lines += ["\n--- DNS Blocklists — 🟢 CLEAN ---",
                  f"  Checked {db_['zones']} zone(s): Spamhaus ZEN, DroneBL"]
    ab = r["platforms"].get("abuseipdb", {})
    if ab.get("found") and ab.get("total_reports", 0) > 0:
        lines += ["\n--- AbuseIPDB ---",
                  f"  Abuse Score : {ab.get('abuse_score',0)}%",
                  f"  Reports     : {ab.get('total_reports',0)}",
                  f"  Last Report : {ab.get('last_reported','')}"]
    elif ab.get("note"):
        lines += ["\n--- AbuseIPDB (skipped) ---", f"  {ab['note']}"]
    return "\n".join(lines)
