"""Normalize bounded email headers and selected text parts without network access."""

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from email import policy
from email.errors import MessageError
from email.parser import BytesHeaderParser, BytesParser
from email.utils import parseaddr, parsedate_to_datetime
from html.parser import HTMLParser


MAX_HEADER_BYTES = 64 * 1024
MAX_TEXT_BYTES = 1024 * 1024


class MessageSkipped(Exception):
    """Unusable message data; exception text must never contain message content."""

    def __init__(self):
        super().__init__("imap_message_skipped")


@dataclass(frozen=True)
class ParsedEmail:
    sender: str
    address: str
    subject: str
    body: str
    received_at: datetime
    read: bool
    has_attachments: bool
    message_id: str | None


class TextHTMLParser(HTMLParser):
    ignored = {"script", "style", "head", "iframe", "object", "template"}
    blocks = {"p", "div", "br", "li", "ul", "ol", "tr", "table", "blockquote",
              "h1", "h2", "h3", "h4", "h5", "h6", "hr", "pre"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.hidden: list[str] = []
        self.text: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag in self.ignored:
            self.hidden.append(tag)
        if not self.hidden and tag in self.blocks:
            self.text.append("\n")

    def handle_startendtag(self, tag, attrs):
        # Self-closing hidden elements must not hide the remaining body.
        if not self.hidden and tag in self.blocks:
            self.text.append("\n")

    def handle_endtag(self, tag):
        if tag in self.hidden:
            index = len(self.hidden) - 1 - self.hidden[::-1].index(tag)
            del self.hidden[index:]
        if not self.hidden and tag in self.blocks:
            self.text.append("\n")

    def handle_data(self, data):
        if not self.hidden:
            self.text.append(data)


def clean_text(text: str) -> str:
    return text.replace("\x00", "").replace("\r\n", "\n").replace("\r", "\n").strip()


def html_to_text(html: str) -> str:
    parser = TextHTMLParser()
    parser.feed(html)
    parser.close()
    lines = [re.sub(r"[^\S\n]+", " ", line).strip() for line in "".join(parser.text).splitlines()]
    return clean_text(re.sub(r"\n{3,}", "\n\n", "\n".join(lines)))


def header_text(message, field: str) -> str:
    try:
        return clean_text(str(message.get(field, "")))
    except (ValueError, IndexError, TypeError, MessageError):
        return ""


def parse_email(headers: bytes, parts: list[tuple[bytes, bytes]], internal_date: datetime | None,
                flags: tuple[bytes, ...], has_attachments: bool, fallback_date: datetime) -> ParsedEmail:
    """Parts contain their MIME headers and encoded body, never attachment payloads."""
    if len(headers) + sum(len(mime) for mime, _ in parts) > MAX_HEADER_BYTES:
        raise MessageSkipped()
    if sum(len(body) for _, body in parts) > MAX_TEXT_BYTES:
        raise MessageSkipped()
    try:
        message = BytesHeaderParser(policy=policy.default).parsebytes(headers)
        sender, address = parseaddr(header_text(message, "From"))
        received_at = internal_date
        if not isinstance(received_at, datetime) or received_at.utcoffset() is None:
            try:
                received_at = parsedate_to_datetime(header_text(message, "Date"))
            except (TypeError, ValueError, OverflowError):
                received_at = None
        if received_at is None or received_at.utcoffset() is None:
            received_at = fallback_date
        body_text = []
        for mime_headers, payload in parts:
            part = BytesParser(policy=policy.default).parsebytes(
                mime_headers.rstrip(b"\r\n") + b"\r\n\r\n" + payload,
            )
            if part.get_content_type() not in {"text/plain", "text/html"}:
                raise MessageSkipped()
            if part.get_content_disposition() == "attachment" or part.get_filename():
                raise MessageSkipped()
            decoded = part.get_payload(decode=True)
            if not isinstance(decoded, bytes):
                raise MessageSkipped()
            try:
                text = decoded.decode(part.get_content_charset() or "utf-8", errors="replace")
            except LookupError:
                text = decoded.decode("utf-8", errors="replace")
            body_text.append(html_to_text(text) if part.get_content_type() == "text/html" else clean_text(text))
        return ParsedEmail(
            sender=sender or address or "Unknown sender", address=address,
            subject=header_text(message, "Subject") or "(No subject)",
            body="\n\n".join(text for text in body_text if text),
            received_at=received_at.astimezone(UTC), read=any(flag.lower() == b"\\seen" for flag in flags),
            has_attachments=has_attachments, message_id=header_text(message, "Message-ID") or None,
        )
    except (ValueError, IndexError, TypeError, UnicodeError, MessageError, OverflowError):
        raise MessageSkipped() from None
