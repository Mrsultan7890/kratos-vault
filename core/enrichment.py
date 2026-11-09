from PyQt6.QtCore import QThread, pyqtSignal, QTimer
from pathlib import Path
from datetime import datetime, timezone
import json
import threading

_status_lock = threading.Lock()
_remote_lookup_lock = threading.Lock()
_remote_lookups_enabled = False
_status_key = None
_MAX_FAILED_ATTEMPTS = 5
_RETRY_DELAYS_SECONDS = (300, 1800, 7200, 86400)

# Re-run 'done' entities after this many days (targets change over time)
RECHECK_DAYS = 30


# ── Enrichment status table (persisted to disk) ───────────────────────────
_STATUS_FILE = Path.home() / ".kratos_vault" / "enrichment_status.json"


def configure_status_encryption(password: str):
    global _status_key
    from core.crypto import decrypt_status, derive_status_key

    with _status_lock:
        _status_key = derive_status_key(password)
        if _STATUS_FILE.exists():
            raw = _STATUS_FILE.read_bytes()
            if raw.startswith(b"KVSTAT01"):
                data = decrypt_status(raw, _status_key)
            else:
                data = json.loads(raw.decode())
            _write_status_unlocked(data)


def set_remote_lookups_enabled(enabled: bool):
    global _remote_lookups_enabled
    with _remote_lookup_lock:
        _remote_lookups_enabled = bool(enabled)


def _read_status_unlocked() -> dict:
    if not _STATUS_FILE.exists():
        return {}
    raw = _STATUS_FILE.read_bytes()
    if raw.startswith(b"KVSTAT01"):
        if _status_key is None:
            raise RuntimeError("Unlock the vault before reading enrichment status")
        from core.crypto import decrypt_status
        return decrypt_status(raw, _status_key)
    return json.loads(raw.decode())


def _write_status_unlocked(data: dict):
    _STATUS_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = _STATUS_FILE.with_suffix(".tmp")
    if _status_key is None:
        encoded = json.dumps(data, indent=2).encode()
    else:
        from core.crypto import encrypt_status
        encoded = encrypt_status(data, _status_key)
    tmp.write_bytes(encoded)
    tmp.replace(_STATUS_FILE)
    _STATUS_FILE.chmod(0o600)


def _load_status() -> dict:
    with _status_lock:
        return _read_status_unlocked()


def _save_status(data: dict):
    with _status_lock:
        _write_status_unlocked(data)


def get_all_status() -> dict:
    return _load_status()


def set_entity_status(entity_id: str, status: str, detail: str = ""):
    with _status_lock:
        if _STATUS_FILE.exists():
            data = _read_status_unlocked()
        else:
            data = {}
        previous = data.get(entity_id, {})
        entry = {"status": status, "detail": detail,
                 "attempts": previous.get("attempts", 0)}
        now = datetime.now(timezone.utc).isoformat()
        if status == "running":
            entry["attempts"] += 1
            entry["last_attempt"] = now
        elif status == "done":
            entry["ts"] = now
        elif status == "failed":
            entry["last_attempt"] = previous.get("last_attempt", now)
            entry["failed_at"] = now
        data[entity_id] = entry
        _write_status_unlocked(data)


def get_entity_status(entity_id: str) -> dict:
    return _load_status().get(entity_id, {"status": "pending", "detail": ""})


def reset_stuck_statuses():
    """Call on app startup — resets any 'running' left from previous crash."""
    data = _load_status()
    changed = False
    for eid in data:
        if data[eid].get("status") == "running":
            data[eid] = {**data[eid], "status": "pending", "detail": ""}
            changed = True
    if changed:
        _save_status(data)


# ── Enrichment router ─────────────────────────────────────────────────────
import re as _re

_EMAIL_RE    = _re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}")
_PHONE_RE    = _re.compile(r"(?<!\d)(\+?(?:91|1|44|61|49|33|86|81)?[\s\-]?\(?\d{3,5}\)?[\s\-]?\d{3,4}[\s\-]?\d{4})(?!\d)")
_USERNAME_RE = _re.compile(r"(?<![\w@])@([a-zA-Z0-9_.]{2,})")

_ENRICHABLE_TYPES = ("Email", "Username", "Phone", "Person",
                     "URL", "IP", "Domain", "Crypto", "Handle",
                     "Hash", "Image", "Document", "Address", "Organization")


def should_enrich(entity: dict) -> bool:
    return entity.get("type") in _ENRICHABLE_TYPES


