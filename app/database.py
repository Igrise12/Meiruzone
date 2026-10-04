"""SQLite persistence. Each operation owns a short-lived connection."""

import os
import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

from .models import EmailDetail, EmailQuery, HumanLabel, LabelPatch, Prediction


SCHEMA = """
BEGIN;
CREATE TABLE emails (
    id TEXT PRIMARY KEY,
    sender TEXT NOT NULL,
    address TEXT NOT NULL,
    subject TEXT NOT NULL,
    body TEXT NOT NULL,
    received_at TEXT NOT NULL,
    is_read INTEGER NOT NULL CHECK (is_read IN (0, 1)),
    has_attachments INTEGER NOT NULL CHECK (has_attachments IN (0, 1))
);
CREATE INDEX emails_received ON emails(received_at DESC, id ASC);
CREATE TABLE predictions (
    email_id TEXT PRIMARY KEY REFERENCES emails(id) ON DELETE CASCADE,
    category TEXT CHECK (category IN (
        'Recruitment', 'LinkedIn', 'Personal', 'Transaction',
        'Newsletter', 'Promotion', 'Spam', 'Other'
    )),
    priority TEXT CHECK (priority IN ('High', 'Medium', 'Low')),
    confidence REAL CHECK (confidence BETWEEN 0 AND 100),
    reason_category TEXT,
    reason_priority TEXT,
    model_version TEXT,
    predicted_at TEXT
);
CREATE TABLE human_labels (
    email_id TEXT PRIMARY KEY REFERENCES emails(id) ON DELETE CASCADE,
    category TEXT CHECK (category IN (
        'Recruitment', 'LinkedIn', 'Personal', 'Transaction',
        'Newsletter', 'Promotion', 'Spam', 'Other'
    )),
    priority TEXT CHECK (priority IN ('High', 'Medium', 'Low')),
    confirmed_at TEXT NOT NULL,
    source TEXT NOT NULL CHECK (source IN ('manual', 'correction')),
    CHECK (category IS NOT NULL OR priority IS NOT NULL)
);
CREATE TABLE sync_state (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    state TEXT NOT NULL CHECK (state IN ('idle', 'succeeded', 'unavailable')),
    started_at TEXT,
    completed_at TEXT,
    imported INTEGER NOT NULL DEFAULT 0 CHECK (imported >= 0),
    error_code TEXT,
    demo_seeded INTEGER NOT NULL DEFAULT 0 CHECK (demo_seeded IN (0, 1))
);
INSERT INTO sync_state(id, state) VALUES (1, 'idle');
PRAGMA user_version = 1;
COMMIT;
"""

JOIN = """
FROM emails e
LEFT JOIN predictions p ON p.email_id = e.id
LEFT JOIN human_labels h ON h.email_id = e.id
"""
SELECT_EMAIL = """
SELECT e.*, p.email_id AS prediction_id, p.category AS prediction_category,
    p.priority AS prediction_priority, p.confidence, p.reason_category,
    p.reason_priority, p.model_version, p.predicted_at,
    h.email_id AS label_id, h.category AS label_category,
    h.priority AS label_priority, h.confirmed_at, h.source
""" + JOIN
EFFECTIVE_CATEGORY = "COALESCE(h.category, p.category, 'Unclassified')"
EFFECTIVE_PRIORITY = "COALESCE(h.priority, p.priority)"
NEEDS_REVIEW = "h.category IS NULL AND p.category IS NOT NULL AND p.confidence < ?"


def utc_text(value: datetime) -> str:
    return value.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


