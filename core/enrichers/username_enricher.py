import time
import requests
from pathlib import Path
from core.enrichers._net import new_session
from core.enrichers._browser import get_stealth_driver, screenshot, safe_quit, SCREENSHOT_DIR

SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)

TG_SESSION = new_session({"User-Agent": "TelegramBot (like TwitterBot)"})

REDDIT_SESSION = new_session({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "application/json",
})


def run(username: str, tags: list = None) -> dict:
    tags = [t.lower() for t in (tags or [])]
    clean = username.lstrip("@")
    result = {
        "username": clean, "found": False,
        "tags": ["username-osint"], "platforms": {}, "screenshots": []
    }

    platforms = _detect_platforms(tags)

    for platform in platforms:
        if platform == "instagram":
            r = _scrape_instagram(clean)
        elif platform == "telegram":
            r = _scrape_telegram_http(clean)
        elif platform == "reddit":
            r = _scrape_reddit(clean)
        elif platform == "twitter":
            r = _scrape_twitter(clean)
        elif platform == "github":
            r = _scrape_github(clean)
        elif platform == "tiktok":
            r = _scrape_tiktok(clean)
        else:
            continue

        result["platforms"][platform] = r
        if r.get("found"):
            result["found"] = True
            result["tags"].append(platform)
            if r.get("screenshot"):
                result["screenshots"].append(r["screenshot"])

    result["notes"] = _build_notes(clean, result["platforms"])
    return result


def _detect_platforms(tags: list) -> list:
    known = ["instagram", "telegram", "twitter", "reddit", "github", "tiktok"]
    matched = [p for p in known if p in tags]
    return matched if matched else ["instagram", "telegram", "reddit", "github"]


# ── Instagram — Selenium stealth ─────────────────────────────────────────
def _scrape_instagram(username: str) -> dict:
    url = f"https://www.instagram.com/{username}/"
    result = {"found": False, "url": url}
    driver = None
    try:
        driver = get_stealth_driver(mobile=False)
        # Set Instagram cookies to bypass login wall
        driver.get("https://www.instagram.com/")
        time.sleep(2)
        # Add fake session cookies to avoid login redirect
        driver.add_cookie({"name": "ig_did", "value": "fake_did", "domain": ".instagram.com"})
        driver.add_cookie({"name": "csrftoken", "value": "fake_csrf", "domain": ".instagram.com"})
        driver.get(url)
        time.sleep(4)
        page = driver.page_source

        if "Sorry, this page" in page or "Page Not Found" in page or "isn't available" in page:
            result["error"] = "Profile not found or private"
            ss = screenshot(driver, f"instagram_{username}.png")
            if ss: result["screenshot"] = ss
            return result

        result["found"] = True

        # Extract meta description (followers/following/posts)
        from selenium.webdriver.common.by import By
        import re
        try:
            desc = driver.find_element(By.XPATH, "//meta[@name='description']")
            content = desc.get_attribute("content") or ""
            result["meta_description"] = content
            for val, label in re.findall(r"([\d,.KM]+)\s+(Followers|Following|Posts)", content):
                result[label.lower()] = val
        except Exception:
            pass
        try:
            title = driver.find_element(By.XPATH, "//meta[@property='og:title']")
            result["title"] = title.get_attribute("content") or ""
        except Exception:
            pass
        try:
            img = driver.find_element(By.XPATH, "//meta[@property='og:image']")
            result["profile_pic"] = img.get_attribute("content") or ""
        except Exception:
            pass

        ss = screenshot(driver, f"instagram_{username}.png")
        if ss: result["screenshot"] = ss

    except Exception as e:
        result["error"] = str(e)[:100]
    finally:
        safe_quit(driver)
    return result


# ── Telegram — pure HTTP ──────────────────────────────────────────────────
def _scrape_telegram_http(username: str) -> dict:
    url = f"https://t.me/{username}"
    result = {"found": False, "url": url}
    try:
        r = TG_SESSION.get(url, timeout=15)
        if "tgme_page_title" in r.text:
            result["found"] = True
            import re
            m = re.search(r'<div class="tgme_page_title"[^>]*>(.*?)</div>', r.text)
            if m: result["name"] = re.sub(r'<[^>]+>', '', m.group(1)).strip()
            m2 = re.search(r'<div class="tgme_page_description"[^>]*>(.*?)</div>', r.text, re.DOTALL)
            if m2: result["description"] = re.sub(r'<[^>]+>', '', m2.group(1)).strip()[:200]
            m3 = re.search(r'<div class="tgme_page_extra"[^>]*>(.*?)</div>', r.text)
            if m3: result["subscribers"] = re.sub(r'<[^>]+>', '', m3.group(1)).strip()
    except Exception as e:
        result["error"] = str(e)[:100]
    return result


