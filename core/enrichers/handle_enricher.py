import time
import requests
from core.enrichers._net import new_session
from core.enrichers._browser import get_stealth_driver, screenshot, safe_quit, next_ua

# Platforms: (url_template, needs_selenium, mobile)
PLATFORMS = {
    "github":    ("https://github.com/{}",              False, False),
    "telegram":  ("https://t.me/{}",                    False, False),
    "youtube":   ("https://www.youtube.com/@{}",        False, False),
    "gitlab":    ("https://gitlab.com/{}",              False, False),
    "medium":    ("https://medium.com/@{}",             False, False),
    "keybase":   ("https://keybase.io/{}",              False, False),
    "pinterest": ("https://www.pinterest.com/{}/",      False, False),
    "twitter":   ("https://twitter.com/{}",             True,  False),
    "instagram": ("https://www.instagram.com/{}/",      True,  False),
    "tiktok":    ("https://www.tiktok.com/@{}",         True,  True),
    "reddit":    ("https://www.reddit.com/user/{}/",    True,  False),
}

NOT_FOUND = [
    "page not found", "user not found", "doesn't exist",
    "this account doesn", "no results", "sorry, this page",
    "profile not found", "isn't available", "404 not found",
    "nobody on reddit goes by",
]

TG_SESSION = new_session({"User-Agent": "TelegramBot (like TwitterBot)"})

_HTTP_SESSION = new_session()  # proxy-aware for _check_http


def run(handle: str) -> dict:
    clean = handle.lstrip("@")
    result = {
        "handle": clean, "found": False,
        "tags": ["handle-osint"], "platforms": {}, "screenshots": [], "notes": ""
    }
    for platform, (url_tpl, needs_selenium, mobile) in PLATFORMS.items():
        url = url_tpl.format(clean)
        if platform == "github":
            r = _check_github(clean)
        elif platform == "telegram":
            r = _check_telegram(url, clean)
        elif needs_selenium:
            r = _check_selenium(platform, url, clean, mobile)
        else:
            r = _check_http(url)

        result["platforms"][platform] = r
        if r.get("found"):
            result["found"] = True
            result["tags"].append(platform)
            if r.get("screenshot"):
                result["screenshots"].append(r["screenshot"])
        time.sleep(0.5)

    result["notes"] = _build_notes(result)
    return result


def _check_http(url: str) -> dict:
    out = {"found": False, "url": url}
    try:
        r = _HTTP_SESSION.get(url, timeout=10, allow_redirects=True,
                              headers={"User-Agent": next_ua()})
        page = r.text.lower()
        if r.status_code == 200 and not any(s in page for s in NOT_FOUND):
            out["found"] = True
    except Exception as e:
        out["error"] = str(e)[:80]
    return out


def _check_telegram(url: str, username: str) -> dict:
    out = {"found": False, "url": url}
    try:
        r = TG_SESSION.get(url, timeout=10)
        if "tgme_page_title" in r.text:
            out["found"] = True
            import re
            m = re.search(r'<div class="tgme_page_title"[^>]*>(.*?)</div>', r.text)
            if m:
                out["name"] = re.sub(r'<[^>]+>', '', m.group(1)).strip()
            m2 = re.search(r'<div class="tgme_page_extra"[^>]*>(.*?)</div>', r.text)
            if m2:
                out["subscribers"] = re.sub(r'<[^>]+>', '', m2.group(1)).strip()
    except Exception as e:
        out["error"] = str(e)[:80]
    return out


def _check_github(username: str) -> dict:
    out = {"found": False, "url": f"https://github.com/{username}"}
    try:
        r = _HTTP_SESSION.get(
            f"https://api.github.com/users/{username}",
            headers={"User-Agent": "KratosVault",
                     "Accept": "application/vnd.github.v3+json"},
            timeout=10
        )
        if r.status_code == 200:
            d = r.json()
            out.update({
                "found":     True,
                "name":      d.get("name", ""),
                "bio":       d.get("bio", ""),
                "location":  d.get("location", ""),
                "email":     d.get("email", ""),
                "blog":      d.get("blog", ""),
                "repos":     d.get("public_repos", 0),
                "followers": d.get("followers", 0),
                "created":   d.get("created_at", ""),
                "avatar":    d.get("avatar_url", ""),
            })
        elif r.status_code == 404:
            out["error"] = "User not found"
    except Exception as e:
        out["error"] = str(e)[:80]
    return out


def _check_selenium(platform: str, url: str, username: str, mobile: bool) -> dict:
    out = {"found": False, "url": url}
    driver = None
    try:
        driver = get_stealth_driver(mobile=mobile)
        driver.get(url)
        time.sleep(4)
        page = driver.page_source.lower()
        if not any(s in page for s in NOT_FOUND):
            out["found"] = True
            ss = screenshot(driver, f"handle_{platform}_{username}.png")
            if ss:
                out["screenshot"] = ss
        else:
            out["error"] = "Profile not found"
    except Exception as e:
        out["error"] = str(e)[:80]
    finally:
        safe_quit(driver)
    return out


def _build_notes(r: dict) -> str:
    lines = [f"=== Handle OSINT: @{r['handle']} ==="]
    found_on  = [p for p, d in r["platforms"].items() if d.get("found")]
    not_found = [p for p, d in r["platforms"].items() if not d.get("found")]
    lines.append(f"\n  Found on  ({len(found_on)}): {', '.join(found_on) or 'none'}")
    lines.append(f"  Not found ({len(not_found)}): {', '.join(not_found)}")
    lines.append("\n--- Details ---")
    for p, d in r["platforms"].items():
        if d.get("found"):
            lines.append(f"  ✅ {p:<12}: {d.get('url', '')}")
            for field in ("name", "bio", "repos", "followers", "subscribers", "location"):
                if d.get(field):
                    lines.append(f"     {field:<10}: {d[field]}")
            if d.get("screenshot"):
                lines.append(f"     screenshot: {d['screenshot']}")
    return "\n".join(lines)
