import ipaddress
import os
import sqlite3
import struct
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from core import crypto
from core.database import Database
from core.enrichers import url_enricher
from core.enrichers.url_enricher import _validate_public_url
from core import enrichment


PASSWORD = "correct horse battery staple"


class CryptoTests(unittest.TestCase):
    def test_authenticated_export_round_trip_and_tamper_detection(self):
        blob = crypto.encrypt({"kind": "test", "value": "safe"}, PASSWORD)
        self.assertEqual(crypto.decrypt(blob, PASSWORD)["value"], "safe")
        damaged = blob[:-1] + bytes([blob[-1] ^ 1])
        with self.assertRaisesRegex(ValueError, "Decryption failed"):
            crypto.decrypt(damaged, PASSWORD)

    def test_rejects_unsafe_iteration_count_before_derivation(self):
        malformed = (
            b"KV20" + struct.pack(">I", 0xFFFFFFFF)
            + b"s" * 32 + b"n" * 12 + b"c" * 16
        )
        with self.assertRaisesRegex(ValueError, "work factor"):
            crypto.decrypt(malformed, PASSWORD)

    def test_exports_require_a_long_password(self):
        with self.assertRaisesRegex(ValueError, "12 characters"):
            crypto.encrypt({"kind": "test"}, "short")


