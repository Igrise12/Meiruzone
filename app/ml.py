"""Shared category preprocessing and explicitly selected, trusted local models."""

import json
import math
import platform
import re
import unicodedata
from collections.abc import Mapping
from importlib.metadata import version
from pathlib import Path
import warnings

import joblib
import numpy as np
from sklearn.exceptions import InconsistentVersionWarning
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import FunctionTransformer
from sklearn.utils.validation import check_is_fitted

from app.models import CATEGORIES, Prediction
from app.parser import clean_text


ARTIFACT_FORMAT = 1
PREPROCESSING_VERSION = 1
TOKEN_PATTERN = re.compile(r"(?u)\b\w\w+\b")  # TF-IDF's default word tokens.


class MLFailure(ValueError):
    """An actionable error whose text contains no private input values."""


def normalize_email(email: Mapping) -> str:
    if not isinstance(email, Mapping):
        raise MLFailure("Email fields must be provided as a mapping.")
    fields = []
    for name in ("sender", "address", "subject", "body"):
        value = email.get(name)
        if value is not None and not isinstance(value, str):
            raise MLFailure("Email text fields must be strings or missing.")
        text = unicodedata.normalize("NFKC", clean_text(value or "")).casefold()
        fields.append(" ".join(text.split()))
    return "\n".join(fields)


def normalize_emails(emails) -> list[str]:
    # Module-level function keeps Joblib artifacts independent of the CLI's __main__.
    return [normalize_email(email) for email in emails]


def dependency_versions() -> dict[str, str]:
    return {"python": platform.python_version(), **{
        name: version(name) for name in ("scikit-learn", "numpy", "scipy", "joblib")
    }}


def load_model(directory: Path) -> dict:
    """Load a run created by app.train. The caller must trust its local provenance.

    Joblib can execute code while loading; metadata checks do not make it safe
    to load downloaded, uploaded, or otherwise untrusted files.
    """
    try:
        metadata = json.loads((directory / "evaluation.json").read_text(encoding="utf-8"))
        if (not isinstance(metadata, dict)
                or metadata.get("artifact_format") != ARTIFACT_FORMAT
                or metadata.get("preprocessing_version") != PREPROCESSING_VERSION
                or metadata.get("dependencies") != dependency_versions()):
            raise MLFailure("Model format or environment is incompatible; retrain locally.")
        classes = metadata["supported_classes"]
        threshold = metadata["review_threshold"]
        if (not isinstance(classes, list) or not 2 <= len(classes) <= len(CATEGORIES)
                or any(not isinstance(label, str) or label not in CATEGORIES for label in classes)
                or len(set(classes)) != len(classes)
                or not isinstance(metadata["model_version"], str)
                or not metadata["model_version"]
                or (threshold is not None and (
                    isinstance(threshold, bool) or not isinstance(threshold, (int, float))
                    or not math.isfinite(threshold) or not 0 <= threshold <= 100))):
            raise MLFailure("Model metadata is invalid; retrain locally.")
        with warnings.catch_warnings():
            warnings.simplefilter("error", InconsistentVersionWarning)
            model = joblib.load(directory / "model.joblib")
        if not isinstance(model, dict) or model.get("metadata") != metadata:
            raise MLFailure("Model and evaluation metadata do not match.")
        pipeline = model["pipeline"]
        if (not isinstance(pipeline, Pipeline)
                or list(pipeline.named_steps) != ["normalize", "tfidf", "classifier"]
                or not isinstance(pipeline["normalize"], FunctionTransformer)
                or pipeline["normalize"].func is not normalize_emails
                or not isinstance(pipeline["tfidf"], TfidfVectorizer)
                or not isinstance(pipeline["classifier"], LogisticRegression)):
            raise MLFailure("Model pipeline is incompatible; retrain locally.")
        check_is_fitted(pipeline["tfidf"])
        check_is_fitted(pipeline["classifier"])
        if (pipeline.classes_.tolist() != classes
                or pipeline["classifier"].n_features_in_ != len(pipeline["tfidf"].vocabulary_)):
            raise MLFailure("Model labels or features are incompatible; retrain locally.")
        return model
    except MLFailure:
        raise
    except Exception:
        raise MLFailure("Model files are missing or corrupt; retrain locally.") from None


def predict_category(model: dict, email: Mapping) -> Prediction:
    if not TOKEN_PATTERN.search(normalize_email(email)):
        raise MLFailure("Email has no usable text for a category prediction.")
    try:
        pipeline = model["pipeline"]
        probabilities = pipeline.predict_proba([email])[0]
        if (len(probabilities) != len(pipeline.classes_)
                or not np.isfinite(probabilities).all()
                or (probabilities < 0).any() or (probabilities > 1).any()
                or not np.isclose(probabilities.sum(), 1)):
            raise MLFailure("Model produced invalid category probabilities.")
        index = int(probabilities.argmax())
        return Prediction(
            category=str(pipeline.classes_[index]), confidence=float(probabilities[index] * 100),
            model_version=model["metadata"]["model_version"],
        )
    except MLFailure:
        raise
    except Exception:
        raise MLFailure("Category prediction failed; check the local model.") from None
