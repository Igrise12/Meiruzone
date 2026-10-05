"""Loopback integration server with synthetic messages and a mocked IMAP provider."""

import sys
from pathlib import Path
from unittest.mock import patch

import uvicorn

from app.config import Settings
from app.database import Repository
from app.demo import demo_emails
from app.main import create_app
from app.train import save_model, train_baseline
from imap_fixtures import FakeIMAP, message
from test_ml import synthetic_examples


def main():
    model_root = Path(sys.argv[1]).parent / "models"
    runs = sorted(model_root.glob("category-*"))
    if runs:
        model_directory = runs[0]
    else:
        pipeline, report = train_baseline(synthetic_examples(("Recruitment", "Spam")))
        model_directory = save_model(pipeline, report, model_root)
    settings = Settings(
        database_path=Path(sys.argv[1]), imap_host="imap.example.test",
        imap_username="synthetic-user@example.test", imap_password="synthetic-password",
        model_directory=model_directory,
    )
    repository = Repository(settings.database_path)
    repository.initialize()
    repository.seed_demo(demo_emails())
    fake = FakeIMAP({1: message(b'<img src="https://tracker.invalid/pixel" onerror="alert(1)">')})
    with patch("app.imap.IMAPClient", return_value=fake):
        uvicorn.run(create_app(settings), host="127.0.0.1", port=int(sys.argv[2]),
                    access_log=False, log_level="error")


if __name__ == "__main__":
    main()
