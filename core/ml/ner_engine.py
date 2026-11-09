"""
NER Engine — spaCy en_core_web_sm
Extracts: PERSON, ORG, GPE, LOC, DATE, EMAIL, PHONE, URL from raw text
"""
from typing import List, Dict
import re
import spacy

_nlp = None

_LABEL_MAP = {
    "PERSON":  "Person",
    "ORG":     "Organization",
    "GPE":     "Address",
    "LOC":     "Address",
    "FAC":     "Address",
    "DATE":    "Other",
    "TIME":    "Other",
    "MONEY":   "Other",
    "PRODUCT": "Other",
    "EVENT":   "Other",
    "NORP":    "Other",
}

_REGEX_PATTERNS = {
    "Email":  re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}"),
    "Phone":  re.compile(r"(?:\+?1[\s.\-]?)?\(?\d{3}\)?[\s.\-]?\d{3}[\s.\-]?\d{4}"),
    "URL":    re.compile(r"https?://[^\s\"'<>]+"),
    "IP":     re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b"),
    "Hash":   re.compile(r"\b[a-fA-F0-9]{32,64}\b"),
    "Crypto": re.compile(r"\b(?:[13][a-km-zA-HJ-NP-Z1-9]{25,34}|bc1[a-z0-9]{39,59}|0x[a-fA-F0-9]{40})\b"),
}


class NERModelError(RuntimeError):
    """Raised when the spaCy language model is not installed."""


def _get_nlp():
    global _nlp
    if _nlp is None:
        try:
            _nlp = spacy.load("en_core_web_sm")
        except OSError as e:
            raise NERModelError(
                "spaCy model 'en_core_web_sm' not installed. Run:\n"
                "    python -m spacy download en_core_web_sm\n"
                "(regex-only extraction still works without it)"
            ) from e
    return _nlp


def extract_entities(text: str) -> List[Dict]:
    if not text or not text.strip():
        return []

    results = []
    seen = set()

    try:
        nlp = _get_nlp()
        doc = nlp(text[:100_000])
        for ent in doc.ents:
            val = ent.text.strip()
            etype = _LABEL_MAP.get(ent.label_)
            if not etype or not val or val.lower() in seen:
                continue
            seen.add(val.lower())
            results.append({
                "type":       etype,
                "name":       val,
                "value":      val,
                "tags":       ["ner", ent.label_.lower()],
                "confidence": 75,
                "source":     "spacy-ner",
                "notes":      f"NER label: {ent.label_} ({spacy.explain(ent.label_)})",
            })
    except NERModelError:
        pass  # model missing → regex patterns below still run

    for etype, pattern in _REGEX_PATTERNS.items():
        for match in pattern.finditer(text):
            val = match.group().strip()
            if val.lower() in seen:
                continue
            seen.add(val.lower())
            results.append({
                "type":       etype,
                "name":       val,
                "value":      val,
                "tags":       ["ner", "regex"],
                "confidence": 85,
                "source":     "regex-ner",
                "notes":      "",
            })

    return results


def get_sentences(text: str) -> List[str]:
    nlp = _get_nlp()
    doc = nlp(text[:50_000])
    return [sent.text.strip() for sent in doc.sents if sent.text.strip()]


def ner_available() -> bool:
    try:
        _get_nlp()
        return True
    except NERModelError:
        return False
