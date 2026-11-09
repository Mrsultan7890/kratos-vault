import os
import sys
import asyncio
import httpx
import time
import re
import uuid
from pathlib import Path

from core.enrichers._browser import get_stealth_driver, safe_quit, screenshot

GHUNT_PATH = Path(os.environ.get("GHUNT_PATH", "/home/kali/Tools-inv/GHunt"))
if GHUNT_PATH.exists() and str(GHUNT_PATH) not in sys.path:
    sys.path.insert(0, str(GHUNT_PATH))

SCREENSHOT_DIR = Path.home() / ".kratos_vault" / "screenshots"
SCREENSHOT_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
os.chmod(SCREENSHOT_DIR, 0o700)


def run(email: str) -> dict:
    try:
        return asyncio.run(_hunt(email))
    except Exception as e:
        return {"error": str(e), "email": email, "found": False,
                "tags": [], "platforms": {}, "screenshots": [], "notes": ""}


# ═══════════════════════════════════════════════════════════════
# LAYER 1 — Core profile + service detection
# ═══════════════════════════════════════════════════════════════
async def _hunt(email: str) -> dict:
    from ghunt.helpers import auth
    from ghunt.helpers.utils import get_httpx_client
    from ghunt.apis.peoplepa import PeoplePaHttp

    result = {
        "email": email, "found": False,
        "tags": ["ghunt", "google", "email-osint"],
        "platforms": {}, "screenshots": [], "notes": "",
    }

    async with get_httpx_client() as client:
        try:
            creds = await auth.load_and_auth(client)
        except Exception as e:
            result["error"] = f"Auth failed: {e}"
            return result

        people_pa = PeoplePaHttp(creds)
        is_found, target = await people_pa.people_lookup(
            client, email, params_template="max_details"
        )
        if not is_found or "PROFILE" not in target.sourceIds:
            result["error"] = "Not a public Google Account"
            return result

        result["found"] = True
        c = "PROFILE"

        # ── Base profile data ──────────────────────────────────────
        profile = {"gaia_id": target.personId}

        if c in target.profilePhotos and not target.profilePhotos[c].isDefault:
            profile["profile_photo"] = target.profilePhotos[c].url
            path = await _download_image(client, profile["profile_photo"],
                                         f"gphoto_{target.personId}.jpg")
            if path:
                result["screenshots"].append(path)

        if c in target.coverPhotos and not target.coverPhotos[c].isDefault:
            profile["cover_photo"] = target.coverPhotos[c].url

        if target.sourceIds[c].lastUpdated:
            profile["last_updated"] = target.sourceIds[c].lastUpdated.strftime(
                "%Y/%m/%d %H:%M:%S UTC")

        if c in target.profileInfos:
            profile["user_types"] = list(target.profileInfos[c].userTypes)

        profile["chat_entity_type"]  = target.extendedData.dynamiteData.entityType
        profile["enterprise_user"]   = target.extendedData.gplusData.isEntrepriseUser
        if target.extendedData.dynamiteData.customerId:
            profile["chat_customer_id"] = target.extendedData.dynamiteData.customerId

        # ── Detected services ──────────────────────────────────────
        services = []
        if c in target.inAppReachability:
            services = list(target.inAppReachability[c].apps)
            profile["google_services"] = services
            result["tags"] += [s.lower() for s in services]

        result["platforms"]["profile"] = profile

        # ═══════════════════════════════════════════════════════════
        # LAYER 2 — Per-service deep scrapers
        # ═══════════════════════════════════════════════════════════
        gaia_id = target.personId

        for service in services:
            s = service.lower()

            if s == "maps":
                result["platforms"]["maps"] = await _layer_maps(client, gaia_id, result)

            elif s == "photos":
                result["platforms"]["photos"] = await _layer_photos(client, gaia_id, result)

            elif s == "youtube":
                result["platforms"]["youtube"] = await _layer_youtube(gaia_id, result)

            elif s == "drive":
                result["platforms"]["drive"] = _layer_drive_note(gaia_id)

            elif s == "meet":
                result["platforms"]["meet"] = {"found": True, "note": "Meet is active on this account"}

            elif s == "chat":
                result["platforms"]["chat"] = {"found": True, "note": "Google Chat is active"}

            elif s == "blogger":
                result["platforms"]["blogger"] = await _layer_blogger(gaia_id, result)

            elif s == "sites":
                result["platforms"]["sites"] = await _layer_sites(email, result)

        # Always run these regardless of service list
        result["platforms"]["gmail"]     = await _layer_gmail(client, email)
        result["platforms"]["calendar"]  = await _layer_calendar(creds, client, email, result)
        result["platforms"]["playgames"] = await _layer_playgames(creds, client, email, result)

    result["notes"] = _build_notes(result)
    return result


