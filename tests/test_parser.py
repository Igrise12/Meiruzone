"""Email normalization and HTML safety using bounded synthetic inputs."""

import base64
import unittest
from unittest.mock import patch
from datetime import UTC, datetime, timedelta, timezone

from app.parser import MAX_HEADER_BYTES, MAX_TEXT_BYTES, MessageSkipped, html_to_text, parse_email
from imap_fixtures import MIME, NOW


class ParserTests(unittest.TestCase):
    def parse(self, headers=b"", parts=None, internal_date=NOW, flags=()):
        return parse_email(headers, [(MIME, b"Hello\r\nworld\x00")] if parts is None else parts,
                           internal_date, flags, False, NOW)

    def test_plain_text_encoded_headers_and_flags(self):
        email = self.parse(
            b"From: =?utf-8?b?Sm9zw6k=?= <sender@example.test>\r\n"
            b"Subject: =?utf-8?q?Ol=C3=A1?=\r\nMessage-ID: <id@example.test>\r\n\r\n",
            flags=(b"\\SEEN",),
        )
        self.assertEqual((email.sender, email.address, email.subject), ("José", "sender@example.test", "Olá"))
        self.assertEqual(email.body, "Hello\nworld")
        self.assertEqual(email.message_id, "<id@example.test>")
        self.assertTrue(email.read)

    def test_transfer_encodings_charsets_and_unknown_charset(self):
        cases = [
            (b"Content-Type: text/plain; charset=iso-8859-1\r\nContent-Transfer-Encoding: quoted-printable", b"caf=E9", "café"),
            (b"Content-Type: text/plain; charset=utf-8\r\nContent-Transfer-Encoding: base64", base64.b64encode("你好".encode()), "你好"),
            (b"Content-Type: text/plain; charset=unknown-charset", b"a\xffb", "a�b"),
            (b"Content-Type: text/plain; charset=utf-8\r\nContent-Transfer-Encoding: base64", b"SGVsbG8", "Hello"),
        ]
        for mime, body, expected in cases:
            with self.subTest(mime=mime):
                self.assertEqual(self.parse(parts=[(mime, body)]).body, expected)

    def test_html_does_not_execute_or_preserve_active_content(self):
        html = '<head><title>hidden</title></head><p>Hello &amp; welcome</p><script>secret()</script><style>hidden</style><img src="https://tracker.invalid/pixel"><a href="https://example.test">Link</a><iframe>hidden</iframe>'
        with patch("socket.create_connection", side_effect=AssertionError("network forbidden")):
            email = self.parse(parts=[(b"Content-Type: text/html; charset=utf-8", html.encode())])
        self.assertIn("Hello & welcome", email.body)
        self.assertIn("Link", email.body)
        for excluded in ("secret", "hidden", "tracker", "src=", "<"):
            self.assertNotIn(excluded, email.body)
        self.assertEqual(html_to_text("<script/><p>Visible</p>"), "Visible")

    def test_date_precedence_timezone_and_fallback(self):
        internal = datetime(2026, 10, 1, 19, tzinfo=timezone(timedelta(hours=7)))
        headers = b"Date: Wed, 30 Sep 2026 01:00:00 +0200\r\n"
        self.assertEqual(self.parse(headers, internal_date=internal).received_at, NOW)
        self.assertEqual(self.parse(headers, internal_date=None).received_at,
                         datetime(2026, 9, 29, 23, tzinfo=UTC))
        for bad_date in (b"invalid", b"Wed, 30 Sep 2026 01:00:00 -0000", b""):
            self.assertEqual(self.parse(b"Date: " + bad_date, internal_date=None).received_at, NOW)

    def test_missing_and_malformed_headers_are_usable(self):
        for headers in (b"", b"From: broken <\r\nSubject: =?bad?broken\r\n",
                        b"From: ;;;\r\nSubject:\r\nMalformed header\r\n"):
            with self.subTest(headers=headers):
                email = self.parse(headers, parts=[])
                self.assertTrue(email.sender)
                self.assertTrue(email.subject)
                self.assertEqual(email.body, "")
                self.assertIsNone(email.message_id)

    def test_size_boundaries_and_attachment_parts_are_rejected(self):
        self.assertEqual(len(self.parse(parts=[(MIME, b"x" * MAX_TEXT_BYTES)]).body), MAX_TEXT_BYTES)
        for headers, parts in (
            (b"x" * (MAX_HEADER_BYTES + 1), []),
            (b"", [(MIME, b"x" * (MAX_TEXT_BYTES + 1))]),
            (b"", [(b"Content-Type: text/plain\r\nContent-Disposition: attachment; filename=a.txt", b"private")]),
            (b"", [(b"Content-Type: multipart/mixed; boundary=broken", b"malformed")]),
        ):
            with self.subTest(headers_size=len(headers)), self.assertRaises(MessageSkipped):
                self.parse(headers, parts=parts)


if __name__ == "__main__":
    unittest.main()
