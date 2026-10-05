"""Local inference, approval, and feedback with synthetic mail and private temporary runs."""

from contextlib import redirect_stdout
import hashlib
import io
import json
import logging
import sqlite3
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.config import Settings
from app.database import MIGRATION_2, MIGRATION_3, SCHEMA, Repository
from app.demo import demo_emails
from app.main import create_app
from app.ml import load_model, predict_priority
from app.train import main as train_command, save_model, train_baseline
from imap_fixtures import FakeIMAP, message
from test_ml import synthetic_examples

WRITE_HEADERS = {"X-Meiruzone-Request": "1"}


class InferenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.examples = synthetic_examples(("Recruitment", "Spam"))
        cls.pipeline, cls.report = train_baseline(cls.examples)

    def setUp(self):
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.run = save_model(self.pipeline, self.report, self.root / "models")
        self.settings = Settings(
            database_path=self.root / "inbox.sqlite3", model_directory=self.run,
            imap_host="imap.example.test", imap_username="synthetic@example.test",
            imap_password="synthetic-password",
        )
        self.fake = FakeIMAP({1: message(b"Recruitment interview. Reply today."),
                              2: message(b"Spam newsletter unsubscribe")})
        mocking = patch("app.imap.IMAPClient", return_value=self.fake)
        mocking.start()
        self.addCleanup(mocking.stop)

    def start(self, **changes):
        app = create_app(self.settings.model_copy(update=changes))
        client = TestClient(app, base_url="http://127.0.0.1:8000")
        client.__enter__()
        self.addCleanup(client.__exit__, None, None, None)
        return client, app.state.inbox.repository

    def sync(self, client):
        return client.post("/api/v1/sync", json={"mode": "recent"}, headers=WRITE_HEADERS)

    def test_real_saved_model_is_loaded_once_and_api_metrics_follow_saved_classes(self):
        with patch("app.services.load_model", wraps=load_model) as loader, \
                patch("socket.create_connection", side_effect=AssertionError("no external network")):
            client, _ = self.start()
            status = client.get("/api/v1/model").json()
            self.assertEqual(status["state"], "ready")
            self.assertEqual(status["supportedCategories"], ["Recruitment", "Spam"])
            self.assertEqual([row["category"] for row in status["evaluation"]["perClass"]],
                             status["supportedCategories"])
            self.assertEqual(status["evaluation"]["confusionMatrix"], self.report["test"]["confusion_matrix"])
            self.assertEqual(status["evaluation"]["macroF1"], self.report["test"]["macro_f1"])
            self.assertNotIn(str(self.root), json.dumps(status))
            self.assertEqual(self.sync(client).json()["imported"], 2)
            self.assertEqual(self.sync(client).json()["imported"], 0)
            client.get("/api/v1/model")
            loader.assert_called_once_with(self.run)
        emails = client.get("/api/v1/emails").json()["items"]
        self.assertEqual({row["prediction"]["priority"] for row in emails}, {"High", "Low"})
        for email in emails:
            prediction = email["prediction"]
            self.assertIn(prediction["category"], status["supportedCategories"])
            self.assertTrue(0 <= prediction["confidence"] <= 100)
            self.assertEqual(prediction["modelVersion"], self.run.name)
            self.assertIsNone(prediction["categoryError"])
            self.assertTrue(prediction["predictedAt"].endswith("Z"))
            self.assertEqual(prediction["reviewThreshold"], self.report["review_threshold"])
        self.assertEqual(client.get("/api/v1/category-stats").json()["total"], 2)

    def test_missing_corrupt_incompatible_and_demo_models_leave_inbox_accessible(self):
        corrupt = self.root / "corrupt"
        corrupt.mkdir()
        (corrupt / "evaluation.json").write_text((self.run / "evaluation.json").read_text())
        (corrupt / "model.joblib").write_bytes(b"private-broken-artifact")
        incompatible = save_model(self.pipeline, self.report, self.root / "models")
        metadata = json.loads((incompatible / "evaluation.json").read_text())
        metadata["dependencies"] = {"private-invalid-dependency": "unknown"}
        (incompatible / "evaluation.json").write_text(json.dumps(metadata))
        for directory, state in ((None, "unconfigured"), (self.root / "missing", "invalid"),
                                 (corrupt, "invalid"), (incompatible, "invalid")):
            with self.subTest(state=state, directory=directory):
                client, _ = self.start(model_directory=directory)
                self.assertEqual(client.get("/api/v1/model").json()["state"], state)
                self.assertEqual(self.sync(client).status_code, 200)
                emails = client.get("/api/v1/emails").json()["items"]
                self.assertEqual(len(emails), 2)
                for row in emails:
                    self.assertIsNone(row["prediction"]["category"])
                    self.assertEqual(row["prediction"]["categoryError"], "model_unavailable")
                    self.assertIsNotNone(row["prediction"]["priority"])
                    self.assertFalse(row["needsReview"])
        with patch("app.services.load_model", side_effect=AssertionError("demo must not load")):
            client, _ = self.start(demo=True)
            self.assertEqual(client.get("/api/v1/model").json()["state"], "demo")
            self.assertIsNone(client.get("/api/v1/model").json()["evaluation"])

    def test_inference_failure_retries_without_replacing_priority_or_corrections_or_logging_content(self):
        client, repository = self.start()
        output = io.StringIO()
        handler = logging.StreamHandler(output)
        logging.getLogger().addHandler(handler)
        self.addCleanup(logging.getLogger().removeHandler, handler)
        with patch("app.services.predict_category", side_effect=RuntimeError("private-error-canary")):
            response = self.sync(client)
        self.assertEqual(response.json()["state"], "succeeded")
        first = client.get("/api/v1/emails").json()["items"]
        self.assertTrue(all(row["prediction"]["categoryError"] == "inference_failed" for row in first))
        corrected = first[0]["id"]
        label = client.patch(f"/api/v1/emails/{corrected}/labels", json={
            "category": "Personal", "priority": "High", "source": "correction",
        }, headers=WRITE_HEADERS).json()
        self.fake.messages[2] = message(b"Spam urgent deadline")
        self.assertEqual(self.sync(client).json()["imported"], 0)
        after = {row["id"]: row for row in client.get("/api/v1/emails").json()["items"]}
        for row in first:
            prediction = after[row["id"]]["prediction"]
            self.assertIsNone(prediction["categoryError"])
            self.assertEqual(prediction["priority"], row["prediction"]["priority"])
        self.assertEqual(after[corrected]["humanLabel"], label)
        self.assertFalse(after[corrected]["needsReview"])
        self.assertEqual(repository.category_training_examples()[0]["category"], "Personal")
        self.assertNotIn("private-error-canary", output.getvalue() + response.text)
        frozen = {row["id"]: row["prediction"] for row in after.values()}
        with patch("app.services.predict_category", side_effect=AssertionError("completed predictions stay intact")):
            self.assertEqual(self.sync(client).status_code, 200)
        self.assertEqual({row["id"]: row["prediction"] for row in client.get("/api/v1/emails").json()["items"]}, frozen)
        restarted, _ = self.start()
        self.assertEqual(restarted.get(f"/api/v1/emails/{corrected}").json()["humanLabel"], label)

    def test_review_cutoffs_equality_review_all_overrides_and_partial_labels(self):
        client, repository = self.start()
        cases = [("equal", 80, 80), ("below", 79.999, 80), ("all", 100, None),
                 ("legacy", 69, 70), ("missing", None, None), ("zero", 0, 0),
                 ("hundred", 100, 100), ("top-below", 99.999, 100)]
        with repository.connect() as connection:
            for identifier, confidence, threshold in cases:
                connection.execute("INSERT INTO emails VALUES (?, '', '', '', '', ?, 0, 0)",
                                   (identifier, "2026-10-05T00:00:00Z"))
                connection.execute("INSERT INTO predictions(email_id, category, confidence, review_threshold, model_version) VALUES (?, ?, ?, ?, ?)",
                                   (identifier, "Spam", confidence, threshold, identifier))
        self.assertEqual({row["id"] for row in client.get("/api/v1/emails?needsReview=true").json()["items"]},
                         {"below", "all", "legacy", "top-below"})
        client.patch("/api/v1/emails/all/labels", json={"priority": "High"}, headers=WRITE_HEADERS)
        self.assertTrue(client.get("/api/v1/emails/all").json()["needsReview"])
        client.patch("/api/v1/emails/all/labels", json={"category": "Personal"}, headers=WRITE_HEADERS)
        self.assertFalse(client.get("/api/v1/emails/all").json()["needsReview"])
        override, _ = self.start(review_threshold=0)
        self.assertEqual(override.get("/api/v1/emails?needsReview=true").json()["total"], 0)
        self.assertTrue(override.get("/api/v1/model").json()["thresholdOverridden"])
        self.assertEqual(override.get("/api/v1/emails/equal").json()["prediction"]["reviewThreshold"], 0)
        self.assertEqual(client.get("/api/v1/emails/equal").json()["prediction"]["reviewThreshold"], 80)

    def test_prediction_write_failure_rolls_back_mail_identity_and_progress(self):
        client, repository = self.start()
        with repository.connect() as connection:
            connection.executescript("CREATE TRIGGER fail_prediction BEFORE INSERT ON predictions BEGIN SELECT RAISE(ABORT, 'synthetic failure'); END;")
        self.assertEqual(self.sync(client).status_code, 503)
        with repository.connect() as connection:
            for table in ("emails", "imap_messages", "predictions"):
                self.assertEqual(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0], 0)
            connection.execute("DROP TRIGGER fail_prediction")
        self.assertEqual(repository.sync_status()["processed"], 0)
        self.assertEqual(self.sync(client).json()["imported"], 2)

    def test_corrections_retrain_readonly_then_require_explicit_activation_and_retain_old_predictions(self):
        client, repository = self.start()
        self.sync(client)
        previous = client.get("/api/v1/emails").json()["items"][0]
        client.patch(f"/api/v1/emails/{previous['id']}/labels", json={"category": "Recruitment", "source": "correction"}, headers=WRITE_HEADERS)
        with repository.connect() as connection:
            for row in self.examples:
                connection.execute("INSERT INTO emails VALUES (?, ?, ?, ?, ?, ?, 0, 0)",
                                   (row["id"], row["sender"], row["address"], row["subject"], row["body"], "2026-10-05T00:00:00Z"))
                connection.execute("INSERT INTO human_labels VALUES (?, ?, NULL, ?, 'manual')",
                                   (row["id"], row["category"], "2026-10-05T00:00:00Z"))
        before = hashlib.sha256(repository.path.read_bytes()).digest()
        with redirect_stdout(io.StringIO()), patch("socket.create_connection", side_effect=AssertionError("no network")):
            self.assertEqual(train_command(["--database", str(repository.path), "--output-dir", str(self.root / "replacement")]), 0)
        self.assertEqual(hashlib.sha256(repository.path.read_bytes()).digest(), before)
        self.assertEqual(client.get("/api/v1/model").json()["modelVersion"], self.run.name)
        replacement, = (self.root / "replacement").iterdir()
        self.assertEqual(load_model(replacement)["metadata"]["data"]["raw_examples"], 41)
        restarted, _ = self.start(model_directory=replacement)
        self.assertEqual(restarted.get("/api/v1/model").json()["modelVersion"], replacement.name)
        self.fake.messages[3] = message(b"Recruitment interview invitation")
        self.sync(restarted)
        self.assertEqual(restarted.get(f"/api/v1/emails/{previous['id']}").json()["prediction"], previous["prediction"])
        self.assertIn(replacement.name, {row["prediction"]["modelVersion"] for row in restarted.get("/api/v1/emails").json()["items"] if row["prediction"]})

    def test_v2_migration_rollback_and_readonly_training_compatibility(self):
        repository = Repository(self.root / "legacy.sqlite3")
        with repository.connect() as connection:
            connection.executescript(SCHEMA + MIGRATION_2)
        repository.seed_demo(demo_emails())
        labels = repository.category_training_examples()
        broken = MIGRATION_3.replace("PRAGMA user_version = 3;", "CREATE TABLE emails(id TEXT);")
        with patch("app.database.MIGRATION_3", broken), self.assertRaises(sqlite3.OperationalError):
            repository.initialize()
        with repository.connect() as connection:
            self.assertEqual(connection.execute("PRAGMA user_version").fetchone()[0], 2)
            self.assertEqual(len(connection.execute("PRAGMA table_info(predictions)").fetchall()), 8)
        self.assertEqual(repository.category_training_examples(), labels)
        repository.initialize()
        self.assertEqual(repository.category_training_examples(), labels)
        with repository.connect() as connection:
            self.assertEqual(connection.execute("PRAGMA user_version").fetchone()[0], 3)
            self.assertEqual(connection.execute("SELECT DISTINCT review_threshold FROM predictions").fetchone()[0], 70)

    def test_priority_rules_are_bilingual_independent_and_respect_boundaries_and_negation(self):
        for text, expected in (("URGENT newsletter", "High"), ("No action required", "Low"),
                               ("tidak perlu tindakan", "Low"), ("Tidak perlu tindakan, tetapi segera balas", "High"),
                               ("Jatuh tempo besok", "High"), ("Balas hari ini", "High"),
                               ("berhenti berlangganan", "Low"), ("sekadar informasi", "Low"),
                               ("unsubscribeworthy urgency fyiish", "Medium"), ("", "Medium"),
                               ("ＲＥＰＬＹ   TODAY", "High")):
            with self.subTest(text=text):
                first = predict_priority({"subject": text, "category": "Spam", "confidence": 0, "read": True})
                self.assertEqual(first[0], expected)
                self.assertEqual(first, predict_priority({"body": text, "category": "Recruitment", "confidence": 100, "has_attachments": True}))
                self.assertIn("priority-rules-v1", first[1])


if __name__ == "__main__":
    unittest.main()
