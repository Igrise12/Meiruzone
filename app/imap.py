"""Verified-TLS, read-only IMAP retrieval of bounded headers and text parts."""

import logging
import ssl
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from email import policy
from email.errors import MessageError
from email.parser import BytesHeaderParser

from imapclient import IMAPClient, exceptions

from .config import Settings
from .models import SyncRequest
from .parser import MAX_HEADER_BYTES, MAX_TEXT_BYTES, MessageSkipped, parse_email


# IMAPClient logs wire commands, login identifiers, and message literals at DEBUG.
# Stop propagation for its whole logger namespace, including connection cleanup.
wire_logger = logging.getLogger("imapclient")
wire_logger.addHandler(logging.NullHandler())
wire_logger.propagate = False


ERROR_MESSAGES = {
    "imap_auth_failed": "IMAP login failed. Check the local credentials or app password.",
    "imap_tls_error": "The IMAP server's TLS connection could not be verified.",
    "imap_timeout": "IMAP timed out. Try syncing again.",
    "imap_connection_failed": "The IMAP connection failed. Check the local configuration and retry.",
    "imap_mailbox_unavailable": "The configured IMAP folder could not be opened.",
    "imap_protocol_error": "The IMAP server returned an unsupported response.",
    "imap_uidvalidity_changed": "The folder's message IDs changed. Preserve this database and use a separate database to sync again.",
    "storage_unavailable": "Local storage is unavailable. Try again.",
    "sync_failed": "Email sync could not be completed. Try again.",
}


class SyncFailure(Exception):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


@contextmanager
def open_mailbox(settings: Settings):
    client = None
    phase = "connect"
    try:
        client = IMAPClient(settings.imap_host, port=settings.imap_port, use_uid=True,
                            ssl=True, ssl_context=ssl.create_default_context(), timeout=30)
        client.normalise_times = False  # Preserve timezone-aware INTERNALDATE values.
        phase = "login"
        client.login(settings.imap_username, settings.imap_password.get_secret_value())
        phase = "folder"
        selected = client.select_folder(settings.imap_mailbox, readonly=True)
        uid_validity = selected.get(b"UIDVALIDITY")
        if type(uid_validity) is not int or not 1 <= uid_validity <= 4294967295:
            raise SyncFailure("imap_protocol_error")
        if b"UIDNOTSTICKY" in selected or b"READ-WRITE" in selected:
            raise SyncFailure("imap_protocol_error")
        phase = "fetch"
        yield client, uid_validity
    except exceptions.LoginError:
        raise SyncFailure("imap_auth_failed") from None
    except ssl.SSLError:
        raise SyncFailure("imap_tls_error") from None
    except TimeoutError:
        raise SyncFailure("imap_timeout") from None
    except OSError:
        raise SyncFailure("imap_connection_failed") from None
    except exceptions.IMAPClientError:
        code = "imap_mailbox_unavailable" if phase == "folder" else "imap_protocol_error"
        raise SyncFailure(code) from None
    finally:
        if client is not None:
            try:
                client.logout()
            except Exception:
                try:
                    client.shutdown()
                except Exception:
                    pass  # Cleanup cannot replace the already recorded sync outcome.


def message_uids(client: IMAPClient, request: SyncRequest) -> list[int]:
    criteria = ["NOT", "DELETED"]
    if request.mode == "unread":
        criteria.append("UNSEEN")
    # ponytail: SEARCH enumerates folder UIDs; use ESEARCH/windowed discovery if size warrants it.
    uids = client.search(criteria)
    if any(type(uid) is not int or not 1 <= uid <= 4294967295 for uid in uids):
        raise SyncFailure("imap_protocol_error")
    return sorted(set(uids), reverse=True)[:request.limit]


@dataclass(frozen=True)
class BodyPart:
    section: str
    subtype: bytes
    size: int


