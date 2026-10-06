"""Configuration and storage boundaries omitted by HTTP-level tests."""

import os
import sqlite3
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from pydantic import ValidationError

from app.config import Settings
from app.database import MIGRATION_2, SCHEMA, Repository
from app.demo import demo_emails
from app.main import create_app


class StorageConfigTests(unittest.TestCase):
    def test_imap_configuration_masks_secrets_and_validates_scope(self):
        with patch.dict(os.environ, {
            "MEIRUZONE_IMAP_HOST": "IMAP.Example.Test", "MEIRUZONE_IMAP_PORT": "993",
            "MEIRUZONE_IMAP_USERNAME": "synthetic@example.test",
            "MEIRUZONE_IMAP_PASSWORD": "synthetic-private-password", "MEIRUZONE_IMAP_MAILBOX": "inbox",
        }, clear=True):
            settings = Settings.from_env()
        self.assertTrue(settings.imap_available)
        self.assertEqual(settings.imap_host, "imap.example.test")
        self.assertEqual(settings.imap_mailbox, "INBOX")
        self.assertNotIn("synthetic-private-password", repr(settings) + settings.model_dump_json())
        self.assertNotIn("synthetic@example.test", repr(settings) + settings.imap_account_key)
        self.assertEqual(settings.imap_account_key,
                         Settings(imap_host="imap.example.test", imap_username="synthetic@example.test",
                                  imap_password="changed-password").imap_account_key)
        self.assertFalse(Settings(imap_host="imap.example.test").imap_available)
        for values in ({"imap_host": "https://imap.example.test"}, {"imap_host": "imap.example.test/path"},
                       {"imap_port": 0}, {"imap_port": 65536}, {"imap_username": "user\r\nLOGOUT"},
                       {"imap_password": "password\r\nLOGOUT"},
                       {"imap_mailbox": "folder\nSTORE"}, {"imap_mailbox": ""}):
            with self.subTest(values=values), self.assertRaises(ValidationError):
                Settings(**values)

    def test_v1_migration_preserves_records_labels_predictions_and_demo_state(self):
        with TemporaryDirectory() as directory:
            repository = Repository(Path(directory) / "legacy.sqlite3")
            with repository.connect() as connection:
                connection.executescript(SCHEMA)
            repository.seed_demo(demo_emails())
            with repository.connect() as connection:
                connection.execute("UPDATE sync_state SET state = 'succeeded', started_at = ?, completed_at = ?",
                                   ("2026-10-01T12:00:00Z", "2026-10-01T12:01:00Z"))
                before = {table: [tuple(row) for row in connection.execute(f"SELECT * FROM {table}")]
                          for table in ("emails", "predictions", "human_labels")}
            repository.initialize()
            repository.initialize()
            with repository.connect() as connection:
                after = {table: [tuple(row)[:8] if table == "predictions" else tuple(row)
                                 for row in connection.execute(f"SELECT * FROM {table}")]
                         for table in before}
                self.assertEqual(before, after)
                self.assertEqual(connection.execute("PRAGMA user_version").fetchone()[0], 3)
                self.assertEqual(connection.execute("SELECT demo_seeded FROM sync_state").fetchone()[0], 1)
                self.assertEqual(connection.execute("SELECT COUNT(*) FROM imap_messages").fetchone()[0], 0)
            status = repository.sync_status()
            self.assertEqual((status["state"], status["started_at"], status["completed_at"]),
                             ("succeeded", "2026-10-01T12:00:00Z", "2026-10-01T12:01:00Z"))
            self.assertEqual((status["processed"], status["total"], status["skipped"]), (0, 0, 0))

    def test_migration_failure_rolls_back_schema_and_version_without_resetting_data(self):
        with TemporaryDirectory() as directory:
            repository = Repository(Path(directory) / "legacy.sqlite3")
            with repository.connect() as connection:
                connection.executescript(SCHEMA)
            repository.seed_demo(demo_emails())
            broken = MIGRATION_2.replace("PRAGMA user_version = 2;", "CREATE TABLE emails (id TEXT);")
            with patch("app.database.MIGRATION_2", broken), self.assertRaises(sqlite3.OperationalError):
                repository.initialize()
            with repository.connect() as connection:
                self.assertEqual(connection.execute("PRAGMA user_version").fetchone()[0], 1)
                self.assertEqual(connection.execute("SELECT COUNT(*) FROM emails").fetchone()[0], 10)
                self.assertEqual(connection.execute("SELECT demo_seeded FROM sync_state").fetchone()[0], 1)
                tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_schema WHERE type = 'table'")}
                self.assertNotIn("mailboxes", tables)
                self.assertNotIn("sync_state_v1", tables)
            repository.initialize()
            self.assertEqual(repository.sync_status()["state"], "idle")

    def test_safe_defaults_and_environment_overrides(self):
        with patch.dict(os.environ, {}, clear=True):
            settings = Settings.from_env()
        self.assertFalse(settings.demo)
        self.assertEqual(settings.database_path, Path("data/meiruzone.sqlite3"))
        self.assertIsNone(settings.review_threshold)
        self.assertIsNone(settings.model_directory)
        with patch.dict(os.environ, {
            "MEIRUZONE_DATABASE_PATH": "/tmp/synthetic.sqlite3", "MEIRUZONE_DEMO": "true",
            "MEIRUZONE_REVIEW_THRESHOLD": "65", "MEIRUZONE_FRONTEND_ORIGINS": "http://localhost:4173",
            "MEIRUZONE_IMAP_PASSWORD": "never-read-or-stored",
            "MEIRUZONE_MODEL_DIRECTORY": "/tmp/synthetic-approved-model",
        }, clear=True):
            settings = Settings.from_env()
        self.assertTrue(settings.demo)
        self.assertEqual(settings.review_threshold, 65)
        self.assertEqual(settings.model_directory, Path("/tmp/synthetic-approved-model"))
        self.assertEqual(settings.frontend_origins, ("http://localhost:4173",))
        self.assertNotIn("never-read-or-stored", repr(settings))

    def test_invalid_configuration_is_rejected_without_exposing_values(self):
        for origin in ("*", "null", "https://attacker.example", "http://localhost:5173/",
                       "http://user:password@localhost:5173", "http://localhost:99999"):
            with self.subTest(origin=origin), self.assertRaises(ValidationError):
                Settings(frontend_origins=(origin,))
        for threshold in (-1, 101, float("nan")):
            with self.subTest(threshold=threshold), self.assertRaises(ValidationError):
                Settings(review_threshold=threshold)
        with patch.dict(os.environ, {"MEIRUZONE_REVIEW_THRESHOLD": "private-invalid-value"}):
            with self.assertRaises(RuntimeError) as caught:
                create_app()
        self.assertNotIn("private-invalid-value", str(caught.exception))

    def test_schema_constraints_foreign_keys_and_private_permissions(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "data" / "inbox.sqlite3"
            repository = Repository(path)
            repository.initialize()
            repository.initialize()
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            with repository.connect() as connection:
                self.assertEqual(connection.execute("PRAGMA user_version").fetchone()[0], 3)
                with self.assertRaises(sqlite3.IntegrityError):
                    connection.execute("INSERT INTO human_labels VALUES (?, ?, ?, ?, ?)", (
                        "missing", "Other", "Low", "2026-10-01T00:00:00Z", "manual",
                    ))
                connection.execute("INSERT INTO emails VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (
                    "synthetic", "Example", "example@example.test", "Subject", "Body",
                    "2026-10-01T00:00:00.000000Z", 0, 0,
                ))
                with self.assertRaises(sqlite3.IntegrityError):
                    connection.execute("INSERT INTO predictions(email_id, confidence) VALUES (?, ?)", ("synthetic", 101))
                with self.assertRaises(sqlite3.IntegrityError):
                    connection.execute("INSERT INTO human_labels VALUES (?, ?, ?, ?, ?)", (
                        "synthetic", None, None, "2026-10-01T00:00:00Z", "manual",
                    ))
            with repository.connect() as connection:
                connection.execute("PRAGMA user_version = 4")
            with self.assertRaises(ValueError):
                repository.initialize()
            with repository.connect() as connection:
                self.assertEqual(connection.execute("SELECT COUNT(*) FROM emails").fetchone()[0], 1)


if __name__ == "__main__":
    unittest.main()
