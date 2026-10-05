"""Selective fetch, TLS, MIME structure, and actual IMAPClient command checks."""

import ssl
import unittest
from unittest.mock import patch

from imapclient import exceptions
from imapclient.response_types import BodyData
from imapclient.testable_imapclient import TestableIMAPClient

from app.config import Settings
from app.imap import SyncFailure, fetch_message, message_uids, open_mailbox, select_text_parts
from app.models import SyncRequest
from app.parser import MAX_HEADER_BYTES, MAX_TEXT_BYTES, MessageSkipped
from imap_fixtures import FakeIMAP, MIME, NOW, message, text_structure


class ImapTests(unittest.TestCase):
    def settings(self):
        return Settings(imap_host="imap.example.test", imap_username="synthetic@example.test",
                        imap_password="synthetic-password", imap_mailbox="Review folder")

    def test_verified_tls_readonly_timezone_and_logout(self):
        fake = FakeIMAP()
        with patch("app.imap.IMAPClient", return_value=fake) as factory:
            with open_mailbox(self.settings()) as (client, validity):
                self.assertIs(client, fake)
                self.assertEqual(validity, 10)
                self.assertFalse(client.normalise_times)
        options = factory.call_args.kwargs
        self.assertTrue(options["ssl"])
        self.assertTrue(options["use_uid"])
        self.assertEqual(options["timeout"], 30)
        self.assertEqual(options["port"], 993)
        self.assertTrue(options["ssl_context"].check_hostname)
        self.assertEqual(options["ssl_context"].verify_mode, ssl.CERT_REQUIRED)
        self.assertIn(("select_folder", "Review folder", True), fake.calls)
        self.assertEqual(fake.calls[-1], ("logout",))

    def test_recent_and_unread_are_bounded_and_skip_deleted(self):
        fake = FakeIMAP({1: message(), 8: message(flags=(b"\\Seen",)),
                         3: message(), 10: message(flags=(b"\\Deleted",))})
        self.assertEqual(message_uids(fake, SyncRequest(limit=2)), [8, 3])
        self.assertEqual(message_uids(fake, SyncRequest(mode="unread", limit=1)), [3])
        self.assertEqual(fake.calls[-1], ("search", ["NOT", "DELETED", "UNSEEN"]))

    def test_alternative_plain_precedence_and_attachment_payloads_never_fetched(self):
        item = message()
        html, plain, attachment = b"<p>Alternative</p>", b"Preferred text", b"private attachment"
        item["structure"] = BodyData.create((
            (text_structure(html, b"HTML"), text_structure(plain), b"ALTERNATIVE", None, None),
            text_structure(attachment, attachment=True),
            (b"IMAGE", b"PNG", None, None, None, b"BASE64", 100_000_000, None, (b"INLINE", None)),
            b"MIXED", None, None,
        ))
        item["parts"] = {"1.1": (b"Content-Type: text/html", html), "1.2": (MIME, plain),
                         "2": (MIME + b"Content-Disposition: attachment", attachment)}
        fake = FakeIMAP({7: item})
        result = fetch_message(fake, 7, NOW)
        self.assertEqual(result.body, "Preferred text")
        self.assertTrue(result.has_attachments)
        fetches = " ".join(str(call[2]) for call in fake.calls if call[0] == "fetch")
        self.assertIn("BODY.PEEK[1.2]", fetches)
        for forbidden in ("BODY.PEEK[1.1]", "BODY.PEEK[2]", "BODY.PEEK[3]", "BODY.PEEK[]", "RFC822"):
            self.assertNotIn(forbidden, fetches)

    def test_html_only_and_inconsistent_attachment_headers(self):
        item = message(b"<p>HTML only</p><script>hidden</script>")
        item["structure"] = BodyData.create(text_structure(item["parts"]["1"][1], b"HTML"))
        item["parts"]["1"] = (b"Content-Type: text/html\r\n", item["parts"]["1"][1])
        self.assertEqual(fetch_message(FakeIMAP({1: item}), 1, NOW).body, "HTML only")
        item = message(b"Secret text attachment")
        item["parts"]["1"] = (b"Content-Type: text/plain\r\nContent-Disposition: attachment; filename=private.txt", b"Secret text attachment")
        fake = FakeIMAP({1: item})
        result = fetch_message(fake, 1, NOW)
        self.assertEqual(result.body, "")
        self.assertTrue(result.has_attachments)
        self.assertEqual(len([call for call in fake.calls if call[0] == "fetch"]), 2)

    def test_oversized_headers_text_missing_messages_and_truncation_are_skipped(self):
        too_big = message(b"x" * (MAX_TEXT_BYTES + 1))
        huge_headers = message()
        huge_headers["headers"] = b"Subject: " + b"x" * MAX_HEADER_BYTES
        truncated = message(b"complete")
        truncated["parts"]["1"] = (MIME, b"short")
        for item in (too_big, huge_headers, truncated):
            fake = FakeIMAP({1: item})
            with self.subTest(kind=len(item["headers"])), self.assertRaises(MessageSkipped):
                fetch_message(fake, 1, NOW)
            if item is too_big:
                self.assertEqual(len(fake.calls), 1)
        with self.assertRaises(MessageSkipped):
            fetch_message(FakeIMAP({}), 1, NOW)

    def test_malformed_and_deep_structure_and_attached_message(self):
        deep = text_structure(b"x")
        for _ in range(22):
            deep = (deep, b"MIXED", None, None)
        for structure in (None, (), (b"TEXT",), BodyData.create(deep)):
            with self.subTest(structure_type=type(structure)), self.assertRaises(MessageSkipped):
                select_text_parts(structure)
        attached = (b"MESSAGE", b"RFC822", None, None, None, b"7BIT", 100_000_000,
                    None, text_structure(b"secret"), 1, None, (b"ATTACHMENT", None))
        self.assertEqual(select_text_parts(BodyData.create(attached)), ([], True))
        named_container = BodyData.create((text_structure(b"private"), b"MIXED", None,
                                           (b"INLINE", (b"FILENAME", b"attached.mime"))))
        self.assertEqual(select_text_parts(named_container), ([], True))

    def test_connection_errors_are_sanitized_and_connections_are_closed(self):
        cases = [
            ("login", exceptions.LoginError("private-password"), "imap_auth_failed"),
            ("select_folder", exceptions.IMAPClientError("private folder"), "imap_mailbox_unavailable"),
            ("search", TimeoutError("private body"), "imap_timeout"),
            ("search", OSError("private username"), "imap_connection_failed"),
        ]
        for phase, error, expected in cases:
            fake = FakeIMAP()
            fake.errors[phase] = error
            with self.subTest(phase=phase), patch("app.imap.IMAPClient", return_value=fake):
                with self.assertRaises(SyncFailure) as caught:
                    with open_mailbox(self.settings()) as (client, _):
                        message_uids(client, SyncRequest())
                self.assertEqual(caught.exception.code, expected)
                self.assertNotIn("private", str(caught.exception))
                self.assertEqual(fake.calls[-1], ("logout",))
        with patch("app.imap.IMAPClient", side_effect=ssl.SSLCertVerificationError("private server")):
            with self.assertRaises(SyncFailure) as caught:
                with open_mailbox(self.settings()):
                    self.fail("unverified TLS must not proceed")
        self.assertEqual(caught.exception.code, "imap_tls_error")
        fake = FakeIMAP(uid_validity=None)
        fake.errors["logout"] = OSError("private cleanup response")
        with patch("app.imap.IMAPClient", return_value=fake), self.assertRaises(SyncFailure):
            with open_mailbox(self.settings()):
                self.fail("invalid identity must not proceed")
        self.assertEqual(fake.calls[-1], ("shutdown",))

    def test_real_imapclient_emits_only_uid_peek_fetches_and_readonly_selection(self):
        # Exercise IMAPClient's response parser and command construction, not just our fake.
        client = TestableIMAPClient()
        wire = client._imap
        wire.login.return_value = ("OK", [b"logged in"])
        wire.select.return_value = ("OK", [b"1"])
        wire.untagged_responses = {"UIDVALIDITY": [b"10"], "EXISTS": [b"1"], "FLAGS": [b"()"]}
        wire.logout.return_value = ("BYE", [b"goodbye"])
        wire._command.return_value = "tag"
        wire._command_complete.return_value = ("OK", [b"done"])
        headers = b"From: Example <sender@example.test>\r\n\r\n"
        structure = b'("TEXT" "PLAIN" ("CHARSET" "UTF-8") NIL NIL "8BIT" 5 1 NIL NIL)'
        metadata = b'1 (UID 7 FLAGS () INTERNALDATE "01-Oct-2026 12:00:00 +0000" BODYSTRUCTURE ' + structure
        responses = []
        for prefix, section, payload in ((metadata, "HEADER", headers), (b"1 (UID 7", "1.MIME", MIME),
                                         (b"1 (UID 7", "1", b"Hello")):
            start = prefix + f" BODY[{section}]<0> {{{len(payload)}}}".encode()
            responses.append(("OK", [(start, payload), b")"]))
        wire._untagged_response.side_effect = responses
        with patch("app.imap.IMAPClient", return_value=client):
            with open_mailbox(self.settings()) as (connected, _):
                result = fetch_message(connected, 7, NOW)
        self.assertEqual(result.body, "Hello")
        self.assertEqual(result.received_at, NOW)
        self.assertTrue(wire.select.call_args.args[1])
        for call in wire._command.call_args_list:
            self.assertEqual(call.args[:2], ("UID", "FETCH"))
            self.assertIn("BODY.PEEK[", call.args[3])
            self.assertNotIn("BODY[]", call.args[3])
        self.assertFalse(wire.store.called)
        self.assertFalse(wire.expunge.called)
        self.assertFalse(wire.close.called)
        self.assertTrue(wire.logout.called)


if __name__ == "__main__":
    unittest.main()