def select_text_parts(structure) -> tuple[list[BodyPart], bool]:
    """Walk IMAPClient's parsed BODYSTRUCTURE; never enter attached messages."""
    nodes = 0

    def walk(node, prefix: str, depth: int):
        nonlocal nodes
        nodes += 1
        if depth > 20 or nodes > 100 or not isinstance(node, tuple) or len(node) < 2:
            raise MessageSkipped()
        multipart = isinstance(node[0], list)
        if multipart:
            kind, subtype, params, disposition_index = b"MULTIPART", node[1], node[2] if len(node) > 2 else None, 3
        else:
            if len(node) < 7 or not isinstance(node[0], bytes):
                raise MessageSkipped()
            kind, subtype, params = node[0].upper(), node[1], node[2]
            disposition_index = 9 if kind == b"TEXT" else 11 if kind == b"MESSAGE" and subtype.upper() == b"RFC822" else 8
        if not isinstance(subtype, bytes):
            raise MessageSkipped()
        disposition = node[disposition_index] if len(node) > disposition_index else None
        if params is not None and (not isinstance(params, tuple) or len(params) % 2):
            raise MessageSkipped()
        named = params and any(isinstance(key, bytes) and key.upper() in {b"NAME", b"FILENAME"}
                               for key in params[::2])
        if disposition is not None:
            if not isinstance(disposition, tuple) or not disposition or not isinstance(disposition[0], bytes):
                raise MessageSkipped()
            attached = disposition[0].upper() == b"ATTACHMENT"
            filenames = disposition[1] if len(disposition) > 1 else None
            if filenames is not None:
                if not isinstance(filenames, tuple) or len(filenames) % 2:
                    raise MessageSkipped()
                named = named or any(isinstance(key, bytes) and key.upper() in {b"NAME", b"FILENAME"}
                                     for key in filenames[::2])
        else:
            attached = False
        if attached or named:
            return [], True
        if multipart:
            if not node[0]:
                raise MessageSkipped()
            children = [walk(child, f"{prefix}.{index}" if prefix else str(index), depth + 1)
                        for index, child in enumerate(node[0], start=1)]
            attachments = any(found for _, found in children)
            if subtype.upper() == b"ALTERNATIVE":
                choices = [parts for parts, _ in children if parts]
                preferred = next((parts for parts in choices if any(part.subtype == b"PLAIN" for part in parts)), None)
                return preferred or (choices[0] if choices else []), attachments
            return [part for parts, _ in children for part in parts], attachments
        if kind != b"TEXT" or subtype.upper() not in {b"PLAIN", b"HTML"}:
            return [], True
        size = node[6]
        if type(size) is not int or size < 0:
            raise MessageSkipped()
        return [BodyPart(prefix or "1", subtype.upper(), size)], False

    try:
        parts, attachments = walk(structure, "", 0)
        if sum(part.size for part in parts) > MAX_TEXT_BYTES:
            raise MessageSkipped()
        return parts, attachments
    except (IndexError, TypeError, AttributeError, ValueError, RecursionError):
        raise MessageSkipped() from None


def body_literal(response: dict, section: str, limit: int) -> bytes:
    # A partial FETCH request is answered as BODY[section]<0>, without PEEK.
    key = f"BODY[{section}]".encode("ascii")
    value = response.get(key + b"<0>", response.get(key))
    if not isinstance(value, bytes) or len(value) > limit:
        raise MessageSkipped()
    return value


def fetch_message(client: IMAPClient, uid: int, fallback_date: datetime):
    metadata = client.fetch([uid], ["FLAGS", "INTERNALDATE", "BODYSTRUCTURE",
                                   f"BODY.PEEK[HEADER]<0.{MAX_HEADER_BYTES + 1}>"]).get(uid)
    if not isinstance(metadata, dict):
        raise MessageSkipped()  # The message may have been expunged by another client.
    flags = metadata.get(b"FLAGS")
    if not isinstance(flags, tuple) or any(not isinstance(flag, bytes) for flag in flags):
        raise MessageSkipped()
    if any(flag.lower() == b"\\deleted" for flag in flags):
        raise MessageSkipped()
    headers = body_literal(metadata, "HEADER", MAX_HEADER_BYTES)
    selected, attachments = select_text_parts(metadata.get(b"BODYSTRUCTURE"))
    parts = []
    remaining_headers, remaining_text = MAX_HEADER_BYTES - len(headers), MAX_TEXT_BYTES
    for part in selected:
        mime_response = client.fetch([uid], [f"BODY.PEEK[{part.section}.MIME]<0.{remaining_headers + 1}>"]).get(uid)
        if not isinstance(mime_response, dict):
            raise MessageSkipped()
        mime_headers = body_literal(mime_response, f"{part.section}.MIME", remaining_headers)
        remaining_headers -= len(mime_headers)
        try:
            mime = BytesHeaderParser(policy=policy.default).parsebytes(mime_headers)
            if mime.get_content_disposition() == "attachment" or mime.get_filename():
                attachments = True
                continue  # Even text attachments must not have their payload fetched.
            if mime.get_content_type() not in {"text/plain", "text/html"}:
                raise MessageSkipped()
        except (ValueError, TypeError, IndexError, MessageError):
            raise MessageSkipped() from None
        payload_response = client.fetch([uid], [f"BODY.PEEK[{part.section}]<0.{remaining_text + 1}>"]).get(uid)
        if not isinstance(payload_response, dict):
            raise MessageSkipped()
        payload = body_literal(payload_response, part.section, remaining_text)
        if len(payload) != part.size:
            raise MessageSkipped()  # Never persist an incomplete text part as a complete body.
        remaining_text -= len(payload)
        parts.append((mime_headers, payload))
    return parse_email(headers, parts, metadata.get(b"INTERNALDATE"), flags, attachments, fallback_date)
