from core.enrichers._net import new_session
from core.enrichers._browser import get_stealth_driver, safe_quit, screenshot

SESSION = new_session({"User-Agent": "Mozilla/5.0"})


def run(address: str) -> dict:
    result = {
        "address": address, "found": False,
        "tags": ["address-osint"], "platforms": {}, "screenshots": [], "notes": ""
    }
    result["platforms"]["nominatim"] = _nominatim(address)
    if result["platforms"]["nominatim"].get("found"):
        result["found"] = True
        lat = result["platforms"]["nominatim"].get("lat")
        lon = result["platforms"]["nominatim"].get("lon")
        if lat and lon:
            result["tags"].append("geocoded")
            ss = _map_screenshot(lat, lon, address)
            if ss:
                result["screenshots"].append(ss)
                result["platforms"]["map_screenshot"] = {"found": True, "path": ss}
    result["notes"] = _build_notes(result)
    return result


def _nominatim(address: str) -> dict:
    try:
        r = SESSION.get(
            "https://nominatim.openstreetmap.org/search",
            params={"q": address, "format": "json", "addressdetails": 1, "limit": 1},
            headers={"Accept-Language": "en"},
            timeout=15
        )
        data = r.json()
        if not data:
            return {"found": False, "note": "Address not found"}
        d = data[0]
        addr = d.get("address", {})
        lat, lon = float(d.get("lat", 0)), float(d.get("lon", 0))
        return {
            "found":        True,
            "display_name": d.get("display_name", ""),
            "lat":          lat,
            "lon":          lon,
            "type":         d.get("type", ""),
            "house_number": addr.get("house_number", ""),
            "road":         addr.get("road", ""),
            "city":         addr.get("city") or addr.get("town") or addr.get("village", ""),
            "state":        addr.get("state", ""),
            "country":      addr.get("country", ""),
            "postcode":     addr.get("postcode", ""),
            "maps_url":     f"https://www.google.com/maps?q={lat},{lon}",
            "osm_url":      f"https://www.openstreetmap.org/?mlat={lat}&mlon={lon}&zoom=16",
        }
    except Exception as e:
        return {"found": False, "error": str(e)[:100]}


def _map_screenshot(lat: float, lon: float, address: str) -> str:
    url = f"https://www.openstreetmap.org/?mlat={lat}&mlon={lon}&zoom=16"
    driver = None
    try:
        driver = get_stealth_driver()
        driver.get(url)
        safe = "".join(c if c.isalnum() else "_" for c in address[:30])
        return screenshot(driver, f"address_{safe}.png")
    except Exception as exc:
        import logging
        logging.getLogger(__name__).warning("Could not capture address map screenshot: %s", exc)
        return ""
    finally:
        safe_quit(driver)


def _build_notes(r: dict) -> str:
    lines = [f"=== Address OSINT: {r['address']} ==="]
    n = r["platforms"].get("nominatim", {})
    if n.get("found"):
        lines += ["\n--- Geocoding (OpenStreetMap) ---",
                  f"  Full Address: {n.get('display_name','')}",
                  f"  Coordinates : {n.get('lat')}, {n.get('lon')}",
                  f"  City        : {n.get('city','')}",
                  f"  State       : {n.get('state','')}",
                  f"  Country     : {n.get('country','')}",
                  f"  Postcode    : {n.get('postcode','')}",
                  f"  Google Maps : {n.get('maps_url','')}",
                  f"  OSM URL     : {n.get('osm_url','')}"]
    m = r["platforms"].get("map_screenshot", {})
    if m.get("found"):
        lines.append(f"\n  Map Screenshot: {m.get('path','')}")
    return "\n".join(lines)
