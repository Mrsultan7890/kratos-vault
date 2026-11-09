# Shared Selenium stealth driver used across all enrichers
import os
import re
import time
import uuid
from pathlib import Path

from core.enrichers._net import CHROME_BINARY, CHROMEDRIVER, proxy_dict

SCREENSHOT_DIR = Path.home() / ".kratos_vault" / "screenshots"
SCREENSHOT_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
os.chmod(SCREENSHOT_DIR, 0o700)

# Rotating user agents
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) Gecko/20100101 Firefox/125.0",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_4 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Mobile/15E148 Safari/604.1",
]

_ua_index = 0

def next_ua() -> str:
    global _ua_index
    ua = USER_AGENTS[_ua_index % len(USER_AGENTS)]
    _ua_index += 1
    return ua


def get_stealth_driver(mobile: bool = False):
    """Selenium driver with anti-detection measures."""
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options
    from selenium.webdriver.chrome.service import Service

    opts = Options()
    opts.add_argument("--headless=new")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--disable-gpu")
    opts.add_argument("--disable-blink-features=AutomationControlled")
    opts.add_argument("--disable-infobars")
    opts.add_argument("--page-load-strategy=eager")
    opts.add_experimental_option("excludeSwitches", ["enable-automation"])
    opts.add_experimental_option("useAutomationExtension", False)

    if mobile:
        opts.add_argument("--window-size=390,844")
        opts.add_argument(f"user-agent=Mozilla/5.0 (iPhone; CPU iPhone OS 17_4 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Mobile/15E148 Safari/604.1")
    else:
        opts.add_argument("--window-size=1280,900")
        opts.add_argument(f"user-agent={next_ua()}")

    opts.binary_location = CHROME_BINARY
    proxy = proxy_dict()
    if proxy:
        # Chrome understands host:port; socks5h:// -> socks5:// host:port
        raw = proxy["http"]
        scheme = "socks5" if raw.startswith("socks") else raw.split("://")[0]
        host_part = raw.split("://", 1)[1]
        opts.add_argument(f"--proxy-server={scheme}://{host_part}")

    if not os.path.isfile(CHROME_BINARY):
        raise FileNotFoundError(
            f"Chromium was not found at {CHROME_BINARY}; set CHROME_PATH to its location"
        )
    if not os.path.isfile(CHROMEDRIVER):
        raise FileNotFoundError(
            f"ChromeDriver was not found at {CHROMEDRIVER}; set CHROMEDRIVER_PATH"
        )
    svc = Service(CHROMEDRIVER)

    driver = webdriver.Chrome(service=svc, options=opts)
    driver.set_page_load_timeout(20)
    driver.set_script_timeout(10)

    # Patch navigator.webdriver to undefined
    driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {
        "source": """
            Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
            Object.defineProperty(navigator, 'plugins', {get: () => [1,2,3]});
            Object.defineProperty(navigator, 'languages', {get: () => ['en-US','en']});
            window.chrome = {runtime: {}};
        """
    })
    return driver


def screenshot(driver, filename: str) -> str:
    try:
        safe_name = re.sub(r"[^A-Za-z0-9._-]+", "_", Path(filename).name)
        path = SCREENSHOT_DIR / f"{Path(safe_name).stem}_{uuid.uuid4().hex[:8]}{Path(safe_name).suffix}"
        driver.save_screenshot(str(path))
        return str(path)
    except Exception:
        return ""


def safe_quit(driver):
    try:
        driver.quit()
    except Exception:
        pass
