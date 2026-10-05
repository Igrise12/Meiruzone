"""Real sync service/API behavior with synthetic IMAP and temporary SQLite."""

import copy
import io
import logging
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from fastapi.testclient import TestClient
from imapclient import exceptions

from app.config import Settings
from app.imap import fetch_message
from app.main import create_app
from app.parser import MAX_HEADER_BYTES
from imap_fixtures import FakeIMAP, NOW, message


WRITE_HEADERS = {"X-Meiruzone-Request": "1"}


class IngestionTests(unittest.TestCase):
    def setUp(self):
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.settings = Settings(database_path=Path(self.directory.name) / "inbox.sqlite3",
                                 imap_host="imap.example.test", imap_username="private-user@example.test",
                                 imap_password="synthetic-private-password")
        self.fake = FakeIMAP({1: message(b"Message one", message_id=None),
                              2: message(b"Message two", flags=(b"\\Seen",))})
        self.factory_patch = patch("app.imap.IMAPClient", return_value=self.fake)
        self.factory = self.factory_patch.start()
        self.addCleanup(self.factory_patch.stop)
        self.app = create_app(self.settings)
        self.client = self.new_client(self.app)
        self.repository = self.app.state.inbox.repository

    def new_client(self, app):
        client = TestClient(app, base_url="http://127.0.0.1:8000")
        client.__enter__()
        self.addCleanup(client.__exit__, None, None, None)
        return client

    def sync(self, **request):
        return self.client.post("/api/v1/sync", json=request, headers=WRITE_HEADERS)

    def emails(self):
        return self.client.get("/api/v1/emails").json()["items"]

    def test_sync_repeat_updates_fields_and_preserves_human_labels_and_predictions(self):
        response = self.sync(limit=1)
        self.assertEqual(response.status_code, 200)
        self.assertEqual((response.json()["state"], response.json()["imported"], response.json()["total"]),
                         ("succeeded", 1, 1))
        email_id = self.emails()[0]["id"]
        self.assertNotEqual(email_id, "2")
        with self.repository.connect() as connection:
            connection.execute("INSERT INTO predictions(email_id, category, confidence) VALUES (?, ?, ?)",
                               (email_id, "Newsletter", 60))
        label = self.client.patch(f"/api/v1/emails/{email_id}/labels", json={
            "category": "Personal", "priority": "High", "source": "correction",
        }, headers=WRITE_HEADERS).json()
        self.fake.messages[2] = message(b"Updated synthetic body")
        repeated = self.sync(limit=1).json()
        self.assertEqual((repeated["imported"], repeated["processed"], repeated["skipped"]), (0, 1, 0))
        detail = self.client.get(f"/api/v1/emails/{email_id}").json()
        self.assertEqual(detail["body"], "Updated synthetic body")
        self.assertFalse(detail["read"])
        self.assertEqual(detail["humanLabel"], label)
        self.assertEqual(detail["prediction"]["category"], "Newsletter")
        self.assertFalse(detail["needsReview"])
        counts = self.client.get("/api/v1/category-stats").json()
        self.assertEqual(counts["total"], 1)
        self.assertEqual(next(row["count"] for row in counts["categories"] if row["category"] == "Personal"), 1)
        restarted = self.new_client(create_app(self.settings))
        self.assertEqual(restarted.get(f"/api/v1/emails/{email_id}").json()["humanLabel"], label)

    def test_unread_limit_flags_noop_empty_and_command_allowlist(self):
        flags_before = copy.deepcopy({uid: item["flags"] for uid, item in self.fake.messages.items()})
        status = self.sync(mode="unread", limit=1).json()
        self.assertEqual((status["imported"], status["total"]), (1, 1))
        self.assertFalse(self.emails()[0]["read"])
        status = self.sync(limit=2).json()
        self.assertEqual((status["imported"], status["processed"], status["total"]), (1, 2, 2))
        self.assertEqual({uid: item["flags"] for uid, item in self.fake.messages.items()}, flags_before)
        self.assertTrue(all(call[0] in {"login", "select_folder", "search", "fetch", "logout"}
                            for call in self.fake.calls))
        self.assertTrue(all("BODY.PEEK[" in str(call[2]) for call in self.fake.calls if call[0] == "fetch"))
        self.fake.messages.clear()
        empty = self.sync().json()
        self.assertEqual((empty["state"], empty["processed"], empty["total"]), ("succeeded", 0, 0))
        self.assertEqual(len(self.emails()), 2)  # Remote removal never deletes local copies.

    def test_partial_connection_failure_survives_restart_and_retry(self):
        self.fake.fail_uid = 1
        response = self.sync(limit=2)
        self.assertEqual(response.status_code, 200)
        partial = response.json()
        self.assertEqual((partial["state"], partial["processed"], partial["imported"], partial["total"]),
                         ("partial", 1, 1, 2))
        self.assertEqual(partial["errorCode"], "imap_connection_failed")
        old_id = self.emails()[0]["id"]
        restarted = self.new_client(create_app(self.settings))
        self.assertEqual(restarted.get("/api/v1/sync").json(), partial)
        self.fake.fail_uid = None
        retried = self.sync(limit=2).json()
        self.assertEqual((retried["state"], retried["processed"], retried["imported"]), ("succeeded", 2, 1))
        self.assertEqual(len(self.emails()), 2)
        self.assertIn(old_id, [email["id"] for email in self.emails()])

    def test_oversized_message_is_skipped_then_retry_can_import_it(self):
        self.fake.messages[1]["headers"] = b"Subject: " + b"x" * MAX_HEADER_BYTES
        partial = self.sync().json()
        self.assertEqual((partial["state"], partial["processed"], partial["skipped"], partial["imported"]),
                         ("partial", 2, 1, 1))
        self.assertEqual(partial["errorCode"], "imap_message_skipped")
        self.fake.messages[1] = message(b"Recovered body", message_id=None)
        retried = self.sync().json()
        self.assertEqual((retried["state"], retried["skipped"], retried["imported"]), ("succeeded", 0, 1))

    def test_uidvalidity_change_stops_before_fetch_and_keeps_labels(self):
        self.sync()
        email_id = self.emails()[0]["id"]
        label = self.client.patch(f"/api/v1/emails/{email_id}/labels", json={"category": "Personal"},
                                  headers=WRITE_HEADERS).json()
        before = self.emails()
        fetches = sum(call[0] == "fetch" for call in self.fake.calls)
        self.fake.uid_validity = 11
        response = self.sync()
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["error"]["code"], "imap_uidvalidity_changed")
        self.assertEqual(sum(call[0] == "fetch" for call in self.fake.calls), fetches)
        self.assertEqual(self.emails(), before)
        self.assertEqual(self.client.get(f"/api/v1/emails/{email_id}").json()["humanLabel"], label)
        fresh_settings = self.settings.model_copy(update={"database_path": Path(self.directory.name) / "fresh.sqlite3"})
        fresh = self.new_client(create_app(fresh_settings))
        self.assertEqual(fresh.post("/api/v1/sync", json={}, headers=WRITE_HEADERS).json()["imported"], 2)
        self.assertEqual(self.emails(), before)

    def test_identical_uids_and_message_ids_are_scoped_to_account_and_folder(self):
        self.fake.messages[1] = message()  # The two UIDs intentionally share Message-ID.
        self.sync()
        original_ids = {email["id"] for email in self.emails()}
        for settings in (self.settings.model_copy(update={"imap_username": "another@example.test"}),
                         self.settings.model_copy(update={"imap_mailbox": "Archive"})):
            client = self.new_client(create_app(settings))
            self.assertEqual(client.post("/api/v1/sync", json={}, headers=WRITE_HEADERS).json()["imported"], 2)
        self.assertEqual(len(self.emails()), 6)
        self.assertTrue(original_ids.issubset({email["id"] for email in self.emails()}))

    def test_progress_visible_and_overlapping_request_rejected(self):
        entered, release = threading.Event(), threading.Event()

        def wait_for_release(uids, fields):
            if uids == [1] and "BODYSTRUCTURE" in fields:
                entered.set()
                if not release.wait(5):
                    raise TimeoutError("test release timed out")

        self.fake.on_fetch = wait_for_release
        with ThreadPoolExecutor(max_workers=1) as executor:
            pending = executor.submit(self.sync)
            try:
                self.assertTrue(entered.wait(5))
                running = self.client.get("/api/v1/sync").json()
                self.assertEqual((running["state"], running["processed"], running["imported"], running["total"]),
                                 ("running", 1, 1, 2))
                self.assertIsNone(running["completedAt"])
                overlap = self.sync()
                self.assertEqual(overlap.status_code, 409)
                self.assertEqual(overlap.json()["error"]["code"], "sync_in_progress")
                self.assertEqual(self.client.get("/api/v1/sync").json(), running)
            finally:
                release.set()
            self.assertEqual(pending.result(timeout=5).json()["state"], "succeeded")

    def test_restart_recovers_running_state_and_preserves_committed_import(self):
        self.assertTrue(self.repository.start_sync())
        restarted = self.new_client(create_app(self.settings))
        self.assertEqual(restarted.get("/api/v1/sync").json()["state"], "failed")
        self.assertTrue(self.repository.start_sync())
        mailbox_id = self.repository.ensure_mailbox(self.settings.imap_account_key, "INBOX", 10)
        self.repository.set_sync_total(2)
        self.repository.store_message(mailbox_id, 10, 2, fetch_message(self.fake, 2, NOW))
        restarted = self.new_client(create_app(self.settings))
        status = restarted.get("/api/v1/sync").json()
        self.assertEqual((status["state"], status["processed"], status["imported"], status["total"]),
                         ("partial", 1, 1, 2))
        self.assertEqual(status["errorCode"], "sync_interrupted")
        self.assertEqual(self.sync().json()["imported"], 1)

    def test_transaction_failure_rolls_back_email_identity_and_progress(self):
        with self.repository.connect() as connection:
            connection.execute("""CREATE TRIGGER reject_progress BEFORE UPDATE ON sync_state
                WHEN NEW.processed > OLD.processed BEGIN SELECT RAISE(ABORT, 'synthetic private storage failure'); END""")
        response = self.sync()
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["error"]["code"], "storage_unavailable")
        with self.repository.connect() as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM emails").fetchone()[0], 0)
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM imap_messages").fetchone()[0], 0)
            connection.execute("DROP TRIGGER reject_progress")
        status = self.client.get("/api/v1/sync").json()
        self.assertEqual((status["processed"], status["imported"]), (0, 0))
        self.assertEqual(self.sync().json()["imported"], 2)

    def test_completed_response_keeps_its_outcome_when_the_next_run_starts(self):
        finish_sync = self.repository.finish_sync

        def finish_then_start_next(*args, **kwargs):
            outcome = finish_sync(*args, **kwargs)
            self.assertTrue(self.repository.start_sync())
            return outcome

        with patch.object(self.repository, "finish_sync", side_effect=finish_then_start_next):
            completed = self.sync().json()
        self.assertEqual((completed["state"], completed["imported"]), ("succeeded", 2))
        self.assertEqual(self.client.get("/api/v1/sync").json()["state"], "running")

    def test_failure_after_import_returns_partial_storage_outcome(self):
        with self.repository.connect() as connection:
            connection.execute("""CREATE TRIGGER reject_one BEFORE INSERT ON emails
                WHEN NEW.body = 'Message one' BEGIN SELECT RAISE(ABORT, 'synthetic failure'); END""")
        response = self.sync()
        self.assertEqual(response.status_code, 200)
        self.assertEqual((response.json()["state"], response.json()["imported"], response.json()["processed"]),
                         ("partial", 1, 1))
        self.assertEqual(response.json()["errorCode"], "storage_unavailable")

    def test_api_errors_debug_logs_and_database_omit_private_secrets(self):
        output = io.StringIO()
        handler = logging.StreamHandler(output)
        root = logging.getLogger()
        original_level = root.level
        root.setLevel(logging.DEBUG)
        root.addHandler(handler)
        try:
            self.sync()
            self.fake.errors["login"] = exceptions.LoginError("synthetic-private-password private-user@example.test Message two")
            failure = self.sync()
            self.assertEqual(failure.status_code, 503)
            self.assertEqual(failure.json()["error"]["code"], "imap_auth_failed")
            self.assertEqual(self.client.get("/api/v1/sync").json()["state"], "failed")
            schema = self.client.get("/openapi.json").text
        finally:
            root.removeHandler(handler)
            root.setLevel(original_level)
        for private in ("synthetic-private-password", "private-user@example.test", "Message two"):
            self.assertNotIn(private, output.getvalue() + failure.text + schema)
        self.assertNotIn(b"synthetic-private-password", self.settings.database_path.read_bytes())

    def test_demo_and_unconfigured_settings_never_connect(self):
        for overrides, status, state in (({"demo": True}, 200, "succeeded"),
                                         ({"imap_password": None}, 503, "unavailable")):
            client = self.new_client(create_app(self.settings.model_copy(update=overrides)))
            self.factory.reset_mock()
            response = client.post("/api/v1/sync", json={}, headers=WRITE_HEADERS)
            self.assertEqual(response.status_code, status)
            self.assertEqual(client.get("/api/v1/sync").json()["state"], state)
            self.factory.assert_not_called()


if __name__ == "__main__":
    unittest.main()
