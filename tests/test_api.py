"""Public API checks using only synthetic emails and temporary SQLite files."""

import json
import sqlite3
import unittest
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


WRITE_HEADERS = {"X-Meiruzone-Request": "1"}
ORIGIN = "http://localhost:5173"


class ApiTests(unittest.TestCase):
    def setUp(self):
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.settings = Settings(database_path=Path(self.directory.name) / "inbox.sqlite3", demo=True)
        self.app = create_app(self.settings)
        self.client = TestClient(self.app, base_url="http://127.0.0.1:8000")
        self.client.__enter__()
        self.addCleanup(self.client.__exit__, None, None, None)

    def save(self, email_id="demo-01", **label):
        return self.client.patch(
            f"/api/v1/emails/{email_id}/labels", json=label, headers=WRITE_HEADERS,
        )

    def stats(self):
        response = self.client.get("/api/v1/category-stats")
        self.assertEqual(response.status_code, 200)
        return response.json()

    def test_default_database_is_empty_and_sync_is_unavailable(self):
        settings = Settings(database_path=Path(self.directory.name) / "empty.sqlite3")
        with TestClient(create_app(settings), base_url="http://localhost") as client:
            self.assertEqual(client.get("/api/v1/emails").json(), {
                "items": [], "total": 0, "limit": 50, "offset": 0,
            })
            stats = client.get("/api/v1/category-stats").json()
            self.assertEqual(stats["total"], 0)
            self.assertEqual(len(stats["categories"]), 9)
            self.assertTrue(all(item["count"] == item["percentage"] == 0 for item in stats["categories"]))
            self.assertFalse(client.get("/api/v1/sync").json()["available"])
            response = client.post("/api/v1/sync", json={}, headers=WRITE_HEADERS)
            self.assertEqual(response.status_code, 503)
            self.assertEqual(response.json()["error"]["code"], "sync_unavailable")
            status = client.get("/api/v1/sync").json()
            self.assertEqual(status["state"], "unavailable")
            self.assertEqual(status["imported"], 0)
            self.assertFalse(status["demo"])

    def test_listing_details_and_missing_predictions(self):
        page = self.client.get("/api/v1/emails").json()
        self.assertEqual(page["total"], 10)
        self.assertEqual(page["limit"], 50)
        self.assertEqual(page["offset"], 0)
        self.assertNotIn("body", page["items"][0])
        self.assertEqual({email["prediction"]["category"] for email in page["items"][:8]}, {
            "Recruitment", "LinkedIn", "Personal", "Transaction",
            "Newsletter", "Promotion", "Spam", "Other",
        })
        self.assertEqual({email["prediction"]["priority"] for email in page["items"][:8]}, {
            "High", "Medium", "Low",
        })
        detail = self.client.get("/api/v1/emails/demo-01").json()
        self.assertIn("synthetic", detail["body"])
        self.assertEqual(detail["prediction"]["confidence"], 61)
        self.assertIsNone(detail["humanLabel"])
        self.assertTrue(detail["hasAttachments"])
        self.assertTrue(detail["receivedAt"].endswith("Z"))
        missing = self.client.get("/api/v1/emails/demo-09").json()
        self.assertIsNone(missing["prediction"])
        self.assertFalse(missing["needsReview"])
        partial = self.client.get("/api/v1/emails/demo-10").json()
        self.assertIsNone(partial["prediction"]["category"])
        self.assertIsNone(partial["prediction"]["confidence"])
        self.assertFalse(partial["needsReview"])

    def test_pagination_is_stable_and_total_is_filtered_total(self):
        first = self.client.get("/api/v1/emails?limit=2").json()
        second = self.client.get("/api/v1/emails?limit=2&offset=2").json()
        self.assertEqual([item["id"] for item in first["items"]], ["demo-01", "demo-02"])
        self.assertEqual([item["id"] for item in second["items"]], ["demo-03", "demo-04"])
        self.assertEqual(first["total"], second["total"])
        self.assertEqual(self.client.get("/api/v1/emails?offset=100").json()["items"], [])
        repository = self.app.state.inbox.repository
        with repository.connect() as connection:
            connection.execute("UPDATE emails SET received_at = ? WHERE id = ?", (
                "2026-10-01T12:00:00.000000Z", "demo-02",
            ))
        tied = self.client.get("/api/v1/emails?limit=2").json()
        self.assertEqual([item["id"] for item in tied["items"]], ["demo-01", "demo-02"])

    def test_filters_use_effective_labels_and_combine_with_search(self):
        personal = self.client.get("/api/v1/emails?category=Personal&limit=1").json()
        self.assertEqual(personal["total"], 2)
        corrected = self.client.get("/api/v1/emails?category=Personal&priority=Low&q=Other").json()
        self.assertEqual([item["id"] for item in corrected["items"]], ["demo-08"])
        self.assertEqual(self.client.get("/api/v1/emails?category=Other").json()["total"], 0)
        unknown = self.client.get("/api/v1/emails?category=Unclassified").json()
        self.assertEqual([item["id"] for item in unknown["items"]], ["demo-09", "demo-10"])
        review = self.client.get("/api/v1/emails?needsReview=true&priority=High").json()
        self.assertEqual([item["id"] for item in review["items"]], ["demo-01"])
        self.assertEqual(self.save(priority="Low").status_code, 200)
        review = self.client.get("/api/v1/emails?needsReview=true&priority=Low").json()
        self.assertEqual(review["total"], 1)
        self.assertEqual(self.save(category="Personal").status_code, 200)
        self.assertEqual(self.client.get("/api/v1/emails?needsReview=true").json()["total"], 0)

    def test_review_threshold_is_configurable_and_exclusive(self):
        settings = self.settings.model_copy(update={"review_threshold": 61})
        with TestClient(create_app(settings), base_url="http://localhost") as client:
            self.assertFalse(client.get("/api/v1/emails/demo-01").json()["needsReview"])
            self.assertEqual(client.get("/api/v1/emails?needsReview=true").json()["total"], 0)

    def test_search_is_unicode_case_insensitive_and_treats_sql_as_text(self):
        with self.app.state.inbox.repository.connect() as connection:
            connection.execute("UPDATE emails SET sender = ?, body = ? WHERE id = ?", (
                "JOSÉ Example", "A literal 100%_ marker", "demo-09",
            ))
        for query in ("josé", "100%_"):
            result = self.client.get("/api/v1/emails", params={"q": query}).json()
            self.assertEqual([item["id"] for item in result["items"]], ["demo-09"])
        response = self.client.get("/api/v1/emails", params={"q": "' OR 1=1 --"})
        self.assertEqual(response.json()["total"], 0)
        self.assertEqual(self.client.get("/api/v1/emails", params={"q": "  "}).json()["total"], 10)

    def test_labels_are_partial_authoritative_and_do_not_replace_predictions(self):
        original = self.client.get("/api/v1/emails/demo-01").json()["prediction"]
        before = datetime.now(UTC)
        response = self.save(category="Personal", source="correction")
        self.assertEqual(response.status_code, 200)
        label = response.json()
        self.assertEqual(label["category"], "Personal")
        self.assertIsNone(label["priority"])
        self.assertEqual(label["source"], "correction")
        self.assertLessEqual(before, datetime.fromisoformat(label["confirmedAt"]))
        self.assertLessEqual(datetime.fromisoformat(label["confirmedAt"]), datetime.now(UTC))
        updated = self.save(priority="Low").json()
        self.assertEqual(updated["category"], "Personal")
        self.assertEqual(updated["priority"], "Low")
        detail = self.client.get("/api/v1/emails/demo-01").json()
        self.assertEqual(detail["prediction"], original)
        self.assertEqual(detail["humanLabel"], updated)

    def test_storage_survives_restart_and_demo_is_seeded_once(self):
        label = self.save(category="Spam", priority="Low").json()
        self.client.post("/api/v1/sync", json={}, headers=WRITE_HEADERS)
        with TestClient(create_app(self.settings), base_url="http://localhost") as client:
            self.assertEqual(client.get("/api/v1/emails").json()["total"], 10)
            self.assertEqual(client.get("/api/v1/emails/demo-01").json()["humanLabel"], label)
            self.assertEqual(client.get("/api/v1/sync").json()["state"], "succeeded")
        with self.app.state.inbox.repository.connect() as connection:
            connection.execute("DELETE FROM emails")
        with TestClient(create_app(self.settings), base_url="http://localhost") as client:
            self.assertEqual(client.get("/api/v1/emails").json()["total"], 0)

    def test_treemap_totals_precedence_zero_counts_and_refresh(self):
        before = self.stats()
        counts = {item["category"]: item["count"] for item in before["categories"]}
        self.assertEqual(before["total"], 10)
        self.assertEqual(sum(counts.values()), before["total"])
        self.assertEqual(counts["Personal"], 2)
        self.assertEqual(counts["Other"], 0)
        self.assertEqual(counts["Unclassified"], 2)
        self.assertTrue(all(item["percentage"] == item["count"] * 10 for item in before["categories"]))
        self.client.get("/api/v1/emails?category=Personal&priority=Low&limit=1&offset=1")
        self.assertEqual(self.stats(), before)
        self.assertEqual(self.save("demo-09", priority="High").status_code, 200)
        self.assertEqual(self.stats(), before)
        self.assertEqual(self.save("demo-09", category="Spam").status_code, 200)
        after = self.stats()
        self.assertEqual(after["total"], 10)
        counts = {item["category"]: item["count"] for item in after["categories"]}
        self.assertEqual(counts["Unclassified"], 1)
        self.assertEqual(counts["Spam"], 2)

    def test_human_label_filter_counts_partial_labels_and_combines_with_filters(self):
        initial = self.client.get("/api/v1/emails?hasHumanLabel=true&limit=1").json()
        self.assertEqual(initial["total"], 1)
        self.save("demo-01", priority="Low")
        self.save("demo-09", category="Spam")
        page = self.client.get("/api/v1/emails?hasHumanLabel=true&limit=1&offset=1").json()
        self.assertEqual(page["total"], 3)
        self.assertEqual(len(page["items"]), 1)
        review = self.client.get("/api/v1/emails?hasHumanLabel=true&needsReview=true").json()
        self.assertEqual([item["id"] for item in review["items"]], ["demo-01"])
        spam = self.client.get("/api/v1/emails?hasHumanLabel=true&category=Spam").json()
        self.assertEqual([item["id"] for item in spam["items"]], ["demo-09"])
        self.assertEqual(self.client.get("/api/v1/emails?hasHumanLabel=false").json()["total"], 10)
        invalid = self.client.get("/api/v1/emails?hasHumanLabel=private-filter-value")
        self.assertEqual(invalid.status_code, 422)
        self.assertEqual(invalid.json()["error"]["fields"][0]["field"], "query.hasHumanLabel")
        self.assertNotIn("private-filter-value", invalid.text)

    def test_training_reader_uses_only_human_category_ground_truth_across_restart(self):
        self.save("demo-01", category="Spam", source="correction")
        self.save("demo-09", priority="High")
        repository = self.app.state.inbox.repository
        examples = repository.category_training_examples()
        self.assertEqual([row["id"] for row in examples], ["demo-01", "demo-08"])
        self.assertEqual(examples[0]["category"], "Spam")
        self.assertIsNone(examples[0]["priority"])
        self.assertEqual(examples[0]["source"], "correction")
        self.assertEqual(set(examples[0]), {
            "id", "sender", "address", "subject", "body", "category", "priority", "confirmed_at", "source",
        })
        self.assertIn("synthetic", examples[0]["body"])
        with TestClient(create_app(self.settings), base_url="http://localhost") as client:
            self.assertEqual(client.app.state.inbox.repository.category_training_examples(), examples)
            self.assertEqual(client.get("/api/v1/emails/demo-01").json()["prediction"]["category"], "Recruitment")

    def test_unknown_ids_and_invalid_inputs(self):
        self.assertEqual(self.client.get("/api/v1/emails/missing").status_code, 404)
        self.assertEqual(self.save("missing", category="Other").status_code, 404)
        queries = [
            {"limit": 0}, {"limit": 101}, {"limit": "1.5"}, {"offset": -1},
            {"offset": 1_000_001}, {"category": "All"}, {"priority": "Urgent"},
            {"needsReview": "perhaps"}, {"q": "x" * 201}, {"unknown": "secret"},
        ]
        for query in queries:
            with self.subTest(query=query):
                self.assertEqual(self.client.get("/api/v1/emails", params=query).status_code, 422)
        for email_id in ("bad.id", "bad id", "x" * 129):
            with self.subTest(email_id=email_id):
                self.assertEqual(self.client.get(f"/api/v1/emails/{email_id}").status_code, 422)
        for label in ({}, {"category": "Unclassified"}, {"priority": "Urgent"},
                      {"category": None, "priority": "Low"}, {"source": "correction"},
                      {"category": "Other", "confirmedAt": "client-controlled-secret"}):
            with self.subTest(label=label):
                self.assertEqual(self.save(**label).status_code, 422)

    def test_validation_errors_do_not_echo_values_or_unknown_keys(self):
        response = self.save(category="secret-email-body", **{"secret-password": "secret-value"})
        self.assertEqual(response.status_code, 422)
        body = response.json()["error"]
        self.assertEqual(body["code"], "validation_error")
        self.assertTrue(body["fields"])
        for secret in ("secret-email-body", "secret-password", "secret-value"):
            self.assertNotIn(secret, response.text)
        malformed = self.client.patch(
            "/api/v1/emails/demo-01/labels", content='{"category": "secret',
            headers={**WRITE_HEADERS, "Content-Type": "application/json"},
        )
        self.assertEqual(malformed.status_code, 422)
        self.assertNotIn("secret", malformed.text)

    def test_demo_sync_is_a_persistent_explicit_no_op(self):
        before = self.stats()
        status = self.client.get("/api/v1/sync").json()
        self.assertEqual(status["state"], "idle")
        self.assertTrue(status["available"])
        response = self.client.post("/api/v1/sync", json={"mode": "unread", "limit": 1}, headers=WRITE_HEADERS)
        self.assertEqual(response.status_code, 200)
        status = response.json()
        self.assertTrue(status["demo"])
        self.assertEqual(status["state"], "succeeded")
        self.assertEqual(status["imported"], 0)
        self.assertIsNone(status["errorCode"])
        self.assertTrue(status["startedAt"].endswith("Z"))
        self.assertTrue(status["completedAt"].endswith("Z"))
        self.assertEqual(self.stats(), before)
        self.assertEqual(self.client.get("/api/v1/sync").json(), status)
        for request in ({"mode": "all"}, {"limit": 0}, {"limit": 101},
                        {"limit": True}, {"limit": "2"}, {"host": "mail.example"}):
            with self.subTest(request=request):
                response = self.client.post("/api/v1/sync", json=request, headers=WRITE_HEADERS)
                self.assertEqual(response.status_code, 422)
        self.assertEqual(self.client.get("/api/v1/sync").json(), status)

    def test_origin_host_and_write_restrictions_prevent_changes(self):
        for origin in ("https://attacker.example", "null", "http://localhost:5174"):
            headers = {**WRITE_HEADERS, "Origin": origin}
            with self.subTest(origin=origin):
                self.assertEqual(self.client.get("/api/v1/emails", headers=headers).status_code, 403)
                self.assertEqual(self.save_with_headers(headers).status_code, 403)
                self.assertEqual(self.client.post("/api/v1/sync", json={}, headers=headers).status_code, 403)
                self.assertEqual(self.client.options("/api/v1/sync", headers={
                    "Origin": origin, "Access-Control-Request-Method": "POST",
                }).status_code, 403)
        for host in ("attacker.example", "localhost.attacker.example", "user@127.0.0.1"):
            with self.subTest(host=host):
                response = self.client.get("/api/v1/emails", headers={"Host": host})
                self.assertEqual(response.status_code, 400)
                self.assertEqual(response.json()["error"]["code"], "invalid_host")
        for headers in (
            [("Host", "localhost"), ("Host", "attacker.example")],
            [("Origin", ORIGIN), ("Origin", "https://attacker.example")],
        ):
            response = self.client.get("/api/v1/emails", headers=headers)
            self.assertEqual(response.status_code, 400)
            self.assertEqual(response.json()["error"]["code"], "invalid_headers")
        for headers in ({}, {"X-Meiruzone-Request": "0"}):
            self.assertEqual(self.save_with_headers(headers).status_code, 403)
        response = self.client.patch("/api/v1/emails/demo-01/labels", data={"category": "Spam"}, headers=WRITE_HEADERS)
        self.assertEqual(response.status_code, 415)
        self.assertIsNone(self.client.get("/api/v1/emails/demo-01").json()["humanLabel"])
        self.assertEqual(self.client.get("/api/v1/sync").json()["state"], "idle")

    def save_with_headers(self, headers):
        return self.client.patch("/api/v1/emails/demo-01/labels", json={"category": "Spam"}, headers=headers)

    def test_allowed_cors_preflight_and_cli_writes(self):
        response = self.client.options("/api/v1/sync", headers={
            "Origin": ORIGIN, "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "Content-Type,X-Meiruzone-Request",
        })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["Access-Control-Allow-Origin"], ORIGIN)
        self.assertNotIn("Access-Control-Allow-Credentials", response.headers)
        for method, header in (("DELETE", "Content-Type"), ("POST", "Authorization")):
            response = self.client.options("/api/v1/sync", headers={
                "Origin": ORIGIN, "Access-Control-Request-Method": method,
                "Access-Control-Request-Headers": header,
            })
            self.assertEqual(response.status_code, 400)
            self.assertEqual(response.json()["error"]["code"], "cors_forbidden")
        response = self.save_with_headers({**WRITE_HEADERS, "Origin": ORIGIN})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["Access-Control-Allow-Origin"], ORIGIN)
        self.assertEqual(self.save(priority="High").status_code, 200)
        response = self.save_with_headers({"Origin": ORIGIN})
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.headers["Access-Control-Allow-Origin"], ORIGIN)

    def test_request_body_limit_checks_actual_bytes(self):
        body = json.dumps({"category": "x" * 4096})
        response = self.client.patch("/api/v1/emails/demo-01/labels", content=body, headers={
            **WRITE_HEADERS, "Content-Type": "application/json", "Content-Length": "1",
        })
        self.assertEqual(response.status_code, 413)
        self.assertIsNone(self.client.get("/api/v1/emails/demo-01").json()["humanLabel"])
        response = self.client.post("/api/v1/sync", content=iter([b"x" * 2000] * 3), headers={
            **WRITE_HEADERS, "Content-Type": "application/json",
        })
        self.assertEqual(response.status_code, 413)

    def test_database_and_unexpected_failures_are_sanitized(self):
        repository = self.app.state.inbox.repository
        with patch.object(repository, "save_label", side_effect=sqlite3.OperationalError("private body password")):
            with self.assertLogs("app.main", level="WARNING") as logs:
                response = self.save(category="Other")
            self.assertEqual(response.status_code, 503)
            self.assertEqual(response.json()["error"]["code"], "storage_unavailable")
            self.assertNotIn("private body password", response.text + " ".join(logs.output))
        with patch.object(repository, "category_counts", side_effect=RuntimeError("private body password")):
            with self.assertLogs("app.main", level="ERROR") as logs:
                response = self.client.get("/api/v1/category-stats")
        self.assertEqual(response.status_code, 500)
        self.assertNotIn("private body password", response.text + " ".join(logs.output))

    def test_openapi_describes_contract_and_has_no_mailbox_secrets(self):
        with patch.dict("os.environ", {"MEIRUZONE_IMAP_PASSWORD": "private-password"}):
            schema = self.client.get("/openapi.json").json()
        paths = schema["paths"]
        self.assertEqual(len(paths), 6)
        patch_operation = paths["/api/v1/emails/{email_id}/labels"]["patch"]
        self.assertTrue(any(parameter["name"] == "X-Meiruzone-Request" and parameter["required"]
                            for parameter in patch_operation["parameters"]))
        self.assertEqual(patch_operation["responses"]["422"]["content"]["application/json"]["schema"], {
            "$ref": "#/components/schemas/ErrorResponse",
        })
        self.assertNotIn("private-password", json.dumps(schema))
        self.assertEqual(self.client.get("/docs").status_code, 404)


if __name__ == "__main__":
    unittest.main()
