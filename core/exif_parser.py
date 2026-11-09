import io
from pathlib import Path
from typing import Dict, Any

try:
    import exifread
    _HAS_EXIFREAD = True
except ImportError:
    _HAS_EXIFREAD = False

try:
    from PIL import Image
    from PIL.ExifTags import TAGS, GPSTAGS
    _HAS_PIL = True
except ImportError:
    _HAS_PIL = False


def _rational_to_float(val):
    try:
        if hasattr(val, "numerator"):
            return val.numerator / val.denominator
        if isinstance(val, (list, tuple)) and len(val) == 2:
            return val[0] / val[1]
        return float(val)
    except Exception:
        return 0.0


def _dms_to_decimal(dms, ref):
    try:
        d = _rational_to_float(dms[0])
        m = _rational_to_float(dms[1])
        s = _rational_to_float(dms[2])
        decimal = d + m / 60 + s / 3600
        if ref in ("S", "W"):
            decimal = -decimal
        return round(decimal, 7)
    except Exception:
        return None


def _as_bytes(data) -> bytes:
    """Accept raw bytes, or a file path (str/Path) — read it."""
    if isinstance(data, (str, Path)):
        return Path(data).read_bytes()
    return data


def extract_exif(data) -> Dict[str, Any]:
    result = {}
    try:
        data = _as_bytes(data)
    except Exception:
        return result
    if _HAS_EXIFREAD:
        try:
            tags = exifread.process_file(io.BytesIO(data), details=False)
            for key, val in tags.items():
                clean_key = key.replace("EXIF ", "").replace("Image ", "").replace("GPS ", "GPS_")
                if clean_key in ("Thumbnail", "ThumbnailLength", "ThumbnailData"):
                    continue
                result[clean_key] = str(val)
            # GPS
            lat_tag = tags.get("GPS GPSLatitude")
            lat_ref = tags.get("GPS GPSLatitudeRef")
            lon_tag = tags.get("GPS GPSLongitude")
            lon_ref = tags.get("GPS GPSLongitudeRef")
            if lat_tag and lon_tag:
                lat_vals = [v.num / v.den for v in lat_tag.values]
                lon_vals = [v.num / v.den for v in lon_tag.values]
                lat = _dms_to_decimal(lat_vals, str(lat_ref))
                lon = _dms_to_decimal(lon_vals, str(lon_ref))
                if lat is not None and lon is not None:
                    result["gps_latitude"] = lat
                    result["gps_longitude"] = lon
                    result["gps_maps_url"] = f"https://maps.google.com/?q={lat},{lon}"
        except Exception:
            pass

    if not result and _HAS_PIL:
        try:
            img = Image.open(io.BytesIO(data))
            raw = img._getexif()
            if raw:
                for tag_id, value in raw.items():
                    tag = TAGS.get(tag_id, str(tag_id))
                    if tag == "GPSInfo":
                        gps = {}
                        for gps_id, gps_val in value.items():
                            gps[GPSTAGS.get(gps_id, gps_id)] = gps_val
                        lat = _dms_to_decimal(gps.get("GPSLatitude"), gps.get("GPSLatitudeRef"))
                        lon = _dms_to_decimal(gps.get("GPSLongitude"), gps.get("GPSLongitudeRef"))
                        if lat is not None and lon is not None:
                            result["gps_latitude"] = lat
                            result["gps_longitude"] = lon
                            result["gps_maps_url"] = f"https://maps.google.com/?q={lat},{lon}"
                    else:
                        result[tag] = str(value)
        except Exception:
            pass

    return result
