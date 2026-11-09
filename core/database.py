import sqlite3 as _stdlib_sqlite3
import json
import re as _re
import uuid
import threading
import os
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from sqlcipher3 import dbapi2 as sqlite3
from core.crypto import PBKDF2_ITERATIONS

DB_PATH = Path.home() / ".kratos_vault" / "vault.db"
_SQLITE_HEADER = b"SQLite format 3\x00"
_MAX_RECORDS = 100_000
_MAX_MEDIA_ITEMS = 2_000


def _now():
    return datetime.now(timezone.utc).isoformat()


def _uuid():
    return str(uuid.uuid4())


def _validate_case_payload(payload: dict):
    """Reject malformed or oversized imports before they can alter the vault."""
    if not isinstance(payload, dict) or not isinstance(payload.get("case"), dict):
        raise ValueError("Invalid case export: missing case record")

    case = payload["case"]
    required_case_fields = ("id", "name", "description", "status", "priority", "created", "updated")
    if any(not isinstance(case.get(key), str) for key in required_case_fields):
        raise ValueError("Invalid case export: case metadata is incomplete")

    list_limits = {
        "entities": _MAX_RECORDS,
        "edges": _MAX_RECORDS,
        "timeline": _MAX_RECORDS,
        "notes": _MAX_RECORDS,
        "audit_log": _MAX_RECORDS,
        "media": _MAX_MEDIA_ITEMS,
    }
    for key, limit in list_limits.items():
        rows = payload.get(key, [])
        if not isinstance(rows, list) or len(rows) > limit:
            raise ValueError(f"Invalid case export: {key} must contain at most {limit} records")

    entities = payload.get("entities", [])
    entity_ids = set()
    for entity in entities:
        if not isinstance(entity, dict) or entity.get("case_id") != case["id"]:
            raise ValueError("Invalid case export: entity belongs to a different case")
        for key in ("id", "type", "name", "value", "notes", "source", "created", "updated"):
            if not isinstance(entity.get(key), str):
                raise ValueError(f"Invalid case export: entity {key} must be text")
        if entity["id"] in entity_ids:
            raise ValueError("Invalid case export: duplicate entity ID")
        entity_ids.add(entity["id"])
        if not isinstance(entity.get("tags", []), list) or not all(
                isinstance(tag, str) for tag in entity.get("tags", [])):
            raise ValueError("Invalid case export: entity tags must be text")
        if not isinstance(entity.get("linked_to", []), list) or not all(
                isinstance(link, str) for link in entity.get("linked_to", [])):
            raise ValueError("Invalid case export: entity links must be IDs")
        confidence = entity.get("confidence")
        if not isinstance(confidence, int) or not 0 <= confidence <= 100:
            raise ValueError("Invalid case export: confidence must be between 0 and 100")

    for edge in payload.get("edges", []):
        if (not isinstance(edge, dict) or edge.get("case_id") != case["id"]
                or edge.get("source") not in entity_ids or edge.get("target") not in entity_ids
                or not isinstance(edge.get("id"), str)):
            raise ValueError("Invalid case export: edge references an unknown entity")

    for key in ("timeline", "notes", "audit_log"):
        for row in payload.get(key, []):
            if not isinstance(row, dict) or row.get("case_id") != case["id"]:
                raise ValueError(f"Invalid case export: invalid {key} record")

    for note in payload.get("notes", []):
        if (not isinstance(note.get("id"), str) or not isinstance(note.get("title"), str)
                or not isinstance(note.get("content", ""), str)
                or not isinstance(note.get("tags", []), list)):
            raise ValueError("Invalid case export: malformed note")

    for event in payload.get("timeline", []):
        if (not isinstance(event.get("id"), str)
                or not isinstance(event.get("event_type"), str)
                or not isinstance(event.get("title"), str)
                or not isinstance(event.get("detail", ""), str)
                or not isinstance(event.get("meta", {}), dict)):
            raise ValueError("Invalid case export: malformed timeline event")

    for entry in payload.get("audit_log", []):
        if any(not isinstance(entry.get(key), str)
               for key in ("id", "ts", "action", "target", "details", "prev_hash", "hash")):
            raise ValueError("Invalid case export: malformed audit entry")
    if payload.get("audit_log"):
        import hashlib
        previous = "0" * 64
        for entry in payload["audit_log"]:
            expected = hashlib.sha256(
                f"{previous}|{entry['ts']}|{entry['action']}|{entry['target']}|"
                f"{entry['details']}".encode()
            ).hexdigest()
            if entry["prev_hash"] != previous or entry["hash"] != expected:
                raise ValueError("Invalid case export: audit chain verification failed")
            previous = entry["hash"]

    total_media_bytes = 0
    for media in payload.get("media", []):
        if (not isinstance(media, dict) or media.get("case_id") != case["id"]
                or not isinstance(media.get("id"), str)
                or not isinstance(media.get("name"), str)
                or not isinstance(media.get("hash_sha256"), str)
                or len(media["hash_sha256"]) != 64
                or not isinstance(media.get("data", ""), str)):
            raise ValueError("Invalid case export: malformed media record")
        data = media.get("data", "")
        if len(data) % 2:
            raise ValueError("Invalid case export: media data is malformed")
        total_media_bytes += len(data) // 2
        if total_media_bytes > 480 * 1024 * 1024:
            raise ValueError("Invalid case export: media exceeds the import size limit")
        try:
            bytes.fromhex(data)
        except ValueError as exc:
            raise ValueError("Invalid case export: media data is not valid hexadecimal") from exc