class Repository:
    def __init__(self, path: Path):
        self.path = path

    @contextmanager
    def connect(self):
        connection = sqlite3.connect(self.path, timeout=5)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.create_function(
            "casefold", 1, lambda value: (value or "").casefold(), deterministic=True,
        )
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        try:
            descriptor = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            pass
        else:
            os.close(descriptor)
        self.path.chmod(0o600)
        with self.connect() as connection:
            version = connection.execute("PRAGMA user_version").fetchone()[0]
            if version == 0:
                connection.executescript(SCHEMA)
            elif version != 1:
                raise ValueError("Unsupported local database schema version.")

    def seed_demo(self, emails: list[EmailDetail]) -> None:
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            seeded = connection.execute("SELECT demo_seeded FROM sync_state").fetchone()[0]
            if seeded or connection.execute("SELECT 1 FROM emails LIMIT 1").fetchone():
                return
            for email in emails:
                connection.execute(
                    "INSERT INTO emails VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (email.id, email.sender, email.address, email.subject, email.body,
                     utc_text(email.received_at), email.read, email.has_attachments),
                )
                if email.prediction is not None:
                    prediction = email.prediction
                    connection.execute(
                        "INSERT INTO predictions VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                        (email.id, prediction.category, prediction.priority,
                         prediction.confidence, prediction.reason_category,
                         prediction.reason_priority, prediction.model_version,
                         utc_text(prediction.predicted_at) if prediction.predicted_at else None),
                    )
                if email.human_label is not None:
                    label = email.human_label
                    connection.execute(
                        "INSERT INTO human_labels VALUES (?, ?, ?, ?, ?)",
                        (email.id, label.category, label.priority,
                         utc_text(label.confirmed_at), label.source),
                    )
            connection.execute("UPDATE sync_state SET demo_seeded = 1 WHERE id = 1")

    @staticmethod
    def email_from_row(row: sqlite3.Row, threshold: float) -> EmailDetail:
        prediction = None
        if row["prediction_id"] is not None:
            prediction = Prediction(
                category=row["prediction_category"], priority=row["prediction_priority"],
                confidence=row["confidence"], reason_category=row["reason_category"],
                reason_priority=row["reason_priority"], model_version=row["model_version"],
                predicted_at=row["predicted_at"],
            )
        label = None
        if row["label_id"] is not None:
            label = HumanLabel(
                category=row["label_category"], priority=row["label_priority"],
                confirmed_at=row["confirmed_at"], source=row["source"],
            )
        return EmailDetail(
            id=row["id"], sender=row["sender"], address=row["address"],
            subject=row["subject"], body=row["body"], received_at=row["received_at"],
            read=row["is_read"], has_attachments=row["has_attachments"],
            prediction=prediction, human_label=label,
            needs_review=bool(
                prediction and prediction.category and prediction.confidence is not None
                and prediction.confidence < threshold and (label is None or label.category is None)
            ),
        )

    def list_emails(self, query: EmailQuery, threshold: float) -> tuple[list[EmailDetail], int]:
        conditions, parameters = [], []
        if query.category is not None:
            conditions.append(f"{EFFECTIVE_CATEGORY} = ?")
            parameters.append(query.category)
        if query.priority is not None:
            conditions.append(f"{EFFECTIVE_PRIORITY} = ?")
            parameters.append(query.priority)
        if query.needs_review:
            conditions.append(NEEDS_REVIEW)
            parameters.append(threshold)
        if query.q.strip():
            conditions.append(
                "instr(casefold(e.sender || ' ' || e.address || ' ' || e.subject || ' ' || "
                f"e.body || ' ' || {EFFECTIVE_CATEGORY} || ' ' || "
                f"COALESCE({EFFECTIVE_PRIORITY}, '')), ?) > 0"
            )
            parameters.append(query.q.strip().casefold())
        where = " WHERE " + " AND ".join(conditions) if conditions else ""
        with self.connect() as connection:
            connection.execute("BEGIN")
            total = connection.execute("SELECT COUNT(*) " + JOIN + where, parameters).fetchone()[0]
            rows = connection.execute(
                SELECT_EMAIL + where + " ORDER BY e.received_at DESC, e.id ASC LIMIT ? OFFSET ?",
                [*parameters, query.limit, query.offset],
            ).fetchall()
        return [self.email_from_row(row, threshold) for row in rows], total

    def get_email(self, email_id: str, threshold: float) -> EmailDetail | None:
        with self.connect() as connection:
            row = connection.execute(SELECT_EMAIL + " WHERE e.id = ?", (email_id,)).fetchone()
        return self.email_from_row(row, threshold) if row else None

    def save_label(self, email_id: str, patch: LabelPatch) -> HumanLabel | None:
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            if not connection.execute("SELECT 1 FROM emails WHERE id = ?", (email_id,)).fetchone():
                return None
            connection.execute(
                """INSERT INTO human_labels VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(email_id) DO UPDATE SET
                    category = COALESCE(excluded.category, human_labels.category),
                    priority = COALESCE(excluded.priority, human_labels.priority),
                    confirmed_at = excluded.confirmed_at, source = excluded.source""",
                (email_id, patch.category, patch.priority, utc_text(datetime.now(UTC)), patch.source),
            )
            row = connection.execute(
                "SELECT category, priority, confirmed_at, source FROM human_labels WHERE email_id = ?",
                (email_id,),
            ).fetchone()
        return HumanLabel(**dict(row))

    def category_counts(self) -> dict[str, int]:
        with self.connect() as connection:
            rows = connection.execute(
                f"SELECT {EFFECTIVE_CATEGORY} AS category, COUNT(*) AS count "
                + JOIN + f" GROUP BY {EFFECTIVE_CATEGORY}",
            ).fetchall()
        return {row["category"]: row["count"] for row in rows}

    def sync_status(self) -> dict:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT state, started_at, completed_at, imported, error_code FROM sync_state WHERE id = 1",
            ).fetchone()
        return dict(row)

    def record_sync(self, demo: bool) -> None:
        now = utc_text(datetime.now(UTC))
        with self.connect() as connection:
            connection.execute(
                """UPDATE sync_state SET state = ?, started_at = ?, completed_at = ?,
                imported = 0, error_code = ? WHERE id = 1""",
                ("succeeded" if demo else "unavailable", now, now,
                 None if demo else "sync_unavailable"),
            )
