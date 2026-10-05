"""Synthetic, backend-only examples; no real mailbox data."""

from datetime import UTC, datetime, timedelta

from .models import CATEGORIES, EmailDetail, HumanLabel, Prediction


def demo_emails() -> list[EmailDetail]:
    received = datetime(2026, 10, 1, 12, tzinfo=UTC)
    emails = [
        EmailDetail(
            id=f"demo-{index + 1:02}", sender=f"Example {category}",
            address=f"sender{index + 1}@example.test", subject=f"Synthetic {category} message",
            body=f"This is a synthetic {category} email for local API testing.",
            received_at=received - timedelta(hours=index), read=index % 2 == 0,
            has_attachments=index == 0,
            prediction=Prediction(
                category=category, priority=("High", "Medium", "Low")[index % 3],
                confidence=61 if index == 0 else 94, model_version="synthetic-demo",
                predicted_at=received,
            ),
        )
        for index, category in enumerate(CATEGORIES)
    ]
    emails[7].human_label = HumanLabel(
        category="Personal", priority="Low", confirmed_at=received, source="correction",
    )
    emails.extend([
        EmailDetail(
            id="demo-09", sender="Unclassified example", address="unknown@example.test",
            subject="A message without a prediction", body="No model prediction is available.",
            received_at=received - timedelta(hours=8), read=False, has_attachments=False,
        ),
        EmailDetail(
            id="demo-10", sender="Partial prediction", address="partial@example.test",
            subject="Missing category confidence", body="Only a priority prediction is available.",
            received_at=received - timedelta(hours=9), read=True, has_attachments=False,
            prediction=Prediction(priority="Low"),
        ),
    ])
    return emails