# ═══════════════════════════════════════════════════════════════
# LAYER 2 SCRAPERS
# ═══════════════════════════════════════════════════════════════

async def _layer_maps(client, gaia_id: str, result: dict) -> dict:
    from ghunt.helpers import gmaps
    data = {"found": False,
            "profile_url": f"https://www.google.com/maps/contrib/{gaia_id}/reviews"}
    try:
        err, stats = await gmaps.get_reviews(client, gaia_id)
        if err == "" and stats:
            data["found"] = True
            data["stats"] = stats
            result["tags"].append("google-maps-contributor")
            # Screenshots: reviews + photos pages
            for page in ["reviews", "photos", "about"]:
                url = f"https://www.google.com/maps/contrib/{gaia_id}/{page}"
                ss = _sync_screenshot(url, f"maps_{gaia_id}_{page}.png")
                if ss:
                    result["screenshots"].append(ss)
                    data[f"screenshot_{page}"] = ss
        else:
            data["status"] = err or "empty"
    except Exception as e:
        data["error"] = str(e)
    return data


async def _layer_photos(client, gaia_id: str, result: dict) -> dict:
    data = {"found": False,
            "profile_url": f"https://photos.google.com/u/0/user/{gaia_id}"}
    try:
        ss = _sync_screenshot(data["profile_url"], f"gphotos_{gaia_id}.png")
        if ss:
            data["found"] = True
            data["screenshot"] = ss
            result["screenshots"].append(ss)
            result["tags"].append("google-photos")

        # Also try shared albums page
        albums_url = f"https://photos.google.com/u/0/user/{gaia_id}/albums"
        ss2 = _sync_screenshot(albums_url, f"gphotos_albums_{gaia_id}.png")
        if ss2:
            data["albums_screenshot"] = ss2
            result["screenshots"].append(ss2)
    except Exception as e:
        data["error"] = str(e)
    return data


async def _layer_youtube(gaia_id: str, result: dict) -> dict:
    data = {"found": False}
    try:
        # YouTube channel search by Gaia ID
        url = f"https://www.youtube.com/channel/{gaia_id}"
        ss = _sync_screenshot(url, f"youtube_{gaia_id}.png")
        if ss:
            data["found"] = True
            data["channel_url"] = url
            data["screenshot"] = ss
            result["screenshots"].append(ss)
            result["tags"].append("youtube")
    except Exception as e:
        data["error"] = str(e)
    return data


def _layer_drive_note(gaia_id: str) -> dict:
    """
    Drive requires a file ID to search — we can't enumerate files by email.
    We note that Drive is active so investigator can manually search
    for shared Drive files from this account.
    """
    return {
        "found": True,
        "note": "Drive is active. Use 'ghunt drive <file_id>' to investigate shared files.",
        "search_tip": f"Search Google for: site:drive.google.com shared files from this account",
    }