def extract_iocs_from_entity(entity: dict) -> dict:
    """
    For Person type — extract emails, phones, usernames from
    name + value + notes fields combined.
    Returns dict with lists: emails, phones, usernames
    """
    blob = " ".join([
        entity.get("value", ""),
        entity.get("name", ""),
        entity.get("notes", ""),
    ])
    emails    = list(dict.fromkeys(_EMAIL_RE.findall(blob)))
    phones    = list(dict.fromkeys(_PHONE_RE.findall(blob)))
    usernames = list(dict.fromkeys(_USERNAME_RE.findall(blob)))
    return {"emails": emails, "phones": phones, "usernames": usernames}


def enrich(entity: dict, progress_cb=None) -> dict:
    with _remote_lookup_lock:
        if not _remote_lookups_enabled:
            return {"error": "Remote OSINT lookups are disabled; enable them explicitly for this session"}
    etype = entity.get("type")
    value = entity.get("value", "")
    tags  = entity.get("tags", [])
    cb    = progress_cb or (lambda phase, step: None)

    if etype == "Email":
        cb("Layer 1 — Google profile lookup", "Connecting to Ghunt...")
        # value field mein email hona chahiye, fallback to IOC extraction
        import re as _re
        email_re = _re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}")
        if email_re.match(value.strip()):
            from core.enrichers.email_enricher import run
            return run(value.strip())
        else:
            # value is not an email — extract from all fields
            iocs = extract_iocs_from_entity(entity)
            if iocs["emails"]:
                from core.enrichers.email_enricher import run
                return run(iocs["emails"][0])
            return {"error": f"No valid email found in entity value: '{value}'"}

    elif etype == "Username":
        cb("Username OSINT", "Detecting platforms from tags...")
        from core.enrichers.username_enricher import run
        return run(value, tags=tags)

    elif etype == "Phone":
        cb("Phone OSINT", "libphonenumber lookup...")
        from core.enrichers.phone_enricher import run
        return run(value)

    elif etype == "Person":
        return enrich_person(entity, progress_cb=progress_cb)

    elif etype == "URL":
        cb("URL OSINT", "WHOIS + DNS + headers...")
        from core.enrichers.url_enricher import run
        return run(value)

    elif etype == "IP":
        cb("IP OSINT", "Geolocation + reverse DNS...")
        from core.enrichers.ip_enricher import run
        return run(value)

    elif etype == "Domain":
        cb("Domain OSINT", "WHOIS + DNS + crt.sh...")
        from core.enrichers.domain_enricher import run
        return run(value)

    elif etype == "Crypto":
        cb("Crypto OSINT", "Blockchain lookup...")
        from core.enrichers.crypto_enricher import run
        return run(value)

    elif etype == "Handle":
        cb("Handle OSINT", "Checking 12 platforms...")
        from core.enrichers.handle_enricher import run
        return run(value)

    elif etype == "Hash":
        cb("Hash OSINT", "VirusTotal + MalwareBazaar...")
        from core.enrichers.hash_enricher import run
        return run(value)

    elif etype == "Image":
        cb("Image OSINT", "EXIF + YOLO + TinEye...")
        from core.enrichers.image_enricher import run
        return run(value)

    elif etype == "Document":
        cb("Document OSINT", "Metadata extraction...")
        from core.enrichers.document_enricher import run
        return run(value)

    elif etype == "Address":
        cb("Address OSINT", "Geocoding via OpenStreetMap...")
        from core.enrichers.address_enricher import run
        return run(value)

    elif etype == "Organization":
        cb("Org OSINT", "OpenCorporates + dorks...")
        from core.enrichers.org_enricher import run
        return run(value)

    return {"error": f"No enricher for type: {etype}"}


