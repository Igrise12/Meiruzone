"""Inbox use cases, independent of HTTP transport."""

import sqlite3
from datetime import UTC, datetime

from .config import Settings
from .database import Repository
from .imap import ERROR_MESSAGES, SyncFailure, fetch_message, message_uids, open_mailbox
from .models import (
    CATEGORIES, CategoryStat, CategoryStats, EmailPage, EmailQuery, EmailSummary,
    LabelPatch, SyncRequest, SyncStatus,
)
from .parser import MessageSkipped


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str):
        self.status = status
        self.code = code
        self.message = message
        super().__init__(code)


class InboxService:
    def __init__(self, repository: Repository, settings: Settings):
        self.repository = repository
        self.settings = settings

    def list_emails(self, query: EmailQuery) -> EmailPage:
        emails, total = self.repository.list_emails(query, self.settings.review_threshold)
        return EmailPage(
            items=[EmailSummary(**email.model_dump(exclude={"body"})) for email in emails],
            total=total, limit=query.limit, offset=query.offset,
        )

    def get_email(self, email_id: str):
        email = self.repository.get_email(email_id, self.settings.review_threshold)
        if email is None:
            raise ApiError(404, "email_not_found", "Message not found.")
        return email

    def save_label(self, email_id: str, patch: LabelPatch):
        label = self.repository.save_label(email_id, patch)
        if label is None:
            raise ApiError(404, "email_not_found", "Message not found.")
        return label

    def category_stats(self) -> CategoryStats:
        counts = self.repository.category_counts()
        total = sum(counts.values())
        return CategoryStats(total=total, categories=[
            CategoryStat(
                category=category, count=counts.get(category, 0),
                percentage=int(100 * counts.get(category, 0) / total + 0.5) if total else 0,
            )
            for category in (*CATEGORIES, "Unclassified")
        ])

    def sync_status(self, outcome: dict | None = None) -> SyncStatus:
        return SyncStatus(
            available=self.settings.demo or self.settings.imap_available, demo=self.settings.demo,
            **(self.repository.sync_status() if outcome is None else outcome),
        )

    def sync(self, request: SyncRequest) -> SyncStatus:
        if not self.repository.start_sync():
            raise ApiError(409, "sync_in_progress", "A sync is already running.")
        if self.settings.demo:
            return self.sync_status(self.repository.finish_sync())
        if not self.settings.imap_available:
            self.repository.finish_sync("sync_unavailable", unavailable=True)
            raise ApiError(503, "sync_unavailable", "Configure IMAP credentials locally to enable sync.")
        error_code = None
        fallback_date = datetime.now(UTC)
        try:
            with open_mailbox(self.settings) as (client, uid_validity):
                mailbox_id = self.repository.ensure_mailbox(
                    self.settings.imap_account_key, self.settings.imap_mailbox, uid_validity,
                )
                if mailbox_id is None:
                    raise SyncFailure("imap_uidvalidity_changed")
                uids = message_uids(client, request)
                self.repository.set_sync_total(len(uids))
                for uid in uids:
                    try:
                        email = fetch_message(client, uid, fallback_date)
                    except MessageSkipped:
                        self.repository.record_skip()
                    else:
                        self.repository.store_message(mailbox_id, uid_validity, uid, email)
        except SyncFailure as error:
            error_code = error.code
        except sqlite3.Error:
            error_code = "storage_unavailable"
        except Exception:
            # Never expose private exception text, including unexpected parser failures.
            error_code = "sync_failed"
        outcome = self.repository.finish_sync(error_code)
        if outcome["state"] == "failed":
            raise ApiError(503, error_code, ERROR_MESSAGES[error_code])
        return self.sync_status(outcome)
