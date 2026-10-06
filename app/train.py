"""Explicit local category training: uv run python -m app.train."""

import argparse
from collections import Counter
from datetime import UTC, datetime
import json
import os
from pathlib import Path
import sqlite3
import sys
from tempfile import TemporaryDirectory
from uuid import uuid4
import warnings

import joblib
import numpy as np
from sklearn.exceptions import ConvergenceWarning
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import classification_report, confusion_matrix, f1_score
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import FunctionTransformer

from app.config import Settings
from app.database import Repository
from app.ml import (
    ARTIFACT_FORMAT, PREPROCESSING_VERSION, TOKEN_PATTERN, MLFailure,
    dependency_versions, load_model, normalize_email, normalize_emails,
)
from app.models import CATEGORIES


SEED = 42
MIN_CLASS_EXAMPLES = 10
REVIEW_TARGET = 0.90
MIN_ACCEPTED = 5


def prepare_examples(examples: list[dict]) -> tuple[list[dict], list[str], dict]:
    unique = {}
    empty = duplicates = 0
    for email in examples:
        text = normalize_email(email)
        label = email.get("category")
        if not isinstance(label, str) or label not in CATEGORIES:
            raise MLFailure("Training categories must be confirmed values from the category taxonomy.")
        if not TOKEN_PATTERN.search(text):
            empty += 1
            continue
        # ponytail: exact normalized duplicates only; group templates/threads if holdout scores inflate.
        if text in unique:
            if unique[text][1] != label:
                raise MLFailure("Identical normalized messages have conflicting labels; review their categories.")
            duplicates += 1
        else:
            unique[text] = (email, label)
    counts = Counter(label for _, label in unique.values())
    eligible = [category for category in CATEGORIES if counts[category] >= MIN_CLASS_EXAMPLES]
    data = {
        "raw_examples": len(examples), "empty_examples": empty, "duplicate_examples": duplicates,
        "class_counts": {category: counts[category] for category in CATEGORIES},
        "missing_classes": [category for category in CATEGORIES if not counts[category]],
        "underrepresented_classes": {
            category: counts[category] for category in CATEGORIES
            if 0 < counts[category] < MIN_CLASS_EXAMPLES
        },
    }
    if len(eligible) < 2:
        summary = ", ".join(f"{category}={counts[category]}" for category in CATEGORIES)
        raise MLFailure(
            f"Need at least two categories with {MIN_CLASS_EXAMPLES} distinct usable human labels each. "
            f"Distinct usable counts: {summary}."
        )
    # Content ordering makes splits reproducible even if database row order changes.
    selected = [entry for _, entry in sorted(unique.items()) if entry[1] in eligible]
    return [email for email, _ in selected], [label for _, label in selected], data


def split_examples(emails: list[dict], labels: list[str]) -> dict:
    train, test, y_train, y_test = train_test_split(
        emails, labels, test_size=0.2, stratify=labels, random_state=SEED,
    )
    train, validation, y_train, y_validation = train_test_split(
        train, y_train, test_size=0.25, stratify=y_train, random_state=SEED,
    )
    splits = {"training": (train, y_train), "validation": (validation, y_validation), "test": (test, y_test)}
    texts = [set(normalize_emails(rows)) for rows, _ in splits.values()]
    if any(texts[left] & texts[right] for left in range(3) for right in range(left + 1, 3)):
        raise MLFailure("Duplicate messages crossed dataset splits; training was stopped.")
    if any(set(values) != set(labels) for _, values in splits.values()):
        raise MLFailure("Every supported category must occur in each split; add more distinct labels.")
    return splits


def review_metrics(truth, predicted, confidence, threshold: float | None) -> dict:
    accepted = np.zeros(len(truth), dtype=bool) if threshold is None else np.asarray(confidence) >= threshold
    count = int(accepted.sum())
    return {
        "accepted": count, "reviewed": len(truth) - count,
        "coverage": count / len(truth) if len(truth) else 0.0,
        "accuracy": float((np.asarray(truth)[accepted] == np.asarray(predicted)[accepted]).mean()) if count else None,
    }


def select_review_threshold(truth, predicted, confidence) -> float | None:
    for threshold in sorted(set(float(value) for value in confidence)):
        result = review_metrics(truth, predicted, confidence, threshold)
        if result["accepted"] >= MIN_ACCEPTED and result["accuracy"] >= REVIEW_TARGET:
            return threshold
    return None


