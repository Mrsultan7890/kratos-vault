"""
Entity Type Classifier — sklearn TF-IDF + LogisticRegression
Auto-predicts entity type from value string.
Model is trained on first run and cached to disk.
"""
import re
import pickle
import os
from typing import Tuple, List
from pathlib import Path

_MODEL_PATH = Path.home() / ".kratos_vault" / "entity_classifier.pkl"
_MODEL_VERSION = 2  # bump to force retrain after training-data changes
_clf = None
_vectorizer = None

# Training data: (value_example, label)
_TRAINING_DATA = [
    # Email
    ("admin@example.com", "Email"), ("user.name+tag@domain.co.uk", "Email"),
    ("john.doe@gmail.com", "Email"), ("support@company.org", "Email"),
    ("noreply@service.net", "Email"), ("hacker@protonmail.com", "Email"),
    ("info@target.io", "Email"), ("contact@evil.onion", "Email"),

    # Phone
    ("+1-800-555-0199", "Phone"), ("(555) 867-5309", "Phone"),
    ("555.123.4567", "Phone"), ("+44 20 7946 0958", "Phone"),
    ("800-555-1234", "Phone"), ("+91 98765 43210", "Phone"),

    # IP
    ("192.168.1.1", "IP"), ("10.0.0.1", "IP"), ("8.8.8.8", "IP"),
    ("172.16.254.1", "IP"), ("203.0.113.42", "IP"), ("45.33.32.156", "IP"),
    ("185.220.101.1", "IP"), ("1.1.1.1", "IP"),

    # Domain
    ("evil.com", "Domain"), ("target.org", "Domain"), ("malware.net", "Domain"),
    ("phishing.io", "Domain"), ("c2server.ru", "Domain"), ("exfil.xyz", "Domain"),
    ("google.com", "Domain"), ("github.com", "Domain"),

    # URL
    ("https://evil.com/payload", "URL"), ("http://phishing.net/login", "URL"),
    ("https://github.com/user/repo", "URL"), ("http://192.168.1.1/admin", "URL"),
    ("https://t.me/channel", "URL"), ("http://onion.onion/path", "URL"),

    # Hash MD5/SHA
    ("d41d8cd98f00b204e9800998ecf8427e", "Hash"),
    ("da39a3ee5e6b4b0d3255bfef95601890afd80709", "Hash"),
    ("e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855", "Hash"),
    ("5d41402abc4b2a76b9719d911017c592", "Hash"),
    ("aabbccddeeff00112233445566778899aabbccdd", "Hash"),

    # Crypto
    ("1A1zP1eP5QGefi2DMPTfTL5SLmv7Divf", "Crypto"),
    ("3J98t1WpEZ73CNmQviecrnyiWrnqRhWNLy", "Crypto"),
    ("0x742d35Cc6634C0532925a3b844Bc454e4438f44e", "Crypto"),
    ("bc1qar0srrr7xfkvy5l643lydnw9re59gtzzwf5mdq", "Crypto"),

    # Handle / Username
    ("@john_doe", "Handle"), ("@hacker_x", "Handle"), ("john_doe_99", "Handle"),
    ("user#1234", "Handle"), ("@target_user", "Handle"), ("xX_h4cker_Xx", "Handle"),

    # Person
    ("John Smith", "Person"), ("Jane Doe", "Person"), ("Muhammad Ali", "Person"),
    ("Dr. Sarah Connor", "Person"), ("Robert Johnson Jr.", "Person"),
    ("Li Wei", "Person"), ("Ahmed Hassan", "Person"),

    # Address
    ("123 Main Street, New York", "Address"), ("London, UK", "Address"),
    ("Berlin, Germany", "Address"), ("45 Oak Ave, Chicago IL 60601", "Address"),
    ("Moscow, Russia", "Address"), ("Dubai, UAE", "Address"),

    # Document
    ("report.pdf", "Document"), ("evidence.docx", "Document"),
    ("data_dump.csv", "Document"), ("invoice_2024.xlsx", "Document"),
    ("malware_sample.exe", "Document"), ("notes.txt", "Document"),
    ("contract_final.doc", "Document"), ("budget_v2.pptx", "Document"),
    ("backup.zip", "Document"), ("logs.tar.gz", "Document"),

    # Image
    ("photo.jpg", "Image"), ("selfie.png", "Image"),
    ("cctv_2024_03_01.jpg", "Image"), ("profile_pic.jpeg", "Image"),
    ("screenshot_01.png", "Image"), ("evidence_photo.gif", "Image"),
    ("passport_scan.bmp", "Image"), ("whatsapp_img.webp", "Image"),
    ("drone_footage.tiff", "Image"), ("meme.png", "Image"),

    # Video / media
    ("cctv_footage.mp4", "Image"), ("recording.avi", "Image"),
    ("clip.mov", "Image"), ("surveillance.wmv", "Image"),
]


