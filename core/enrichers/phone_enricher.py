import time
import re
import requests
from pathlib import Path
from core.enrichers._net import new_session
from core.enrichers._browser import get_stealth_driver, screenshot, safe_quit, SCREENSHOT_DIR

PHONE_SESSION = new_session({
    "User-Agent": "TelegramBot (like TwitterBot)",
    "Accept": "text/html,application/xhtml+xml",
})

UPI_SUFFIXES = [
    "okicici", "okhdfcbank", "okaxis", "oksbi",
    "paytm", "ybl", "ibl", "axl", "upi",
]


def run(phone: str) -> dict:
    result = {
        "phone": phone, "found": False,
        "tags": ["phone-osint"], "platforms": {}, "screenshots": [], "notes": ""
    }

    # 1. libphonenumber — offline
    lib = _phonenumber_info(phone)
    result["platforms"]["phonenumber"] = lib
    if lib.get("valid"):
        result["found"] = True
        result["tags"] += lib.get("tags", [])

    # 2. WhatsApp — Selenium (JS required)
    wa = _check_whatsapp(phone)
    result["platforms"]["whatsapp"] = wa
    if wa.get("found"):
        result["tags"].append("whatsapp")
        if wa.get("screenshot"):
            result["screenshots"].append(wa["screenshot"])

    # 3. Telegram — pure HTTP, no Selenium needed
    tg = _check_telegram_http(phone)
    result["platforms"]["telegram"] = tg
    if tg.get("found"):
        result["tags"].append("telegram")

    result["notes"] = _build_notes(result)
    return result


def _phonenumber_info(phone: str) -> dict:
    try:
        import phonenumbers
        from phonenumbers import geocoder, carrier, timezone
        parsed = phonenumbers.parse(phone, None)
        valid  = phonenumbers.is_valid_number(parsed)
        country     = geocoder.description_for_number(parsed, "en")
        carrier_name= carrier.name_for_number(parsed, "en")
        timezones   = list(timezone.time_zones_for_number(parsed))
        number_type = phonenumbers.number_type(parsed)
        type_map = {0:"FIXED_LINE",1:"MOBILE",2:"FIXED_OR_MOBILE",
                    3:"TOLL_FREE",4:"PREMIUM_RATE",6:"VOIP",99:"UNKNOWN"}
        line_type = type_map.get(number_type, "UNKNOWN")
        tags = []
        if valid:
            if country:   tags.append(f"country-{country.lower().replace(' ','-')}")
            tags.append(line_type.lower())
            if carrier_name: tags.append(f"carrier-{carrier_name.lower().replace(' ','-')}")
        return {
            "valid": valid,
            "country": country, "carrier": carrier_name,
            "line_type": line_type, "timezones": timezones,
            "e164": phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164),
            "international": phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.INTERNATIONAL),
            "tags": [t for t in tags if t],
        }
    except Exception as e:
        return {"valid": False, "error": str(e)[:100]}


def _clean_phone(phone: str) -> str:
    return re.sub(r"[^\d]", "", phone)


def _check_whatsapp(phone: str) -> dict:
    """
    wa.me redirects to api.whatsapp.com for ALL numbers (valid or not).
    Use Selenium to render JS and check for 'Continue to Chat' button.
    """
    digits = _clean_phone(phone)
    url = f"https://wa.me/{digits}"
    result = {"found": False, "url": url}
    driver = None
    try:
        driver = get_stealth_driver(mobile=True)
        driver.get(url)
        time.sleep(4)
        page = driver.page_source

        # Real indicator: "Continue to Chat" button appears only for valid numbers
        if "Continue to Chat" in page or "continue_to_chat" in page.lower():
            result["found"] = True
        elif "app_absent" in driver.current_url:
            # Check rendered page for the chat button via JS
            btn = driver.execute_script(
                "return document.querySelector('a[href*=\"open_app\"]') !== null"
            )
            if btn:
                result["found"] = True

        ss = screenshot(driver, f"whatsapp_{digits}.png")
        if ss: result["screenshot"] = ss
        result["final_url"] = driver.current_url

    except Exception as e:
        result["error"] = str(e)[:100]
    finally:
        safe_quit(driver)
    return result


def _check_telegram_http(phone: str) -> dict:
    """
    Telegram t.me/+<phone> — pure HTTP with TelegramBot UA.
    tgme_page_title present = account exists.
    """
    digits = _clean_phone(phone)
    url = f"https://t.me/+{digits}"
    result = {"found": False, "url": url}
    try:
        r = PHONE_SESSION.get(url, timeout=15, allow_redirects=True)
        if "tgme_page_title" in r.text or "tgme_page_description" in r.text:
            result["found"] = True
            # Extract name if available
            import re as _re
            m = _re.search(r'<div class="tgme_page_title"[^>]*>(.*?)</div>', r.text)
            if m:
                result["name"] = _re.sub(r'<[^>]+>', '', m.group(1)).strip()
    except Exception as e:
        result["error"] = str(e)[:100]
    return result


def _build_notes(r: dict) -> str:
    lines = [f"=== Phone OSINT: {r['phone']} ==="]
    ph = r["platforms"].get("phonenumber", {})
    if ph.get("valid"):
        lines += ["\n--- Number Info ---",
                  f"  E164        : {ph.get('e164','')}",
                  f"  International: {ph.get('international','')}",
                  f"  Country     : {ph.get('country','')}",
                  f"  Carrier     : {ph.get('carrier','')}",
                  f"  Line Type   : {ph.get('line_type','')}",
                  f"  Timezones   : {', '.join(ph.get('timezones',[]))}"]
    wa = r["platforms"].get("whatsapp", {})
    lines += ["\n--- WhatsApp ---",
              f"  Registered  : {'YES ✓' if wa.get('found') else 'NO'}"]
    if wa.get("screenshot"): lines.append(f"  Screenshot  : {wa['screenshot']}")
    tg = r["platforms"].get("telegram", {})
    lines += ["\n--- Telegram ---",
              f"  Registered  : {'YES ✓' if tg.get('found') else 'NO'}"]
    if tg.get("name"): lines.append(f"  Name        : {tg['name']}")
    return "\n".join(lines)
