"""Inbox use cases, independent of HTTP transport."""

from .config import Settings
from .database import Repository
from .models import (
    CATEGORIES, CategoryStat, CategoryStats, EmailPage, EmailQuery, EmailSummary,
    LabelPatch, SyncStatus,
)


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

    def sync_status(self) -> SyncStatus:
        return SyncStatus(
            available=self.settings.demo, demo=self.settings.demo,
            **self.repository.sync_status(),
        )

    def sync(self) -> SyncStatus:
        self.repository.record_sync(self.settings.demo)
        if not self.settings.demo:
            raise ApiError(503, "sync_unavailable", "IMAP sync is not implemented yet.")
        return self.sync_status()
