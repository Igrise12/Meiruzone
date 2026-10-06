"""Loopback integration server with synthetic messages and a mocked IMAP provider."""

import argparse
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
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("database", type=Path)
    parser.add_argument("port", type=int)
    parser.add_argument("--phase", choices=("training", "prediction", "replacement"))
    parser.add_argument("--model-directory", type=Path)
    args = parser.parse_args()
    model_directory = args.model_directory
    if args.phase is None:
        model_root = args.database.parent / "models"
        runs = sorted(model_root.glob("category-*"))
        if runs:
            model_directory = runs[0]
        else:
            pipeline, report = train_baseline(synthetic_examples(("Recruitment", "Spam")))
            model_directory = save_model(pipeline, report, model_root)
    settings = Settings(
        database_path=args.database, imap_host="imap.example.test",
        imap_username="synthetic-user@example.test", imap_password="synthetic-password",
        model_directory=model_directory,
    )
    repository = Repository(settings.database_path)
    repository.initialize()
    if args.phase is None:
        repository.seed_demo(demo_emails())
        messages = {1: message(b'<img src="https://tracker.invalid/pixel" onerror="alert(1)">')}
    else:
        messages = {}
        for uid, row in enumerate(synthetic_examples(("Recruitment", "Spam")), 1):
            item = message(row["body"].encode(), flags=(b"\\Seen",) if uid % 2 else ())
            item["headers"] = (
                f'From: {row["sender"]} <{row["address"]}>\r\n'
                f'Subject: {row["subject"]}\r\nMessage-ID: <workflow-{uid}@example.test>\r\n\r\n'
            ).encode()
            messages[uid] = item
        if args.phase in ("prediction", "replacement"):
            messages[41] = message(b'Recruitment Recruitment <img src="https://tracker.invalid/pixel" onerror="alert(1)">')
            messages[42] = message(b"Spam Spam newsletter unsubscribe")
        if args.phase == "replacement":
            messages[43] = message(b"Spam Spam later synthetic newsletter")
    fake = FakeIMAP(messages)
    with patch("app.imap.IMAPClient", return_value=fake), \
            patch("socket.create_connection", side_effect=AssertionError("Unexpected outbound connection.")):
        uvicorn.run(create_app(settings), host="127.0.0.1", port=args.port,
                    access_log=False, log_level="error")


if __name__ == "__main__":
    main()