async def _layer_blogger(gaia_id: str, result: dict) -> dict:
    data = {"found": False}
    try:
        url = f"https://www.blogger.com/profile/{gaia_id}"
        ss = _sync_screenshot(url, f"blogger_{gaia_id}.png")
        if ss:
            data["found"] = True
            data["profile_url"] = url
            data["screenshot"] = ss
            result["screenshots"].append(ss)
            result["tags"].append("blogger")
    except Exception as e:
        data["error"] = str(e)
    return data


async def _layer_sites(email: str, result: dict) -> dict:
    data = {"found": False}
    try:
        # Google Sites search
        username = email.split("@")[0]
        url = f"https://sites.google.com/view/{username}"
        ss = _sync_screenshot(url, f"gsites_{username}.png")
        if ss:
            data["found"] = True
            data["url"] = url
            data["screenshot"] = ss
            result["screenshots"].append(ss)
            result["tags"].append("google-sites")
    except Exception as e:
        data["error"] = str(e)
    return data


async def _layer_gmail(client, email: str) -> dict:
    try:
        from ghunt.helpers.gmail import is_email_registered
        registered = await is_email_registered(client, email)
        return {"found": registered, "registered": registered}
    except Exception as e:
        return {"found": False, "error": str(e)}


async def _layer_calendar(creds, client, email: str, result: dict) -> dict:
    from ghunt.helpers import calendar as gcal
    data = {"found": False}
    try:
        cal_found, calendar, events = await gcal.fetch_all(creds, client, email)
        if not cal_found:
            return data
        data["found"]       = True
        data["calendar_id"] = calendar.id
        data["timezone"]    = calendar.time_zone
        data["ical_url"]    = f"https://calendar.google.com/calendar/ical/{email}/public/basic.ics"
        result["tags"].append("public-calendar")

        if events.items:
            data["event_count"] = len(events.items)
            data["events"] = [
                {"title": ev.summary or "(no title)",
                 "date":  ev.start.date_time.strftime("%Y/%m/%d %H:%M")
                          if ev.start.date_time else "?"}
                for ev in events.items[-10:]
            ]
            # Other names used by target
            other_names = {
                ev.creator.display_name
                for ev in events.items
                if ev.creator.email == email and ev.creator.display_name
            }
            if other_names:
                data["other_names"] = list(other_names)
                result["tags"].append("multiple-names")
    except Exception as e:
        data["error"] = str(e)
    return data


async def _layer_playgames(creds, client, email: str, result: dict) -> dict:
    from ghunt.helpers import playgames
    data = {"found": False}
    try:
        players = await playgames.search_player(creds, client, email)
        if not players:
            return data
        p = players[0]
        data["found"]       = True
        data["player_name"] = p.name
        data["player_id"]   = p.id
        data["avatar_url"]  = p.avatar_url
        result["tags"].append("play-games")

        _, player = await playgames.get_player(creds, client, p.id)
        if player.played_games:
            data["played_games_count"] = len(player.played_games)
            data["last_game"] = player.profile.last_played_app.app_name
        if player.achievements:
            data["achievements_count"] = len(player.achievements)
    except Exception as e:
        data["error"] = str(e)
    return data


# ═══════════════════════════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════════════════════════

async def _download_image(client: httpx.AsyncClient, url: str, filename: str) -> str:
    try:
        from core.enrichers.url_enricher import _validate_public_url
        _validate_public_url(url)
        async with client.stream("GET", url, timeout=15, follow_redirects=False) as resp:
            if resp.status_code != 200:
                return ""
            if int(resp.headers.get("content-length", "0") or 0) > 10 * 1024 * 1024:
                return ""
            data = bytearray()
            async for chunk in resp.aiter_bytes():
                data.extend(chunk)
                if len(data) > 10 * 1024 * 1024:
                    return ""
        safe_name = re.sub(r"[^A-Za-z0-9._-]+", "_", Path(filename).name)
        path = SCREENSHOT_DIR / (
            f"{Path(safe_name).stem}_{uuid.uuid4().hex[:8]}{Path(safe_name).suffix}")
        path.write_bytes(data)
        path.chmod(0o600)
        return str(path)
    except Exception as exc:
        import logging
        logging.getLogger(__name__).warning("Could not save remote profile image: %s", exc)
    return ""