def _extract_features(value: str) -> str:
    """Create feature string from value for TF-IDF."""
    features = [value]
    # Add structural features
    if re.search(r"@.*\.", value):
        features.append("has_at_dot email_pattern")
    if re.match(r"\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}", value):
        features.append("ip_pattern four_octets")
    if re.match(r"https?://", value):
        features.append("url_scheme http")
    if re.match(r"[13][a-km-zA-HJ-NP-Z1-9]{25,34}$", value):
        features.append("bitcoin_address crypto")
    if re.match(r"0x[a-fA-F0-9]{40}$", value):
        features.append("ethereum_address crypto")
    if re.match(r"[a-fA-F0-9]{32,64}$", value):
        features.append("hex_hash digest")
    if re.match(r"\+?\d[\d\s\-().]{7,}", value):
        features.append("phone_digits telephone")
    if value.startswith("@"):
        features.append("at_prefix handle username")
    if re.search(r"\.(pdf|docx?|xlsx?|csv|exe|zip|rar|pptx|txt|tar|gz)$", value, re.I):
        features.append("file_extension document")
    if re.search(r"\.(jpe?g|png|gif|bmp|webp|tiff?|mp4|avi|mov|wmv|mkv)$", value, re.I):
        features.append("media_file image video photo")
    if len(value.split()) >= 2 and value[0].isupper():
        features.append("capitalized_words proper_noun person")
    return " ".join(features)


def _train():
    from sklearn.pipeline import Pipeline
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.linear_model import LogisticRegression

    X = [_extract_features(v) for v, _ in _TRAINING_DATA]
    y = [label for _, label in _TRAINING_DATA]

    pipeline = Pipeline([
        ("tfidf", TfidfVectorizer(analyzer="char_wb", ngram_range=(2, 4), max_features=5000)),
        ("clf",   LogisticRegression(max_iter=1000, C=5.0)),
    ])
    pipeline.fit(X, y)

    _MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(_MODEL_PATH, "wb") as f:
        pickle.dump({"version": _MODEL_VERSION, "pipeline": pipeline}, f)
    return pipeline


def _get_model():
    global _clf
    if _clf is not None:
        return _clf
    if _MODEL_PATH.exists():
        try:
            with open(_MODEL_PATH, "rb") as f:
                blob = pickle.load(f)
            if isinstance(blob, dict) and blob.get("version") == _MODEL_VERSION:
                _clf = blob["pipeline"]
                return _clf
        except Exception:
            pass
    _clf = _train()
    return _clf


def predict(value: str) -> Tuple[str, float]:
    """
    Predict entity type for a given value string.
    Returns (predicted_type, confidence_0_to_1)
    """
    model = _get_model()
    features = _extract_features(value)
    proba = model.predict_proba([features])[0]
    classes = model.classes_
    best_idx = int(proba.argmax())
    return classes[best_idx], float(proba[best_idx])


def predict_batch(values: List[str]) -> List[Tuple[str, float]]:
    model = _get_model()
    features = [_extract_features(v) for v in values]
    probas = model.predict_proba(features)
    classes = model.classes_
    return [(classes[int(p.argmax())], float(p.max())) for p in probas]


def retrain():
    """Force retrain and save model."""
    global _clf
    _clf = _train()
    return _clf