class DatabaseTests(unittest.TestCase):
    def test_vault_is_encrypted_and_rejects_a_wrong_password(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "vault.db"
            db = Database(path, password=PASSWORD)
            case = db.create_case("Private case")
            db.close()

            self.assertNotEqual(path.read_bytes()[:16], b"SQLite format 3\x00")
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            with self.assertRaisesRegex(ValueError, "Could not unlock"):
                Database(path, password="incorrect password")

            reopened = Database(path, password=PASSWORD)
            self.assertEqual(reopened.get_case(case["id"])["name"], "Private case")
            backup = reopened.backup(backups_dir=Path(temp_dir) / "backups")
            self.assertNotEqual(backup.read_bytes()[:16], b"SQLite format 3\x00")
            reopened.close()

    def test_plaintext_vault_is_migrated_without_losing_records(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "legacy.db"
            legacy = sqlite3.connect(path)
            legacy.execute(
                "CREATE TABLE cases (id TEXT PRIMARY KEY, name TEXT, description TEXT, "
                "status TEXT, priority TEXT, created TEXT, updated TEXT)"
            )
            legacy.execute(
                "INSERT INTO cases VALUES (?, ?, ?, ?, ?, ?, ?)",
                ("legacy-id", "Legacy case", "", "Active", "Medium", "now", "now"),
            )
            legacy.commit()
            legacy.close()

            db = Database(path, password=PASSWORD)
            self.assertEqual(db.get_case("legacy-id")["name"], "Legacy case")
            self.assertNotEqual(path.read_bytes()[:16], b"SQLite format 3\x00")
            db.close()

    def test_all_case_audit_chains_are_verified_independently(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db = Database(Path(temp_dir) / "vault.db", password=PASSWORD)
            first = db.create_case("First")
            second = db.create_case("Second")
            self.assertEqual(db.verify_audit_chain(first["id"]), (True, None))
            self.assertEqual(db.verify_audit_chain(second["id"]), (True, None))
            self.assertEqual(db.verify_audit_chain(), (True, None))
            db.close()

    def test_import_rejects_malformed_payload_without_partial_case(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            source = Database(Path(temp_dir) / "source.db", password=PASSWORD)
            case = source.create_case("Exported")
            entity = source.create_entity(case["id"], "Person", "A", "A")
            payload = source.export_case(case["id"])
            payload["edges"] = [{
                "id": "edge-id", "case_id": case["id"], "source": entity["id"],
                "target": "missing", "label": "", "weight": 1, "created": "now",
            }]

            target = Database(Path(temp_dir) / "target.db", password=PASSWORD)
            with self.assertRaisesRegex(ValueError, "unknown entity"):
                target.import_case(payload)
            self.assertIsNone(target.get_case(case["id"]))
            source.close()
            target.close()

    def test_full_import_is_atomic_on_id_collision(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            source = Database(Path(temp_dir) / "source.db", password=PASSWORD)
            first = source.create_case("First")
            second = source.create_case("Second")
            payloads = [source.export_case(first["id"]), source.export_case(second["id"])]
            target = Database(Path(temp_dir) / "target.db", password=PASSWORD)
            target.import_case(payloads[0])
            with self.assertRaisesRegex(ValueError, "already exist"):
                target.import_cases(payloads)
            self.assertEqual(len(target.list_cases()), 1)
            source.close()
            target.close()


class PrivacyAndNetworkTests(unittest.TestCase):
    def test_remote_enrichment_is_disabled_until_explicitly_enabled(self):
        enrichment.set_remote_lookups_enabled(False)
        self.assertIn("disabled", enrichment.enrich({"type": "Email", "value": "a@example.org"})["error"])
        enrichment.set_remote_lookups_enabled(True)
        self.assertIn("No enricher", enrichment.enrich({"type": "Unrecognized"})["error"])
        enrichment.set_remote_lookups_enabled(False)

    def test_enrichment_status_is_encrypted_at_rest(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            status_path = Path(temp_dir) / "status.json"
            with patch.object(enrichment, "_STATUS_FILE", status_path):
                enrichment.configure_status_encryption(PASSWORD)
                enrichment.set_entity_status("entity-id", "failed", "private@example.org")
                raw = status_path.read_bytes()
                self.assertTrue(raw.startswith(b"KVSTAT01"))
                self.assertNotIn(b"private@example.org", raw)
                self.assertEqual(
                    enrichment.get_entity_status("entity-id")["detail"],
                    "private@example.org",
                )

    def test_failed_enrichment_retries_only_after_backoff(self):
        old = (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat()
        recent = datetime.now(timezone.utc).isoformat()
        self.assertTrue(enrichment._failed_retry_due({"attempts": 1, "last_attempt": old}))
        self.assertFalse(enrichment._failed_retry_due({"attempts": 1, "last_attempt": recent}))
        self.assertFalse(enrichment._failed_retry_due({"attempts": 5, "last_attempt": old}))

    def test_url_enrichment_blocks_local_and_credentialed_urls(self):
        for url in (
            "http://127.0.0.1/admin",
            "http://[::1]/",
            "http://user:password@example.org/",
            "file:///etc/passwd",
        ):
            with self.subTest(url=url), self.assertRaises(ValueError):
                _validate_public_url(url)

    def test_socks_proxy_never_silently_falls_back_to_direct_network(self):
        from core.enrichers._net import new_session

        with patch.dict(os.environ, {"KV_PROXY": "socks5h://127.0.0.1:9050"}), \
                patch.dict(sys.modules, {"socks": None}):
            with self.assertRaisesRegex(RuntimeError, "refusing to make an unproxied"):
                new_session()

    def test_url_header_probe_does_not_follow_redirects(self):
        response = SimpleNamespace(status=302)
        connection = SimpleNamespace(
            request=lambda *args, **kwargs: None,
            getresponse=lambda: response,
            close=lambda: None,
            sock=None,
        )
        parsed = url_enricher.urlparse("http://example.test/")
        with patch.object(url_enricher, "proxy_dict", return_value=None), \
                patch.object(url_enricher, "_validate_public_url",
                             return_value=(parsed, ipaddress.ip_address("8.8.8.8"), 80)), \
                patch.object(url_enricher.socket, "create_connection", return_value=object()), \
                patch.object(url_enricher.http.client, "HTTPConnection", return_value=connection):
            result = url_enricher._http_headers("http://example.test/")
        self.assertFalse(result["found"])
        self.assertIn("Redirects are not followed", result["error"])


if __name__ == "__main__":
    unittest.main()
