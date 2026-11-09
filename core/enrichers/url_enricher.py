import http.client
import ipaddress
import socket
import ssl
from urllib.parse import urlparse, urlunsplit

from core.enrichers._net import new_session
from core.enrichers._net import proxy_dict
from pathlib import Path

SCREENSHOT_DIR = Path.home() / ".kratos_vault" / "screenshots"
SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
SESSION = new_session({"User-Agent": "Mozilla/5.0"})


def run(url: str) -> dict:
    result = {
        "url": url, "found": True,
        "tags": ["url-osint"], "platforms": {}, "screenshots": [], "notes": ""
    }
    result["platforms"]["whois"]   = _whois(url)
    result["platforms"]["headers"] = _http_headers(url)
    result["platforms"]["urlscan"] = _urlscan(url)
    result["platforms"]["dns"]     = _dns(url)
    result["notes"] = _build_notes(result)
    return result


def _whois(url: str) -> dict:
    try:
        import whois
        domain = _extract_domain(url)
        w = whois.whois(domain)
        return {
            "found": True,
            "registrar":    str(w.registrar or ""),
            "creation_date":str(w.creation_date or ""),
            "expiry_date":  str(w.expiration_date or ""),
            "name_servers": [str(n) for n in (w.name_servers or [])],
            "country":      str(w.country or ""),
            "org":          str(w.org or ""),
            "emails":       [str(e) for e in (w.emails if isinstance(w.emails, list) else [w.emails] if w.emails else [])],
        }
    except Exception as e:
        return {"found": False, "error": str(e)[:100]}


def _http_headers(url: str) -> dict:
    conn = None
    try:
        if proxy_dict():
            return {
                "found": False,
                "error": "Active URL checks are disabled with a proxy because its destination "
                         "cannot be validated safely",
            }
        parsed, address, port = _validate_public_url(url)
        conn = http.client.HTTPConnection(parsed.hostname, port, timeout=10)
        sock = socket.create_connection((str(address), port), timeout=10)
        if parsed.scheme == "https":
            sock = ssl.create_default_context().wrap_socket(
                sock, server_hostname=parsed.hostname)
        conn.sock = sock
        path = urlunsplit(("", "", parsed.path or "/", parsed.query, ""))
        host_header = f"[{parsed.hostname}]" if ":" in parsed.hostname else parsed.hostname
        if port != (443 if parsed.scheme == "https" else 80):
            host_header = f"{host_header}:{port}"
        conn.request("HEAD", path, headers={
            "Host": host_header,
            "User-Agent": "Mozilla/5.0",
            "Connection": "close",
        })
        response = conn.getresponse()
        if 300 <= response.status < 400:
            return {
                "found": False,
                "status_code": response.status,
                "error": "Redirects are not followed to prevent requests to private/internal hosts",
            }
        h = dict(response.getheaders())
        return {
            "found":        True,
            "status_code":  response.status,
            "final_url":    url,
            "server":       h.get("Server", ""),
            "x_powered_by": h.get("X-Powered-By", ""),
            "content_type": h.get("Content-Type", ""),
            "x_frame":      h.get("X-Frame-Options", ""),
            "csp":          h.get("Content-Security-Policy", "")[:200] if h.get("Content-Security-Policy") else "",
        }
    except Exception as e:
        return {"found": False, "error": str(e)[:100]}
    finally:
        if conn:
            conn.close()


def _validate_public_url(url: str):
    parsed = urlparse(url if "://" in url else "https://" + url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise ValueError("Only absolute HTTP(S) URLs with a hostname can be checked")
    if parsed.username or parsed.password:
        raise ValueError("URLs containing embedded credentials are not allowed")

    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    try:
        addresses = [ipaddress.ip_address(parsed.hostname)]
    except ValueError:
        try:
            addresses = [
                ipaddress.ip_address(info[4][0])
                for info in socket.getaddrinfo(parsed.hostname, port,
                                               type=socket.SOCK_STREAM)
            ]
        except (OSError, ValueError) as exc:
            raise ValueError("URL host did not resolve to a public address") from exc
    if not addresses or any(not address.is_global for address in addresses):
        raise ValueError("Requests to private, local, or reserved IP addresses are blocked")
    return parsed, addresses[0], port


def _urlscan(url: str) -> dict:
    """urlscan.io SEARCH (keyless) — look up existing public scans for the URL's
    domain. (Submitting new scans needs an API key AND leaks the target URL to
    a third party — avoid during investigations.)"""
    try:
        domain = _extract_domain(url)
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


def _dns(url: str) -> dict:
    try:
        import dns.resolver
        domain = _extract_domain(url)
        out = {"found": True, "domain": domain}
        for rtype in ["A", "MX", "NS", "TXT"]:
            try:
                answers = dns.resolver.resolve(domain, rtype, lifetime=5)
                out[rtype] = [str(r) for r in answers]
            except Exception:
                out[rtype] = []
        return out
    except Exception as e:
        return {"found": False, "error": str(e)[:100]}


def _extract_domain(url: str) -> str:
    from urllib.parse import urlparse
    p = urlparse(url if "://" in url else "https://" + url)
    return p.netloc or p.path.split("/")[0]


def _build_notes(r: dict) -> str:
    lines = [f"=== URL OSINT: {r['url']} ==="]
    w = r["platforms"].get("whois", {})
    if w.get("found"):
        lines += ["\n--- WHOIS ---",
                  f"  Registrar   : {w.get('registrar','')}",
                  f"  Created     : {w.get('creation_date','')}",
                  f"  Expires     : {w.get('expiry_date','')}",
                  f"  Country     : {w.get('country','')}",
                  f"  Org         : {w.get('org','')}",
                  f"  Nameservers : {', '.join(w.get('name_servers',[])[:3])}",
                  f"  Emails      : {', '.join(w.get('emails',[]))}"]
    h = r["platforms"].get("headers", {})
    if h.get("found"):
        lines += ["\n--- HTTP Headers ---",
                  f"  Status      : {h.get('status_code','')}",
                  f"  Final URL   : {h.get('final_url','')}",
                  f"  Server      : {h.get('server','')}",
                  f"  Powered By  : {h.get('x_powered_by','')}",
                  f"  Content-Type: {h.get('content_type','')}"]
    d = r["platforms"].get("dns", {})
    if d.get("found"):
        lines += ["\n--- DNS ---",
                  f"  A Records   : {', '.join(d.get('A',[]))}",
                  f"  MX Records  : {', '.join(d.get('MX',[])[:3])}",
                  f"  NS Records  : {', '.join(d.get('NS',[])[:3])}"]
        if d.get("TXT"):
            lines.append(f"  TXT Records : {d['TXT'][0][:100]}")
    u = r["platforms"].get("urlscan", {})
    if u.get("found"):
        lines += ["\n--- URLScan.io (existing public scans) ---",
                  f"  Previous Scans: {u.get('scans',0)}",
                  f"  Latest Result : {u.get('latest','')}"]
    return "\n".join(lines)