def _sync_screenshot(url: str, filename: str) -> str:
    driver = None
    try:
        driver = get_stealth_driver()
        driver.get(url)
        time.sleep(4)
        return screenshot(driver, filename)
    finally:
        safe_quit(driver)


# ═══════════════════════════════════════════════════════════════
# NOTES BUILDER
# ═══════════════════════════════════════════════════════════════

def _build_notes(r: dict) -> str:
    lines = [f"=== Google OSINT: {r['email']} ===",
             f"Tags: {', '.join(r['tags'])}"]

    p = r["platforms"].get("profile", {})
    lines += ["\n--- [LAYER 1] Google Account ---"]
    if p.get("gaia_id"):          lines.append(f"  Gaia ID       : {p['gaia_id']}")
    if p.get("last_updated"):     lines.append(f"  Last Edit     : {p['last_updated']}")
    if p.get("user_types"):       lines.append(f"  User Types    : {', '.join(p['user_types'])}")
    if p.get("google_services"):  lines.append(f"  Services      : {', '.join(p['google_services'])}")
    if p.get("enterprise_user"):  lines.append(f"  Enterprise    : {p['enterprise_user']}")
    if p.get("profile_photo"):    lines.append(f"  Profile Photo : {p['profile_photo']}")
    if p.get("cover_photo"):      lines.append(f"  Cover Photo   : {p['cover_photo']}")
    if p.get("chat_entity_type"): lines.append(f"  Chat Type     : {p['chat_entity_type']}")

    lines.append("\n--- [LAYER 2] Per-Service Results ---")

    gm = r["platforms"].get("gmail", {})
    lines.append(f"  Gmail Registered : {'YES ✓' if gm.get('registered') else 'NO'}")

    for svc, label in [
        ("maps",      "Google Maps"),
        ("photos",    "Google Photos"),
        ("youtube",   "YouTube"),
        ("drive",     "Google Drive"),
        ("calendar",  "Google Calendar"),
        ("playgames", "Play Games"),
        ("blogger",   "Blogger"),
        ("sites",     "Google Sites"),
        ("meet",      "Google Meet"),
        ("chat",      "Google Chat"),
    ]:
        d = r["platforms"].get(svc)
        if not d:
            continue
        lines.append(f"\n  [{label}]")
        if d.get("note"):
            lines.append(f"    Note      : {d['note']}")
        if d.get("profile_url"):
            lines.append(f"    URL       : {d['profile_url']}")
        if d.get("stats"):
            for k, v in d["stats"].items():
                if v: lines.append(f"    {k:<12}: {v}")
        if d.get("calendar_id"):
            lines.append(f"    Cal ID    : {d['calendar_id']}")
            lines.append(f"    Timezone  : {d.get('timezone', '')}")
            lines.append(f"    iCal      : {d.get('ical_url', '')}")
            lines.append(f"    Events    : {d.get('event_count', 0)}")
        if d.get("other_names"):
            lines.append(f"    Alt Names : {', '.join(d['other_names'])}")
        if d.get("events"):
            lines.append("    Recent Events:")
            for ev in d["events"]:
                lines.append(f"      [{ev['date']}] {ev['title']}")
        if d.get("player_name"):
            lines.append(f"    Player    : {d['player_name']} (ID: {d['player_id']})")
            lines.append(f"    Games     : {d.get('played_games_count', 0)}")
            lines.append(f"    Achiev.   : {d.get('achievements_count', 0)}")
        if d.get("channel_url"):
            lines.append(f"    Channel   : {d['channel_url']}")
        for k in ["screenshot", "screenshot_reviews", "screenshot_photos"]:
            if d.get(k):
                lines.append(f"    Screenshot: {d[k]}")

    return "\n".join(lines)