def enrich_person(entity: dict, progress_cb=None) -> dict:
    cb   = progress_cb or (lambda phase, step: None)
    iocs = extract_iocs_from_entity(entity)
    combined = {
        "found": False,
        "tags": ["person-osint"],
        "platforms": {},
        "screenshots": [],
        "notes": f"=== Person OSINT: {entity.get('name', entity.get('value', ''))} ===\n",
    }

    for email in iocs["emails"]:
        cb("Email enrichment", f"Ghunt → {email}")
        from core.enrichers.email_enricher import run as email_run
        r = email_run(email)
        combined["platforms"][f"email_{email}"] = r
        combined["screenshots"] += r.get("screenshots", [])
        combined["tags"]        += r.get("tags", [])
        combined["notes"]       += f"\n{r.get('notes', '')}"
        if r.get("found"): combined["found"] = True

    for phone in iocs["phones"]:
        cb("Phone enrichment", f"libphonenumber + WhatsApp + Telegram → {phone}")
        from core.enrichers.phone_enricher import run as phone_run
        r = phone_run(phone)
        combined["platforms"][f"phone_{phone}"] = r
        combined["screenshots"] += r.get("screenshots", [])
        combined["tags"]        += r.get("tags", [])
        combined["notes"]       += f"\n{r.get('notes', '')}"
        if r.get("found"): combined["found"] = True

    for uname in iocs["usernames"]:
        cb("Username enrichment", f"Instagram + Telegram → @{uname}")
        from core.enrichers.username_enricher import run as uname_run
        r = uname_run(uname, tags=entity.get("tags", []))
        combined["platforms"][f"username_{uname}"] = r
        combined["screenshots"] += r.get("screenshots", [])
        combined["tags"]        += r.get("tags", [])
        combined["notes"]       += f"\n{r.get('notes', '')}"
        if r.get("found"): combined["found"] = True

    if not any([iocs["emails"], iocs["phones"], iocs["usernames"]]):
        combined["error"] = "No email/phone/username found in entity value or notes"

    combined["tags"] = list(dict.fromkeys(combined["tags"]))
    return combined


# ── Auto-checker: scans DB for pending entities and triggers enrichment ──
class EnrichmentAutoChecker(QThread):
    """
    Runs once on startup + every interval.
    Finds all enrichable entities with status 'pending' or 'failed'
    that have never been run, and queues them.
    """
    enqueue = pyqtSignal(str)   # entity_id to enrich
    status_update = pyqtSignal(str)  # log message for UI

    def __init__(self, db, interval_ms: int = 30_000, parent=None):
        super().__init__(parent)
        self.db          = db
        self.interval_ms = interval_ms
        self._stop_event = threading.Event()
        self._wake_event = threading.Event()

    def run(self):
        # Reset any stuck 'running' from previous crash
        reset_stuck_statuses()
        while not self._stop_event.is_set() and not self.isInterruptionRequested():
            self._scan()
            self._wake_event.wait(self.interval_ms / 1000)
            self._wake_event.clear()
            if self._stop_event.is_set():
                break

    def stop(self):
        self._stop_event.set()
        self._wake_event.set()
        self.requestInterruption()

    def scan_now(self):
        self._wake_event.set()

    def _scan(self):
        all_status = _load_status()
        cases = self.db.list_cases()
        pending = []
        stale = []
        enrichable_count = 0

        for case in cases:
            entities = self.db.list_entities(case["id"])
            for e in entities:
                if not should_enrich(e):
                    continue
                enrichable_count += 1
                s = all_status.get(e["id"], {})
                status = s.get("status", "pending")
                # Only queue truly untouched entities (never run)
                if status == "pending":
                    pending.append(e["id"])
                elif status == "failed" and _failed_retry_due(s):
                    pending.append(e["id"])
                elif status == "done" and _is_stale(s.get("ts")):
                    stale.append(e["id"])

        if pending or stale:
            msg = f"🔍 Auto-checker: {len(pending)} pending, {len(stale)} stale (> {RECHECK_DAYS}d)"
            self.status_update.emit(msg)
            for eid in stale:
                # reset so the done-check in _trigger_enrichment doesn't skip
                set_entity_status(eid, "pending", f"Stale — re-checking (>{RECHECK_DAYS}d)")
            for eid in pending + stale:
                self.enqueue.emit(eid)
        elif enrichable_count:
            self.status_update.emit("✅ Auto-checker: all entities enriched")


def _is_stale(ts) -> bool:
    """
    True only when a 'done' enrichment carries a timestamp older than
    RECHECK_DAYS. Entries without a timestamp (pre-scheduling data) are never
    auto-requeued — use the manual Re-run button for those.
    """
    if not ts:
        return False