# ── Reddit — HTTP with session ────────────────────────────────────────────
def _scrape_reddit(username: str) -> dict:
    """Reddit blocks direct API — use Selenium stealth."""
    url = f"https://www.reddit.com/user/{username}/"
    result = {"found": False, "url": url}
    driver = None
    try:
        driver = get_stealth_driver()
        driver.get(url)
        time.sleep(4)
        page = driver.page_source
        if "nobody on Reddit goes by that name" in page or "page not found" in page.lower():
            result["error"] = "User not found"
        else:
            result["found"] = True
            ss = screenshot(driver, f"reddit_{username}.png")
            if ss: result["screenshot"] = ss
    except Exception as e:
        result["error"] = str(e)[:100]
    finally:
        safe_quit(driver)
    return result


# ── GitHub — pure HTTP JSON API ───────────────────────────────────────────
def _scrape_github(username: str) -> dict:
    result = {"found": False, "url": f"https://github.com/{username}"}
    try:
        r = REDDIT_SESSION.get(
            f"https://api.github.com/users/{username}",
            headers={"Accept": "application/vnd.github.v3+json"},  # UA already set
            timeout=10
        )
        if r.status_code == 200:
            d = r.json()
            result.update({
                "found":      True,
                "name":       d.get("name", ""),
                "bio":        d.get("bio", ""),
                "company":    d.get("company", ""),
                "location":   d.get("location", ""),
                "email":      d.get("email", ""),
                "blog":       d.get("blog", ""),
                "followers":  d.get("followers", 0),
                "following":  d.get("following", 0),
                "repos":      d.get("public_repos", 0),
                "created":    d.get("created_at", ""),
                "avatar":     d.get("avatar_url", ""),
            })
        elif r.status_code == 404:
            result["error"] = "User not found"
    except Exception as e:
        result["error"] = str(e)[:100]
    return result


# ── Twitter — Selenium stealth ────────────────────────────────────────────
def _scrape_twitter(username: str) -> dict:
    url = f"https://twitter.com/{username}"
    result = {"found": False, "url": url}
    driver = None
    try:
        driver = get_stealth_driver()
        driver.get(url)
        time.sleep(5)
        page = driver.page_source
        if "This account doesn" in page or "doesn't exist" in page or "page doesn't exist" in page:
            result["error"] = "Account not found"
        else:
            result["found"] = True
            ss = screenshot(driver, f"twitter_{username}.png")
            if ss: result["screenshot"] = ss
    except Exception as e:
        result["error"] = str(e)[:100]
    finally:
        safe_quit(driver)
    return result


# ── TikTok — Selenium stealth ─────────────────────────────────────────────
def _scrape_tiktok(username: str) -> dict:
    url = f"https://www.tiktok.com/@{username}"
    result = {"found": False, "url": url}
    driver = None
    try:
        driver = get_stealth_driver(mobile=True)
        driver.get(url)
        time.sleep(5)
        page = driver.page_source
        if "Couldn't find this account" in page or "404" in page:
            result["error"] = "Account not found"
        else:
            result["found"] = True
            ss = screenshot(driver, f"tiktok_{username}.png")
            if ss: result["screenshot"] = ss
    except Exception as e:
        result["error"] = str(e)[:100]
    finally:
        safe_quit(driver)
    return result


def _build_notes(username: str, platforms: dict) -> str:
    lines = [f"=== Username OSINT: @{username} ==="]
    for platform, data in platforms.items():
        lines.append(f"\n--- {platform.upper()} ---")
        if not data.get("found"):
            lines.append(f"  Not found: {data.get('error', 'N/A')}")
            continue
        lines.append(f"  URL       : {data.get('url', '')}")
        for field in ("name","title","bio","description","subscribers",
                      "followers","following","posts","repos","location",
                      "company","email","blog","created","profile_pic","avatar"):
            if data.get(field):
                lines.append(f"  {field:<12}: {str(data[field])[:100]}")
        if data.get("screenshot"):
            lines.append(f"  Screenshot: {data['screenshot']}")
    return "\n".join(lines)