class Database:
    def __init__(self, path: Path = DB_PATH, password: str | None = None):
        if not password:
            raise ValueError("A vault password is required")
        self.path = path
        if not self.path.exists() and len(password) < 12:
            raise ValueError("New vault passwords must contain at least 12 characters")
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.chmod(self.path.parent, 0o700)
        self._lock = threading.Lock()
        if self.path.exists():
            with self.path.open("rb") as vault_file:
                header = vault_file.read(len(_SQLITE_HEADER))
            if header == _SQLITE_HEADER:
                if len(password) < 12:
                    raise ValueError("Use at least 12 characters to encrypt this existing vault")
                self._migrate_plaintext_vault(password)
        self._password = password
        old_umask = os.umask(0o077)
        try:
            self._conn = sqlite3.connect(str(self.path), check_same_thread=False)
        finally:
            os.umask(old_umask)
        self._configure_connection(self._conn, password)
        if self.path.exists():
            os.chmod(self.path, 0o600)
        self._conn.row_factory = sqlite3.Row
        try:
            self._conn.execute("SELECT count(*) FROM sqlite_master").fetchone()
        except sqlite3.DatabaseError as exc:
            self._conn.close()
            raise ValueError("Could not unlock the vault; check the password or vault file") from exc
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._migrate()

    @staticmethod
    def _configure_connection(conn, password: str):
        quoted = "'" + password.replace("'", "''") + "'"
        conn.execute(f"PRAGMA key = {quoted}")
        conn.execute(f"PRAGMA kdf_iter = {PBKDF2_ITERATIONS}")
        conn.execute("PRAGMA cipher_memory_security = ON")

    def _migrate_plaintext_vault(self, password: str):
        """Encrypt a pre-SQLCipher vault atomically, retaining the original on failure."""
        temp_path = self.path.with_name(f".{self.path.name}.{uuid.uuid4().hex}.tmp")
        source = sqlite3.connect(str(self.path), check_same_thread=False)
        try:
            escaped_path = str(temp_path).replace("'", "''")
            escaped_password = password.replace("'", "''")
            source.execute(
                f"ATTACH DATABASE '{escaped_path}' AS encrypted KEY '{escaped_password}'")
            source.execute(f"PRAGMA encrypted.kdf_iter = {PBKDF2_ITERATIONS}")
            source.execute("SELECT sqlcipher_export('encrypted')")
            source.execute("DETACH DATABASE encrypted")
            source.close()

            check = sqlite3.connect(str(temp_path))
            self._configure_connection(check, password)
            check.execute("SELECT count(*) FROM sqlite_master").fetchone()
            check.close()
            os.chmod(temp_path, 0o600)
            os.replace(temp_path, self.path)
            for suffix in ("-wal", "-shm"):
                Path(f"{self.path}{suffix}").unlink(missing_ok=True)
        except Exception:
            source.close()
            temp_path.unlink(missing_ok=True)
            raise

    def _exec(self, sql, params=()):
        """Thread-safe execute + commit."""
        with self._lock:
            self._conn.execute(sql, params)
            self._conn.commit()

    @contextmanager
    def _tx(self):
        """
        Serialize write transactions. Enrichment/ML worker threads and the UI
        thread share one connection — without this lock, a commit from one
        thread can flush another thread's half-finished statement.
        """
        with self._lock:
            try:
                yield self._conn
                self._conn.commit()
            except Exception:
                self._conn.rollback()
                raise

    @staticmethod
    def _check_cols(kwargs):
        """Column names are code-controlled, but guard anyway before f-string SQL."""
        for k in kwargs:
            if not _re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", k):
                raise ValueError(f"Invalid column name: {k!r}")

    def _migrate(self):
        c = self._conn
        c.executescript("""
            CREATE TABLE IF NOT EXISTS cases (
                id          TEXT PRIMARY KEY,
                name        TEXT NOT NULL,
                description TEXT DEFAULT '',
                status      TEXT DEFAULT 'Active',
                priority    TEXT DEFAULT 'Medium',
                created     TEXT NOT NULL,
                updated     TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS entities (
                id          TEXT PRIMARY KEY,
                case_id     TEXT NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
                type        TEXT NOT NULL,
                name        TEXT NOT NULL,
                value       TEXT NOT NULL,
                notes       TEXT DEFAULT '',
                tags        TEXT DEFAULT '[]',
                linked_to   TEXT DEFAULT '[]',
                confidence  INTEGER DEFAULT 50,
                source      TEXT DEFAULT '',
                created     TEXT NOT NULL,
                updated     TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS edges (
                id          TEXT PRIMARY KEY,
                case_id     TEXT NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
                source      TEXT NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
                target      TEXT NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
                label       TEXT DEFAULT '',
                weight      INTEGER DEFAULT 1,
                created     TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS media (
                id          TEXT PRIMARY KEY,
                case_id     TEXT NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
                name        TEXT NOT NULL,
                mime_type   TEXT DEFAULT '',
                size        INTEGER DEFAULT 0,
                hash_sha256 TEXT NOT NULL,
                data        BLOB NOT NULL,
                exif        TEXT DEFAULT '{}',
                notes       TEXT DEFAULT '',
                created     TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS timeline (
                id          TEXT PRIMARY KEY,
                case_id     TEXT NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
                event_type  TEXT NOT NULL,
                title       TEXT NOT NULL,
                detail      TEXT DEFAULT '',
                meta        TEXT DEFAULT '{}',
                created     TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS notes (
                id          TEXT PRIMARY KEY,
                case_id     TEXT NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
                title       TEXT NOT NULL,
                content     TEXT DEFAULT '',
                tags        TEXT DEFAULT '[]',
                created     TEXT NOT NULL,
                updated     TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS audit_log (
                id        TEXT PRIMARY KEY,
                ts        TEXT NOT NULL,
                case_id   TEXT DEFAULT '',
                action    TEXT NOT NULL,
                target    TEXT DEFAULT '',
                details   TEXT DEFAULT '',
                prev_hash TEXT DEFAULT '',
                hash      TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_entities_case ON entities(case_id);
            CREATE INDEX IF NOT EXISTS idx_edges_case    ON edges(case_id);
            CREATE INDEX IF NOT EXISTS idx_media_case    ON media(case_id);
            CREATE INDEX IF NOT EXISTS idx_timeline_case ON timeline(case_id);
            CREATE INDEX IF NOT EXISTS idx_notes_case    ON notes(case_id);
            CREATE INDEX IF NOT EXISTS idx_audit_case    ON audit_log(case_id);
        """)
        c.commit()

    def close(self):
        with self._lock:
            self._conn.commit()
            self._conn.close()

    def backup(self, keep: int = 5, backups_dir: Path = None) -> Path:
        """
        Consistent snapshot of the live DB via SQLite's backup API (WAL-safe).
        Rotates old snapshots, keeping the newest `keep`.
        """
        bdir = Path(backups_dir or (self.path.parent / "backups"))
        bdir.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.chmod(bdir, 0o700)
        stamp = _now().replace(":", "").replace(".", "-").replace("+", "Z")
        dest_path = bdir / f"vault-{stamp}.db"
        dest = sqlite3.connect(str(dest_path))
        self._configure_connection(dest, self._password)
        try:
            with self._lock:
                self._conn.commit()
                self._conn.backup(dest)
        finally:
            dest.close()
        os.chmod(dest_path, 0o600)
        snapshots = sorted(bdir.glob("vault-*.db"))
        for old in snapshots[:-keep]:
            old.unlink(missing_ok=True)
        return dest_path

    def export_all_cases(self) -> dict:
        """Every case in one payload — for encrypted full-vault backups."""
        return {
            "version": "2.1",
            "kind": "full_vault",
            "cases": [self.export_case(c["id"]) for c in self.list_cases()],
        }

    # ── Audit log (tamper-evident hash chain, per case) ────────────────────
    def _audit(self, case_id: str, action: str, target: str = "", details: str = ""):
        """Append-only chain-of-custody entry. Each row hashes the previous
        row of the SAME case, so any edit/delete breaks verification."""
        import hashlib
        ts = _now()
        with self._tx() as c:
            prev = c.execute(
                "SELECT hash FROM audit_log WHERE case_id=? ORDER BY rowid DESC LIMIT 1",
                (case_id or "",)).fetchone()
            prev_hash = prev["hash"] if prev else "0" * 64
            row_hash = hashlib.sha256(
                f"{prev_hash}|{ts}|{action}|{target}|{details}".encode()).hexdigest()
            c.execute(
                "INSERT INTO audit_log (id,ts,case_id,action,target,details,prev_hash,hash) "
                "VALUES (?,?,?,?,?,?,?,?)",
                (_uuid(), ts, case_id or "", action, target, details, prev_hash, row_hash))

    def list_audit(self, case_id=None):
        if case_id:
            rows = self._conn.execute(
                "SELECT * FROM audit_log WHERE case_id=? ORDER BY rowid ASC",
                (case_id,)).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT * FROM audit_log ORDER BY rowid ASC").fetchall()
        return [dict(r) for r in rows]

    def verify_audit_chain(self, case_id=None):
        """Recompute every hash. Returns (ok: bool, broken_at_row_id: str|None)."""
        import hashlib
        prev_hashes = {}
        for row in self.list_audit(case_id):
            scope = row["case_id"] or ""
            prev_hash = prev_hashes.get(scope, "0" * 64)
            expected = hashlib.sha256(
                f"{prev_hash}|{row['ts']}|{row['action']}|{row['target']}|{row['details']}".encode()
            ).hexdigest()
            if row["prev_hash"] != prev_hash or row["hash"] != expected:
                return False, row["id"]
            prev_hashes[scope] = row["hash"]
        return True, None

    # ── Cases ──────────────────────────────────────────────────────────────
    def create_case(self, name, description="", status="Active", priority="Medium"):
        row = {"id": _uuid(), "name": name, "description": description,
               "status": status, "priority": priority,
               "created": _now(), "updated": _now()}
        with self._tx() as c:
            c.execute(
                "INSERT INTO cases VALUES (:id,:name,:description,:status,:priority,:created,:updated)", row)
        self.add_event(row["id"], "case_created", f"Case '{name}' created")
        self._audit(row["id"], "case_created", target=name,
                    details=f"status={status}, priority={priority}")
        return row

    def list_cases(self):
        return [dict(r) for r in self._conn.execute(
            "SELECT * FROM cases ORDER BY updated DESC").fetchall()]

    def get_case(self, case_id):
        r = self._conn.execute("SELECT * FROM cases WHERE id=?", (case_id,)).fetchone()
        return dict(r) if r else None

    def update_case(self, case_id, **kwargs):
        self._check_cols(kwargs)
        kwargs["updated"] = _now()
        sets = ", ".join(f"{k}=?" for k in kwargs)
        with self._tx() as c:
            c.execute(f"UPDATE cases SET {sets} WHERE id=?",
                      (*kwargs.values(), case_id))
        self._audit(case_id, "case_updated",
                    target=case_id,
                    details="changed: " + ", ".join(sorted(k for k in kwargs if k != "updated")))

    def delete_case(self, case_id):
        case = self.get_case(case_id)
        with self._tx() as c:
            c.execute("DELETE FROM cases WHERE id=?", (case_id,))
        # Audit row survives the case — deletion itself is on the record
        self._audit(case_id, "case_deleted",
                    target=case["name"] if case else case_id)

    def case_stats(self, case_id):
        e = self._conn.execute("SELECT COUNT(*) FROM entities WHERE case_id=?", (case_id,)).fetchone()[0]
        ed = self._conn.execute("SELECT COUNT(*) FROM edges WHERE case_id=?", (case_id,)).fetchone()[0]
        m = self._conn.execute("SELECT COUNT(*) FROM media WHERE case_id=?", (case_id,)).fetchone()[0]
        t = self._conn.execute("SELECT COUNT(*) FROM timeline WHERE case_id=?", (case_id,)).fetchone()[0]
        n = self._conn.execute("SELECT COUNT(*) FROM notes WHERE case_id=?", (case_id,)).fetchone()[0]
        return {"entities": e, "edges": ed, "media": m, "events": t, "notes": n}

    # ── Entities ───────────────────────────────────────────────────────────
    def create_entity(self, case_id, type_, name, value, notes="", tags=None,
                      confidence=50, source=""):
        # Duplicate guard — same type + value in this case returns the existing row
        dup = self._conn.execute(
            "SELECT * FROM entities WHERE case_id=? AND type=? AND value=?",
            (case_id, type_, value)).fetchone()
        if dup:
            d = dict(dup)
            d["tags"] = json.loads(d["tags"] or "[]")
            d["linked_to"] = json.loads(d["linked_to"] or "[]")
            d["duplicate"] = True
            return d
        row = {"id": _uuid(), "case_id": case_id, "type": type_,
               "name": name, "value": value, "notes": notes,
               "tags": json.dumps(tags or []), "linked_to": "[]",
               "confidence": confidence, "source": source,
               "created": _now(), "updated": _now()}
        with self._tx() as c:
            c.execute(
                "INSERT INTO entities VALUES (:id,:case_id,:type,:name,:value,:notes,"
                ":tags,:linked_to,:confidence,:source,:created,:updated)", row)
        self.add_event(case_id, "entity_added", f"Entity added: {name}",
                       detail=f"Type: {type_} | Value: {value}")
        self._audit(case_id, "entity_created", target=row["id"],
                    details=f"{type_}: {name} = {value}")
        row["tags"] = tags or []
        row["linked_to"] = []
        return row

    def list_entities(self, case_id, type_filter=None, search=None):
        q = "SELECT * FROM entities WHERE case_id=?"
        params = [case_id]
        if type_filter:
            q += " AND type=?"
            params.append(type_filter)
        if search:
            q += " AND (name LIKE ? OR value LIKE ? OR notes LIKE ?)"
            s = f"%{search}%"
            params += [s, s, s]
        q += " ORDER BY created DESC"
        rows = self._conn.execute(q, params).fetchall()
        result = []
        for r in rows:
            d = dict(r)
            d["tags"] = json.loads(d["tags"] or "[]")
            d["linked_to"] = json.loads(d["linked_to"] or "[]")
            result.append(d)
        return result

    def get_entity(self, entity_id):
        r = self._conn.execute("SELECT * FROM entities WHERE id=?", (entity_id,)).fetchone()
        if not r:
            return None
        d = dict(r)
        d["tags"] = json.loads(d["tags"] or "[]")
        d["linked_to"] = json.loads(d["linked_to"] or "[]")
        return d

    def update_entity(self, entity_id, **kwargs):
        self._check_cols(kwargs)
        audit_keys = ", ".join(sorted(k for k in kwargs if k != "updated"))
        if "tags" in kwargs:
            kwargs["tags"] = json.dumps(kwargs["tags"])
        if "linked_to" in kwargs:
            kwargs["linked_to"] = json.dumps(kwargs["linked_to"])
        kwargs["updated"] = _now()
        sets = ", ".join(f"{k}=?" for k in kwargs)
        with self._tx() as c:
            c.execute(f"UPDATE entities SET {sets} WHERE id=?",
                      (*kwargs.values(), entity_id))
        if audit_keys:
            self._audit(self.get_entity_case(entity_id), "entity_updated",
                        target=entity_id, details="changed: " + audit_keys)

    def get_entity_case(self, entity_id):
        r = self._conn.execute("SELECT case_id FROM entities WHERE id=?",
                               (entity_id,)).fetchone()
        return r["case_id"] if r else ""

    def delete_entity(self, entity_id):
        ent = self.get_entity(entity_id)
        with self._tx() as c:
            c.execute("DELETE FROM edges WHERE source=? OR target=?",
                      (entity_id, entity_id))
            c.execute("DELETE FROM entities WHERE id=?", (entity_id,))
        if ent:
            self._audit(ent["case_id"], "entity_deleted", target=entity_id,
                        details=f"{ent['type']}: {ent['name']} = {ent['value']}")

    # ── Edges ──────────────────────────────────────────────────────────────
    def create_edge(self, case_id, source, target, label="", weight=1):
        existing = self._conn.execute(
            "SELECT id FROM edges WHERE case_id=? AND source=? AND target=?",
            (case_id, source, target)).fetchone()
        if existing:
            return dict(existing)
        row = {"id": _uuid(), "case_id": case_id, "source": source,
               "target": target, "label": label, "weight": weight, "created": _now()}
        with self._tx() as c:
            c.execute(
                "INSERT INTO edges VALUES (:id,:case_id,:source,:target,:label,:weight,:created)", row)
        self._sync_linked_to(source, target)
        self._audit(case_id, "edge_created", target=row["id"],
                    details=f"{source} -> {target} ({label})")
        return row

    def _sync_linked_to(self, source, target):
        """Keep entities.linked_to in sync with edges (both directions)."""
        for a, b in ((source, target), (target, source)):
            e = self.get_entity(a)
            if e and b not in e["linked_to"]:
                self.update_entity(a, linked_to=e["linked_to"] + [b])

    def list_edges(self, case_id):
        return [dict(r) for r in self._conn.execute(
            "SELECT * FROM edges WHERE case_id=?", (case_id,)).fetchall()]

    def delete_edge(self, edge_id):
        edge = self._conn.execute(
            "SELECT source, target FROM edges WHERE id=?", (edge_id,)).fetchone()
        with self._tx() as c:
            c.execute("DELETE FROM edges WHERE id=?", (edge_id,))
        if edge:
            for a, b in ((edge["source"], edge["target"]),
                         (edge["target"], edge["source"])):
                e = self.get_entity(a)
                if e and b in e["linked_to"]:
                    self.update_entity(a, linked_to=[x for x in e["linked_to"] if x != b])
            self._audit(self.get_entity_case(edge["source"]) if self.get_entity(edge["source"])
                        else "", "edge_deleted", target=edge_id,
                        details=f"{edge['source']} -> {edge['target']}")

    # ── Media ──────────────────────────────────────────────────────────────
    def create_media(self, case_id, name, mime_type, size, hash_sha256, data, exif=None, notes=""):
        existing = self._conn.execute(
            "SELECT id FROM media WHERE case_id=? AND hash_sha256=?",
            (case_id, hash_sha256)).fetchone()
        if existing:
            return None  # duplicate
        row = {"id": _uuid(), "case_id": case_id, "name": name,
               "mime_type": mime_type, "size": size, "hash_sha256": hash_sha256,
               "data": data, "exif": json.dumps(exif or {}), "notes": notes,
               "created": _now()}
        with self._tx() as c:
            c.execute(
                "INSERT INTO media VALUES (:id,:case_id,:name,:mime_type,:size,"
                ":hash_sha256,:data,:exif,:notes,:created)", row)
        self.add_event(case_id, "media_added", f"Media added: {name}",
                       detail=f"SHA-256: {hash_sha256[:16]}...")
        self._audit(case_id, "media_created", target=row["id"],
                    details=f"{name} ({mime_type}, {size}B, sha256={hash_sha256[:16]}...)")
        row["exif"] = exif or {}
        return row

    def list_media(self, case_id):
        rows = self._conn.execute(
            "SELECT id,case_id,name,mime_type,size,hash_sha256,exif,notes,created "
            "FROM media WHERE case_id=? ORDER BY created DESC", (case_id,)).fetchall()
        result = []
        for r in rows:
            d = dict(r)
            d["exif"] = json.loads(d["exif"] or "{}")
            result.append(d)
        return result

    def get_media_data(self, media_id):
        r = self._conn.execute("SELECT data FROM media WHERE id=?", (media_id,)).fetchone()
        return r[0] if r else None

    def delete_media(self, media_id):
        r = self._conn.execute(
            "SELECT case_id, name FROM media WHERE id=?", (media_id,)).fetchone()
        with self._tx() as c:
            c.execute("DELETE FROM media WHERE id=?", (media_id,))
        if r:
            self._audit(r["case_id"], "media_deleted", target=media_id,
                        details=r["name"])

    # ── Timeline ───────────────────────────────────────────────────────────
    def add_event(self, case_id, event_type, title, detail="", meta=None):
        row = {"id": _uuid(), "case_id": case_id, "event_type": event_type,
               "title": title, "detail": detail,
               "meta": json.dumps(meta or {}), "created": _now()}
        with self._tx() as c:
            c.execute(
                "INSERT INTO timeline VALUES (:id,:case_id,:event_type,:title,:detail,:meta,:created)", row)
        return row

    def list_events(self, case_id):
        rows = self._conn.execute(
            "SELECT * FROM timeline WHERE case_id=? ORDER BY created DESC",
            (case_id,)).fetchall()
        result = []
        for r in rows:
            d = dict(r)
            d["meta"] = json.loads(d["meta"] or "{}")
            result.append(d)
        return result

    # ── Notes ──────────────────────────────────────────────────────────────
    def create_note(self, case_id, title, content="", tags=None):
        row = {"id": _uuid(), "case_id": case_id, "title": title,
               "content": content, "tags": json.dumps(tags or []),
               "created": _now(), "updated": _now()}
        with self._tx() as c:
            c.execute(
                "INSERT INTO notes VALUES (:id,:case_id,:title,:content,:tags,:created,:updated)", row)
        self._audit(case_id, "note_created", target=row["id"], details=title)
        row["tags"] = tags or []
        return row

    def list_notes(self, case_id):
        rows = self._conn.execute(
            "SELECT * FROM notes WHERE case_id=? ORDER BY updated DESC", (case_id,)).fetchall()
        result = []
        for r in rows:
            d = dict(r)
            d["tags"] = json.loads(d["tags"] or "[]")
            result.append(d)
        return result

    def update_note(self, note_id, **kwargs):
        self._check_cols(kwargs)
        if "tags" in kwargs:
            kwargs["tags"] = json.dumps(kwargs["tags"])
        kwargs["updated"] = _now()
        sets = ", ".join(f"{k}=?" for k in kwargs)
        with self._tx() as c:
            c.execute(f"UPDATE notes SET {sets} WHERE id=?",
                      (*kwargs.values(), note_id))
        r = self._conn.execute("SELECT case_id FROM notes WHERE id=?",
                               (note_id,)).fetchone()
        if r:
            self._audit(r["case_id"], "note_updated", target=note_id,
                        details="changed: " + ", ".join(sorted(k for k in kwargs if k != "updated")))

    def delete_note(self, note_id):
        r = self._conn.execute(
            "SELECT case_id, title FROM notes WHERE id=?", (note_id,)).fetchone()
        with self._tx() as c:
            c.execute("DELETE FROM notes WHERE id=?", (note_id,))
        if r:
            self._audit(r["case_id"], "note_deleted", target=note_id,
                        details=r["title"])

    # ── Export / Import ────────────────────────────────────────────────────
    def export_case(self, case_id):
        case = self.get_case(case_id)
        entities = self.list_entities(case_id)
        edges = self.list_edges(case_id)
        events = self.list_events(case_id)
        notes = self.list_notes(case_id)
        media_meta = self.list_media(case_id)
        media_data = []
        for m in media_meta:
            raw = self.get_media_data(m["id"])
            media_data.append({**m, "data": raw.hex() if raw else ""})
        self._audit(case_id, "case_exported", target=case_id,
                    details=f"{len(entities)} entities, {len(media_data)} media")
        return {
            "version": "2.1",
            "case": case,
            "entities": entities,
            "edges": edges,
            "timeline": events,
            "notes": notes,
            "media": media_data,
            "audit_log": self.list_audit(case_id),
        }

    def import_case(self, payload):
        return self.import_cases([payload])[0]

    def import_cases(self, payloads):
        if not isinstance(payloads, list) or len(payloads) > 1_000:
            raise ValueError("Invalid full-vault export: case count exceeds the import limit")
        for payload in payloads:
            _validate_case_payload(payload)
        case_ids = [payload["case"]["id"] for payload in payloads]
        if len(set(case_ids)) != len(case_ids):
            raise ValueError("Invalid full-vault export: duplicate case IDs")
        if any(self.get_case(case_id) for case_id in case_ids):
            raise ValueError("One or more cases already exist in the vault")
        with self._tx() as c:
            for payload in payloads:
                self._insert_case_payload(c, payload)
        for payload in payloads:
            case = payload["case"]
            self.add_event(case["id"], "import",
                           f"Case imported: {case.get('name', case['id'])}")
            self._audit(case["id"], "case_imported", target=case["id"],
                        details=f"name={case.get('name', '')}")
        return case_ids

    @staticmethod
    def _insert_case_payload(conn, payload):
        case = payload["case"]
        conn.execute(
            "INSERT INTO cases VALUES (:id,:name,:description,:status,:priority,:created,:updated)",
            case)
        for entity in payload.get("entities", []):
            row = {**entity, "tags": json.dumps(entity.get("tags", [])),
                   "linked_to": json.dumps(entity.get("linked_to", []))}
            conn.execute(
                "INSERT INTO entities VALUES "
                "(:id,:case_id,:type,:name,:value,:notes,:tags,:linked_to,"
                ":confidence,:source,:created,:updated)", row)
        for edge in payload.get("edges", []):
            conn.execute(
                "INSERT INTO edges VALUES "
                "(:id,:case_id,:source,:target,:label,:weight,:created)", edge)
        for media in payload.get("media", []):
            raw = bytes.fromhex(media["data"]) if media.get("data") else b""
            conn.execute(
                "INSERT INTO media VALUES "
                "(:id,:case_id,:name,:mime_type,:size,:hash_sha256,:data,:exif,:notes,:created)",
                {**media, "data": raw, "exif": json.dumps(media.get("exif", {}))})
        for event in payload.get("timeline", []):
            conn.execute(
                "INSERT INTO timeline VALUES "
                "(:id,:case_id,:event_type,:title,:detail,:meta,:created)",
                {**event, "meta": json.dumps(event.get("meta", {}))})
        for note in payload.get("notes", []):
            conn.execute(
                "INSERT INTO notes VALUES "
                "(:id,:case_id,:title,:content,:tags,:created,:updated)",
                {**note, "tags": json.dumps(note.get("tags", []))})
        for entry in payload.get("audit_log", []):
            conn.execute(
                "INSERT INTO audit_log "
                "(id,ts,case_id,action,target,details,prev_hash,hash) "
                "VALUES (:id,:ts,:case_id,:action,:target,:details,:prev_hash,:hash)", entry)