def train_baseline(examples: list[dict]) -> tuple[Pipeline, dict]:
    emails, labels, data = prepare_examples(examples)
    splits = split_examples(emails, labels)
    training, y_train = splits["training"]
    validation, y_validation = splits["validation"]
    test, y_test = splits["test"]
    best = None
    best_score = -1.0
    scores = []
    try:
        for strength in (0.1, 1.0, 10.0):
            candidate = Pipeline([
                ("normalize", FunctionTransformer(normalize_emails, validate=False)),
                ("tfidf", TfidfVectorizer()),
                ("classifier", LogisticRegression(C=strength, solver="lbfgs", max_iter=1000, random_state=SEED)),
            ])
            with warnings.catch_warnings():
                warnings.simplefilter("error", ConvergenceWarning)
                candidate.fit(training, y_train)
            score = float(f1_score(y_validation, candidate.predict(validation), average="macro", zero_division=0))
            scores.append({"C": strength, "macro_f1": score})
            if score > best_score:  # Ascending C gives smaller-C tie breaking.
                best, best_score = candidate, score
        classes = best.classes_.tolist()
        validation_proba = best.predict_proba(validation)
        validation_prediction = best.classes_[validation_proba.argmax(axis=1)]
        validation_confidence = validation_proba.max(axis=1) * 100
        threshold = select_review_threshold(y_validation, validation_prediction, validation_confidence)
        # Freeze this fitted model and its cutoff before the single held-out evaluation.
        test_proba = best.predict_proba(test)
        test_prediction = best.classes_[test_proba.argmax(axis=1)]
        test_confidence = test_proba.max(axis=1) * 100
    except MLFailure:
        raise
    except Exception:
        raise MLFailure("Model fitting or evaluation failed; check usable labels and the local environment.") from None
    report = {
        "artifact_format": ARTIFACT_FORMAT, "preprocessing_version": PREPROCESSING_VERSION,
        "dependencies": dependency_versions(), "seed": SEED,
        "minimum_class_examples": MIN_CLASS_EXAMPLES, "supported_classes": classes, "data": data,
        "splits": {name: {"total": len(values), "class_counts": {
            label: values.count(label) for label in classes
        }} for name, (_, values) in splits.items()},
        "selected_parameters": {"C": best["classifier"].C, "solver": "lbfgs", "max_iter": 1000},
        "validation_candidates": scores, "review_threshold": threshold,
        "review_target_accuracy": REVIEW_TARGET, "minimum_validation_accepted": MIN_ACCEPTED,
        "validation_review": review_metrics(y_validation, validation_prediction, validation_confidence, threshold),
        "test": {
            "classification_report": classification_report(
                y_test, test_prediction, labels=classes, output_dict=True, zero_division=0,
            ),
            "macro_f1": float(f1_score(y_test, test_prediction, labels=classes, average="macro", zero_division=0)),
            "confusion_matrix": confusion_matrix(y_test, test_prediction, labels=classes).tolist(),
            "review": review_metrics(y_test, test_prediction, test_confidence, threshold),
        },
        "limitations": [
            "Only supported categories can be predicted; missing and underrepresented categories are excluded.",
            "Ten examples per category is a readiness floor, not evidence of model quality.",
            "Only exact normalized duplicates are removed; similar templates or threads can inflate evaluation.",
            "Validation is reused for C and cutoff selection; small validation sets give uncertain estimates.",
            "Confidence is an uncalibrated model probability; 90% validation accuracy is not a production guarantee.",
            "The saved model is fitted only on the training split; validation and test examples are not refitted.",
        ],
    }
    return best, report


def save_model(pipeline: Pipeline, report: dict, root: Path = Path("models")) -> Path:
    now = datetime.now(UTC)
    model_version = f"category-{now:%Y%m%dT%H%M%SZ}-{uuid4().hex[:12]}"
    metadata = {**report, "model_version": model_version, "created_at": now.isoformat()}
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    root.chmod(0o700)
    destination = root / model_version
    # Both files become visible together; failed runs never replace an earlier version.
    with TemporaryDirectory(prefix=".training-", dir=root) as temporary:
        staging = Path(temporary)
        for filename in ("evaluation.json", "model.joblib"):
            descriptor = os.open(staging / filename, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            with os.fdopen(descriptor, "wb") as output:
                if filename.endswith(".json"):
                    output.write((json.dumps(metadata, indent=2, allow_nan=False) + "\n").encode("utf-8"))
                else:
                    joblib.dump({"pipeline": pipeline, "metadata": metadata}, output, protocol=5)
                output.flush()
                os.fsync(output.fileno())
        load_model(staging)  # Refuse publishing artifacts that cannot be loaded locally.
        staging.rename(destination)
    return destination


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Train and evaluate a local human-labeled category baseline.")
    parser.add_argument("--database", type=Path, help="Existing version 2 or 3 SQLite database (defaults to backend configuration).")
    parser.add_argument("--output-dir", type=Path, default=Path("models"), help="Private local artifact directory (default: models).")
    args = parser.parse_args(argv)
    try:
        try:
            database = args.database if args.database is not None else Settings.from_env().database_path
        except ValueError:
            raise MLFailure("Invalid backend configuration; check the documented settings.") from None
        try:
            examples = Repository(database).category_training_examples()
        except (OSError, sqlite3.Error, ValueError):
            raise MLFailure("Training requires a readable, initialized version 2 or 3 database; start the backend first.") from None
        pipeline, report = train_baseline(examples)
        destination = save_model(pipeline, report, args.output_dir)
        print((destination / "evaluation.json").read_text(encoding="utf-8"), end="")
        print(f"Saved local model: {destination}")
        return 0
    except MLFailure as error:
        print(f"Training stopped: {error}", file=sys.stderr)
    except Exception:
        print("Training stopped: the local operation failed; existing model versions were preserved.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
