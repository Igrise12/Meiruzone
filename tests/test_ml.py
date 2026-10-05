"""Category baseline checks use only synthetic messages and temporary storage."""

from contextlib import redirect_stderr, redirect_stdout
import hashlib
import io
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import joblib
import numpy as np

from app.database import Repository
from app.ml import MLFailure, load_model, normalize_email, predict_category
from app.models import CATEGORIES
from app.train import (
    main, prepare_examples, review_metrics, save_model,
    select_review_threshold, split_examples, train_baseline,
)


def synthetic_examples(categories=CATEGORIES, count=20):
    return [{
        "id": f"sample-{category}-{index:03}", "category": category,
        "sender": category, "address": f"{category.lower()}@example.test",
        "subject": f"{category} uniquetoken{category.lower()}{index}",
        "body": f"{category} {category} syntheticcontent{index}",
    } for category in categories for index in range(count)]


class MLTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.examples = synthetic_examples()
        cls.pipeline, cls.report = train_baseline(cls.examples)

    def setUp(self):
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def saved(self):
        return save_model(self.pipeline, self.report, self.root / "models")

    def database(self):
        repository = Repository(self.root / "training.sqlite3")
        repository.initialize()
        with repository.connect() as connection:
            connection.executemany("INSERT INTO emails VALUES (?, ?, ?, ?, ?, ?, ?, ?)", [
                (row["id"], row["sender"], row["address"], row["subject"], row["body"],
                 "2026-10-05T00:00:00Z", 0, 0) for row in self.examples
            ])
            connection.executemany("INSERT INTO human_labels VALUES (?, ?, ?, ?, ?)", [
                (row["id"], row["category"], None, "2026-10-05T00:00:00Z", "manual") for row in self.examples
            ])
            for email_id in ("priority-only", "unverified"):
                connection.execute("INSERT INTO emails VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (
                    email_id, "private-sender", "private-address@example.test", "private-subject",
                    "private-body-canary", "2026-10-05T00:00:00Z", 0, 0,
                ))
            connection.execute("INSERT INTO human_labels VALUES (?, ?, ?, ?, ?)", (
                "priority-only", None, "High", "2026-10-05T00:00:00Z", "manual",
            ))
            connection.execute("INSERT INTO predictions(email_id, category, priority, confidence, reason_category, reason_priority, model_version, predicted_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (
                "unverified", "Spam", "Low", 99, None, None, "synthetic", "2026-10-05T00:00:00Z",
            ))
        return repository

    def test_preprocessing_normalizes_unicode_case_whitespace_and_missing_fields(self):
        self.assertEqual(normalize_email({
            "sender": " ＭＡＩＬ\x00 ", "address": None, "subject": "Straße\t CAFÉ",
            "body": " first\r\n second  ",
        }), "mail\n\nstrasse café\nfirst second")
        self.assertEqual(normalize_email({}), "\n\n\n")
        for value in ([], {"body": ["private-body"]}, {"address": 123}, {"subject": False}):
            with self.subTest(value=value), self.assertRaises(MLFailure) as stopped:
                normalize_email(value)
            self.assertNotIn("private-body", str(stopped.exception))

    def test_duplicates_empty_fields_and_unsupported_classes(self):
        base = synthetic_examples(("Recruitment", "Spam"))
        duplicate = {**base[0], "subject": "  " + base[0]["subject"].upper() + "\t"}
        rows, labels, data = prepare_examples(base + [duplicate, {"category": "Other"}] +
                                              synthetic_examples(("Personal",), count=9))
        self.assertEqual(len(rows), 40)
        self.assertEqual(set(labels), {"Recruitment", "Spam"})
        self.assertEqual(data["duplicate_examples"], 1)
        self.assertEqual(data["empty_examples"], 1)
        self.assertEqual(data["underrepresented_classes"], {"Personal": 9})
        self.assertIn("Other", data["missing_classes"])
        with self.assertRaisesRegex(MLFailure, "conflicting labels"):
            prepare_examples(base + [{**base[0], "category": "Personal"}])
        subset, report = train_baseline(base)
        self.assertEqual(subset.classes_.tolist(), ["Recruitment", "Spam"])
        self.assertIn("Personal", report["data"]["missing_classes"])

    def test_insufficient_data_invalid_labels_and_tokenless_examples(self):
        for rows in ([], synthetic_examples(("Spam",)), synthetic_examples(count=9),
                     synthetic_examples(("Spam",), count=1) * 20):
            with self.subTest(count=len(rows)), self.assertRaisesRegex(MLFailure, "two categories.*10 distinct"):
                train_baseline(rows)
        with self.assertRaises(MLFailure) as stopped:
            prepare_examples([{"category": "private-category", "body": "private-content"}])
        self.assertNotIn("private", str(stopped.exception))
        _, _, data = prepare_examples(self.examples + [{"category": "Other", "body": "! a 😀"}])
        self.assertEqual(data["empty_examples"], 1)
        pipeline, report = train_baseline(synthetic_examples(("Recruitment", "Spam"), count=10))
        self.assertIsNone(report["review_threshold"])
        self.assertEqual(report["test"]["review"]["accepted"], 0)
        self.assertIsNone(load_model(save_model(pipeline, report, self.root / "small"))["metadata"]["review_threshold"])

    def test_splits_are_reproducible_disjoint_and_heldout_vocabulary_is_absent(self):
        rows, labels, _ = prepare_examples(self.examples)
        reversed_rows, reversed_labels, _ = prepare_examples(list(reversed(self.examples)))
        splits = split_examples(rows, labels)
        self.assertEqual(splits, split_examples(reversed_rows, reversed_labels))
        self.assertEqual([len(emails) for emails, _ in splits.values()], [96, 32, 32])
        identifiers = [set(row["id"] for row in emails) for emails, _ in splits.values()]
        self.assertFalse(identifiers[0] & identifiers[1] or identifiers[0] & identifiers[2] or identifiers[1] & identifiers[2])
        vocabulary = self.pipeline["tfidf"].vocabulary_
        for name, (emails, values) in splits.items():
            self.assertEqual(set(values), set(CATEGORIES))
            for email in emails:
                marker = email["subject"].split()[1].lower()
                self.assertEqual(marker in vocabulary, name == "training")
        _, repeated = train_baseline(list(reversed(self.examples)))
        self.assertEqual(repeated, self.report)
        self.assertEqual(self.report["selected_parameters"]["C"], 0.1)
        self.assertEqual(self.report["test"]["macro_f1"], 1.0)
        self.assertEqual(np.asarray(self.report["test"]["confusion_matrix"]).sum(), 32)
        self.assertEqual(set(self.report["test"]["classification_report"]) & set(CATEGORIES), set(CATEGORIES))

    def test_threshold_accuracy_support_boundaries_and_review_all(self):
        truth = ["Spam"] * 10
        predicted = ["Other"] + ["Spam"] * 9
        confidence = list(range(50, 60))
        self.assertEqual(select_review_threshold(truth, predicted, confidence), 50)
        predicted[1] = "Other"
        self.assertEqual(select_review_threshold(truth, predicted, confidence), 52)
        self.assertIsNone(select_review_threshold(truth, ["Other"] * 10, confidence))
        self.assertIsNone(select_review_threshold(truth[:4], truth[:4], confidence[:4]))
        self.assertIsNone(select_review_threshold([], [], []))
        boundary = review_metrics(["Spam"] * 3, ["Spam"] * 3, [69.9, 70, 70.1], 70)
        self.assertEqual(boundary["accepted"], 2)
        self.assertEqual(boundary["accuracy"], 1)
        self.assertEqual(review_metrics(truth, truth, [100] * 10, None), {
            "accepted": 0, "reviewed": 10, "coverage": 0.0, "accuracy": None,
        })

    def test_saved_model_roundtrip_and_fresh_process_predictions(self):
        directory = self.saved()
        loaded = load_model(directory)
        email = self.examples[0]
        prediction = predict_category(loaded, email)
        self.assertEqual(prediction.category, "Recruitment")
        self.assertGreaterEqual(prediction.confidence, 0)
        self.assertLessEqual(prediction.confidence, 100)
        self.assertIsNone(prediction.priority)
        expected = self.pipeline.predict_proba([email])[0].max() * 100
        self.assertEqual(prediction.confidence, expected)
        script = (
            "import json, sys; from pathlib import Path; "
            "from app.ml import load_model, predict_category; "
            "print(predict_category(load_model(Path(sys.argv[1])), json.loads(sys.argv[2])).model_dump_json())"
        )
        result = subprocess.run([sys.executable, "-c", script, str(directory), json.dumps(email)],
                                capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), prediction.model_dump(mode="json"))
        for empty in ({}, {"body": " \t"}, {"body": "a !"}):
            with self.assertRaisesRegex(MLFailure, "no usable text"):
                predict_category(loaded, empty)
        with self.assertRaises(MLFailure):
            predict_category(loaded, {"body": {"private-body": "invalid"}})

    def test_private_permissions_immutable_versions_and_failed_publication(self):
        first = self.saved()
        before = (first / "model.joblib").read_bytes()
        second = self.saved()
        self.assertNotEqual(first, second)
        self.assertEqual(first.stat().st_mode & 0o777, 0o700)
        self.assertEqual(first.parent.stat().st_mode & 0o777, 0o700)
        for filename in ("model.joblib", "evaluation.json"):
            self.assertEqual((first / filename).stat().st_mode & 0o777, 0o600)
        for target in ("app.train.joblib.dump", "app.train.load_model"):
            with self.subTest(target=target), patch(target, side_effect=RuntimeError("private-failure")):
                with self.assertRaises(RuntimeError):
                    self.saved()
            self.assertEqual(set(first.parent.iterdir()), {first, second})
            self.assertEqual((first / "model.joblib").read_bytes(), before)
        self.assertEqual(load_model(first)["metadata"]["model_version"], first.name)
        ignored = subprocess.run(["git", "check-ignore", "models/example/model.joblib", "models/example/evaluation.json"],
                                 capture_output=True, text=True)
        self.assertEqual(ignored.returncode, 0)
        self.assertEqual(len(ignored.stdout.splitlines()), 2)

    def test_missing_corrupt_and_incompatible_models_are_sanitized(self):
        with self.assertRaises(MLFailure):
            load_model(self.root / "missing")
        for change in ("dependencies", "artifact_format", "preprocessing_version", "review_threshold", "supported_classes", "test"):
            with self.subTest(change=change):
                directory = self.saved()
                report = json.loads((directory / "evaluation.json").read_text())
                report[change] = "private-invalid-value"
                (directory / "evaluation.json").write_text(json.dumps(report))
                with patch("app.ml.joblib.load", side_effect=AssertionError("must not deserialize")) as loader:
                    with self.assertRaises(MLFailure) as stopped:
                        load_model(directory)
                    loader.assert_not_called()
                self.assertNotIn("private", str(stopped.exception))
        directory = self.saved()
        (directory / "model.joblib").write_bytes(b"private-broken-artifact")
        with self.assertRaises(MLFailure) as stopped:
            load_model(directory)
        self.assertNotIn("private", str(stopped.exception))
        directory = self.saved()
        model = joblib.load(directory / "model.joblib")
        model["metadata"] = {**model["metadata"], "seed": -1}
        joblib.dump(model, directory / "model.joblib")
        with self.assertRaisesRegex(MLFailure, "do not match"):
            load_model(directory)
        directory = self.saved()
        model = joblib.load(directory / "model.joblib")
        model["pipeline"] = "private-invalid-pipeline"
        joblib.dump(model, directory / "model.joblib")
        with self.assertRaisesRegex(MLFailure, "incompatible"):
            load_model(directory)

    def test_cli_readonly_database_human_ground_truth_and_safe_output(self):
        repository = self.database()
        before = hashlib.sha256(repository.path.read_bytes()).digest()
        output, errors = io.StringIO(), io.StringIO()
        with redirect_stdout(output), redirect_stderr(errors), \
                patch("app.database.Repository.initialize", side_effect=AssertionError("no initialization")), \
                patch("socket.create_connection", side_effect=AssertionError("no network")), \
                patch.dict(os.environ, {"MEIRUZONE_DATABASE_PATH": str(repository.path), "MEIRUZONE_DEMO": "true"}):
            status = main(["--output-dir", str(self.root / "models")])
        self.assertEqual(status, 0, errors.getvalue())
        self.assertEqual(hashlib.sha256(repository.path.read_bytes()).digest(), before)
        directory, = (self.root / "models").iterdir()
        report = load_model(directory)["metadata"]
        self.assertEqual(report["data"]["raw_examples"], 160)
        self.assertEqual(report["supported_classes"], sorted(CATEGORIES))
        self.assertEqual(report["test"], self.report["test"])
        for value in ("private-", "@example.test", "uniquetoken", "syntheticcontent"):
            self.assertNotIn(value, output.getvalue() + errors.getvalue())
            self.assertNotIn(value, json.dumps(report))
        with repository.connect(readonly=True) as connection:
            with self.assertRaises(sqlite3.OperationalError):
                connection.execute("DELETE FROM emails")
        result = subprocess.run([
            sys.executable, "-m", "app.train", "--database", str(repository.path),
            "--output-dir", str(self.root / "cli-models"),
        ], capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        command_run, = (self.root / "cli-models").iterdir()
        self.assertEqual(load_model(command_run)["metadata"]["test"], report["test"])
        self.assertEqual(hashlib.sha256(repository.path.read_bytes()).digest(), before)
        self.assertNotIn("private-", result.stdout + result.stderr)

    def test_cli_failures_do_not_create_databases_or_modify_saved_models(self):
        previous = self.saved()
        missing = self.root / "missing.sqlite3"
        invalid = self.root / "invalid.sqlite3"
        invalid.write_bytes(b"private-invalid-database")
        old = self.root / "old.sqlite3"
        with sqlite3.connect(old) as connection:
            connection.execute("PRAGMA user_version = 1")
        for database in (missing, invalid, old):
            output, errors = io.StringIO(), io.StringIO()
            with self.subTest(database=database.name), redirect_stdout(output), redirect_stderr(errors):
                self.assertEqual(main(["--database", str(database), "--output-dir", str(previous.parent)]), 1)
            self.assertEqual(output.getvalue(), "")
            self.assertNotIn("private", errors.getvalue())
            self.assertEqual(set(previous.parent.iterdir()), {previous})
        self.assertFalse(missing.exists())
        repository = self.database()
        for target in ("app.train.train_baseline", "app.train.save_model"):
            errors = io.StringIO()
            with patch(target, side_effect=ValueError("private-email-body password-secret")), redirect_stderr(errors):
                self.assertEqual(main(["--database", str(repository.path), "--output-dir", str(previous.parent)]), 1)
            self.assertNotIn("private-email", errors.getvalue())
            self.assertNotIn("password-secret", errors.getvalue())
            self.assertEqual(set(previous.parent.iterdir()), {previous})


if __name__ == "__main__":
    unittest.main()
