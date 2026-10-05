"""Synthetic parsed IMAP responses; no mailbox or network connection is used."""

import logging
import re
from datetime import UTC, datetime

from imapclient.response_types import BodyData


NOW = datetime(2026, 10, 1, 12, tzinfo=UTC)
MIME = b"Content-Type: text/plain; charset=utf-8\r\nContent-Transfer-Encoding: 8bit\r\n\r\n"


def text_structure(payload: bytes, subtype=b"PLAIN", *, attachment=False):
    disposition = (b"ATTACHMENT", (b"FILENAME", b"private.txt")) if attachment else None
    return (b"TEXT", subtype, (b"CHARSET", b"UTF-8"), None, None, b"8BIT",
            len(payload), 1, None, disposition)


def message(body=b"Synthetic body", *, flags=(), message_id=b"<synthetic@example.test>"):
    headers = b"From: Example <sender@example.test>\r\nSubject: Synthetic message\r\n"
    if message_id:
        headers += b"Message-ID: " + message_id + b"\r\n"
    return {
        "headers": headers + b"\r\n", "flags": flags, "date": NOW,
        "structure": BodyData.create(text_structure(body)), "parts": {"1": (MIME, body)},
    }


class FakeIMAP:
    def __init__(self, messages=None, uid_validity=10):
        self.messages = {1: message()} if messages is None else messages
        self.uid_validity = uid_validity
        self.normalise_times = True
        self.calls = []
        self.errors = {}
        self.fail_uid = None
        self.on_search = None
        self.on_fetch = None

    def login(self, username, password):
        self.calls.append(("login", username, password))
        logging.getLogger("imapclient.imapclient").debug("login %s %s", username, password)
        if "login" in self.errors:
            raise self.errors["login"]

    def select_folder(self, folder, readonly=False):
        self.calls.append(("select_folder", folder, readonly))
        if "select_folder" in self.errors:
            raise self.errors["select_folder"]
        return {b"UIDVALIDITY": self.uid_validity, b"READ-ONLY": True}

    def search(self, criteria):
        self.calls.append(("search", criteria))
        if self.on_search:
            self.on_search()
        if "search" in self.errors:
            raise self.errors["search"]
        return [uid for uid, item in self.messages.items()
                if not any(flag.lower() == b"\\deleted" for flag in item["flags"])
                and ("UNSEEN" not in criteria or not any(flag.lower() == b"\\seen" for flag in item["flags"]))]

    def fetch(self, uids, fields):
        self.calls.append(("fetch", tuple(uids), tuple(fields)))
        if self.on_fetch:
            self.on_fetch(uids, fields)
        uid = uids[0]
        if uid == self.fail_uid:
            raise OSError("synthetic-private-body-password")
        if uid not in self.messages:
            return {}
        item = self.messages[uid]
        if "BODYSTRUCTURE" in fields:
            data = {b"FLAGS": item["flags"], b"INTERNALDATE": item["date"],
                    b"BODYSTRUCTURE": item["structure"], b"UID": uid}
        else:
            data = {}
        for field in fields:
            match = re.fullmatch(r"BODY\.PEEK\[([^]]+)\]<0\.(\d+)>", field)
            if not match:
                continue
            section, limit = match[1], int(match[2])
            if section == "HEADER":
                payload = item["headers"]
            elif section.endswith(".MIME"):
                payload = item["parts"][section[:-5]][0]
            else:
                payload = item["parts"][section][1]
            logging.getLogger("imapclient.imaplib").debug("literal %r", payload)
            data[f"BODY[{section}]<0>".encode()] = payload[:limit]
        return {uid: data}

    def logout(self):
        self.calls.append(("logout",))
        if "logout" in self.errors:
            raise self.errors["logout"]

    def shutdown(self):
        self.calls.append(("shutdown",))
