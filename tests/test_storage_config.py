"""Configuration and storage boundaries omitted by HTTP-level tests."""

import os
import sqlite3
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from pydantic import ValidationError

from app.config import Settings
from app.database import Repository
from app.main import create_app


class StorageConfigTests(unittest.TestCase):
    def test_safe_defaults_and_environment_overrides(self):
        with patch.dict(os.environ, {}, clear=True):
            settings = Settings.from_env()
        self.assertFalse(settings.demo)
        self.assertEqual(settings.database_path, Path("data/meiruzone.sqlite3"))
        self.assertEqual(settings.review_threshold, 70)
        with patch.dict(os.environ, {
            "MEIRUZONE_DATABASE_PATH": "/tmp/synthetic.sqlite3", "MEIRUZONE_DEMO": "true",
            "MEIRUZONE_REVIEW_THRESHOLD": "65", "MEIRUZONE_FRONTEND_ORIGINS": "http://localhost:4173",
            "MEIRUZONE_IMAP_PASSWORD": "never-read-or-stored",
        }, clear=True):
            settings = Settings.from_env()
        self.assertTrue(settings.demo)
        self.assertEqual(settings.review_threshold, 65)
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
                self.assertEqual(connection.execute("PRAGMA user_version").fetchone()[0], 1)
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
                connection.execute("PRAGMA user_version = 2")
            with self.assertRaises(ValueError):
                repository.initialize()
            with repository.connect() as connection:
                self.assertEqual(connection.execute("SELECT COUNT(*) FROM emails").fetchone()[0], 1)


if __name__ == "__main__":
    unittest.main()
