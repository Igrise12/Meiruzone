"""Inbox use cases, independent of HTTP transport."""

import sqlite3
from datetime import UTC, datetime

from .config import Settings
from .database import Repository
from .imap import ERROR_MESSAGES, SyncFailure, fetch_message, message_uids, open_mailbox
from .ml import PRIORITY_VERSION, MLFailure, evaluation_summary, load_model, predict_category, predict_priority
from .models import (
    CATEGORIES, CategoryStat, CategoryStats, EmailPage, EmailQuery, EmailSummary,
    LabelPatch, ModelStatus, Prediction, SyncRequest, SyncStatus,
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
        self.model = None
        self.model_state = "unconfigured"

    def initialize_model(self) -> None:
        self.model = None
        self.model_state = "unconfigured"
        if self.settings.demo:
            self.model_state = "demo"
        elif self.settings.model_directory is not None:
            try:
                self.model = load_model(self.settings.model_directory)
                self.model_state = "ready"
            except MLFailure:
                self.model_state = "invalid"

    def model_status(self) -> ModelStatus:
        if self.model is None:
            return ModelStatus(state=self.model_state)
        metadata = self.model["metadata"]
        return ModelStatus(
            state="ready", model_version=metadata["model_version"],
            supported_categories=metadata["supported_classes"],
            review_threshold=(self.settings.review_threshold if self.settings.review_threshold is not None
                              else metadata["review_threshold"]),
            threshold_overridden=self.settings.review_threshold is not None,
            evaluation=evaluation_summary(metadata),
        )

    def predict(self, email, existing: Prediction | None) -> Prediction:
        prediction = existing.model_copy() if existing else Prediction(review_threshold=None)
        complete = prediction.category is not None and prediction.confidence is not None
        if not complete:
            if self.model is None:
                prediction.category_error = "model_unavailable"
            else:
                try:
                    category = predict_category(self.model, email)
                    for field in ("category", "confidence", "model_version", "review_threshold", "reason_category"):
                        setattr(prediction, field, getattr(category, field))
                    prediction.category_error = None
                except Exception:
                    # Private exception details never leave the inference boundary.
                    prediction.category_error = "inference_failed"
            prediction.predicted_at = datetime.now(UTC)
        if prediction.priority is None:
            prediction.priority, prediction.reason_priority = predict_priority(email)
            if prediction.model_version is None and prediction.category is None:
                prediction.model_version = PRIORITY_VERSION
        return prediction

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
                        existing = self.repository.ingested_prediction(mailbox_id, uid_validity, uid)
                        prediction = self.predict(vars(email), existing)
                        self.repository.store_message(mailbox_id, uid_validity, uid, email, prediction)
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