def _failed_retry_due(status: dict) -> bool:
    attempts = status.get("attempts", 0)
    if not isinstance(attempts, int) or attempts >= _MAX_FAILED_ATTEMPTS:
        return False
    last_attempt = status.get("last_attempt")
    if not last_attempt:
        return True
    try:
        attempted_at = datetime.fromisoformat(last_attempt)
        if attempted_at.tzinfo is None:
            attempted_at = attempted_at.replace(tzinfo=timezone.utc)
        delay = _RETRY_DELAYS_SECONDS[min(max(attempts - 1, 0), len(_RETRY_DELAYS_SECONDS) - 1)]
        return (datetime.now(timezone.utc) - attempted_at).total_seconds() >= delay
    except (ValueError, TypeError):
        return False
    try:
        done_at = datetime.fromisoformat(ts)
        if done_at.tzinfo is None:
            done_at = done_at.replace(tzinfo=timezone.utc)
        age_days = (datetime.now(timezone.utc) - done_at).days
        return age_days >= RECHECK_DAYS
    except (ValueError, TypeError):
        return False


# ── QThread Worker ────────────────────────────────────────────────────────
class EnrichmentWorker(QThread):
    started_signal  = pyqtSignal(str, str)   # entity_id, value
    finished_signal = pyqtSignal(str, dict)  # entity_id, result
    error_signal    = pyqtSignal(str, str)   # entity_id, error_msg
    phase_signal    = pyqtSignal(str, str)   # entity_id, phase description
    step_signal     = pyqtSignal(str, str)   # entity_id, step description

    def __init__(self, db, entity: dict, parent=None):
        super().__init__(parent)
        self.db     = db
        self.entity = entity

    def run(self):
        eid   = self.entity["id"]
        value = self.entity.get("value", "")
        etype = self.entity.get("type", "")

        self.started_signal.emit(eid, value)
        set_entity_status(eid, "running", "Enrichment in progress...")

        try:
            self.phase_signal.emit(eid, f"[{etype}] Routing to enricher...")
            result = enrich(self.entity, progress_cb=lambda phase, step: (
                self.phase_signal.emit(eid, phase),
                self.step_signal.emit(eid, step)
            ))

            if result.get("error"):
                set_entity_status(eid, "failed", result["error"])
                self.error_signal.emit(eid, result["error"])
                return

            self.phase_signal.emit(eid, "Saving results...")
            _apply_result(self.db, self.entity, result)
            set_entity_status(eid, "done", "Enrichment complete")
            self.finished_signal.emit(eid, result)

        except Exception as e:
            msg = str(e)
            set_entity_status(eid, "failed", msg)
            self.error_signal.emit(eid, msg)


def _apply_result(db, entity: dict, result: dict):
    """Write enrichment data back to entity — always re-fetch fresh from DB."""
    eid     = entity["id"]
    case_id = entity["case_id"]

    # Re-fetch fresh to avoid stale data from long-running worker
    fresh = db.get_entity(eid)
    if not fresh:
        return

    existing_notes = fresh.get("notes") or ""
    existing_tags  = fresh.get("tags") or []
    conf           = fresh.get("confidence", 50)

    new_notes = result.get("notes", "")
    new_tags  = result.get("tags", [])

    # Don't append if same notes already exist (re-run protection)
    if new_notes and new_notes[:50] in existing_notes:
        merged_notes = existing_notes
    else:
        merged_notes = (existing_notes + "\n\n" + new_notes).strip() if new_notes else existing_notes
    merged_tags  = list(dict.fromkeys(existing_tags + new_tags))
    if result.get("found"):
        conf = min(conf + 20, 95)

    db.update_entity(eid, notes=merged_notes, tags=merged_tags, confidence=conf)

    for ss_path in result.get("screenshots", []):
        _add_screenshot(db, case_id, eid, ss_path, entity)

    platforms_found = [p for p, d in result.get("platforms", {}).items() if isinstance(d, dict) and d.get("found")]
    detail = f"Found on: {', '.join(platforms_found)}" if platforms_found else "No platforms found"
    db.add_event(case_id, "enrichment_done",
                 f"Enriched: {entity.get('value', '')}",
                 detail=detail)


def _add_screenshot(db, case_id: str, entity_id: str, ss_path: str, entity: dict):
    from pathlib import Path as P
    import hashlib
    import logging

    path = P(ss_path)
    if not path.exists():
        return
    try:
        data = path.read_bytes()
        sha  = hashlib.sha256(data).hexdigest()
        name = f"[OSINT] {entity.get('value', '')} — {path.stem}.png"
        db.create_media(
            case_id, name, "image/png", len(data), sha, data,
            notes=f"Auto-captured screenshot for entity: {entity.get('value', '')}"
        )
    except OSError as exc:
        logging.getLogger(__name__).warning("Could not import enrichment screenshot: %s", exc)
    finally:
        path.unlink(missing_ok=True)
