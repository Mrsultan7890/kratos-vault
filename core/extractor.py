import re
from typing import List, Dict

_PATTERNS = {
    "Email":   re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}", re.I),
    "Phone":   re.compile(r"(?:\+?1[\s.\-]?)?\(?\d{3}\)?[\s.\-]?\d{3}[\s.\-]?\d{4}"),
    "URL":     re.compile(r"https?://[^\s\"'<>]+"),
    "IP":      re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b"),
    "Domain":  re.compile(r"\b(?:[a-zA-Z0-9\-]+\.)+(?:com|net|org|io|gov|edu|co|uk|de|ru|cn|onion)\b", re.I),
    "BTC":     re.compile(r"\b(?:[13][a-km-zA-HJ-NP-Z1-9]{25,34}|bc1[a-z0-9]{39,59})\b"),
    "ETH":     re.compile(r"\b0x[a-fA-F0-9]{40}\b"),
    "Hash_MD5":    re.compile(r"\b[a-fA-F0-9]{32}\b"),
    "Hash_SHA1":   re.compile(r"\b[a-fA-F0-9]{40}\b"),
    "Hash_SHA256": re.compile(r"\b[a-fA-F0-9]{64}\b"),
}

_ENTITY_TYPE_MAP = {
    "Email": "Email",
    "Phone": "Phone",
    "URL": "URL",
    "IP": "IP",
    "Domain": "Domain",
    "BTC": "Crypto",
    "ETH": "Crypto",
    "Hash_MD5": "Hash",
    "Hash_SHA1": "Hash",
    "Hash_SHA256": "Hash",
}


def extract(text: str) -> List[Dict]:
    if not text:
        return []
    results = []
    seen = set()
    for pattern_name, regex in _PATTERNS.items():
        for match in regex.finditer(text):
            val = match.group().strip()
            if val in seen:
                continue
            seen.add(val)
            entity_type = _ENTITY_TYPE_MAP.get(pattern_name, "Other")
            tag = pattern_name.lower().replace("_", "-")
            results.append({
                "type": entity_type,
                "name": val,
                "value": val,
                "tags": ["auto-extracted", tag],
                "confidence": 70,
                "source": "auto-extract",
            })
    return results


def extract_iocs(text: str) -> Dict[str, List[str]]:
    """Return grouped IOCs dict for quick display."""
    result = {}
    for name, regex in _PATTERNS.items():
        matches = list(set(regex.findall(text)))
        if matches:
            result[name] = matches
    return result
