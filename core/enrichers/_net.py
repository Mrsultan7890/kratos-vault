"""
Shared network configuration for enrichers.

Environment variables (all optional):
  CHROME_PATH        chromium binary       (default /usr/bin/chromium)
  CHROMEDRIVER_PATH  chromedriver binary   (default /usr/bin/chromedriver)
  KV_PROXY           proxy for supported requests-based lookups, e.g.
                     socks5h://127.0.0.1:9050   (Tor)
                     http://127.0.0.1:8080
                     Some integrations and DNS lookups use separate clients and
                     may not honor this proxy. Active URL probes are disabled
                     when a proxy is configured because the destination cannot
                     be validated safely through the proxy.
"""
import os
import requests

CHROME_BINARY = os.environ.get("CHROME_PATH", "/usr/bin/chromium")
CHROMEDRIVER = os.environ.get("CHROMEDRIVER_PATH", "/usr/bin/chromedriver")


def proxy_dict() -> dict | None:
    raw = os.environ.get("KV_PROXY", "").strip()
    if not raw:
        return None
    return {"http": raw, "https": raw}


def new_session(default_headers: dict | None = None) -> requests.Session:
    """requests.Session with KV_PROXY applied (if usable)."""
    s = requests.Session()
    s.trust_env = False
    if default_headers:
        s.headers.update(default_headers)
    proxy = proxy_dict()
    if proxy:
        if proxy["http"].startswith("socks"):
            try:
                import socks  # noqa: F401 — provided by pysocks
            except ImportError as exc:
                raise RuntimeError(
                    "KV_PROXY uses SOCKS, but PySocks is not installed; refusing "
                    "to make an unproxied OSINT request"
                ) from exc
        s.proxies.update(proxy)
    return s
