# Architecture

## Status and scope

This document describes the **proposed MVP architecture** for the local-first smart email classifier. The repository is currently a minimal Python project template; the services and workflows below are design targets, not claims about already implemented features.

The MVP retrieves mail over IMAP, stores the minimum useful data locally, supports manual labels, trains and evaluates a traditional ML category model, assigns a basic priority, and presents the results in a React Smart Inbox backed by a FastAPI service. It does not send mail or modify the mailbox.

## Design principles

- **Local by default:** email parsing, inference, database storage, and model files stay on the user's machine. Cloud services are not required.
- **Small operational footprint:** one frontend and one backend process, with SQLite as a local file. Add background or database infrastructure only when real needs justify it.
- **Privacy by design:** credentials are kept out of source control; logs exclude message bodies; private datasets and trained artifacts are not committed.
- **Replaceable boundaries:** keep IMAP, persistence, classification, and HTTP presentation behind separate modules so each can evolve without making the MVP distributed.
- **Human correction:** predictions are suggestions. Users can label or correct them, and corrections become labeled examples for later training.

## System context

```text
┌─────────────────┐      IMAP       ┌─────────────────────────┐
│ Email provider  │ ◀─────────────▶ │ Python backend          │
└─────────────────┘                │                         │
                                    │ IMAP sync → parse →     │
                                    │ classify → persist      │
                                    └────────────┬────────────┘
                                                 │
                                  ┌──────────────┴──────────────┐
                                  │                             │
                           ┌──────▼──────┐               ┌──────▼──────┐
                           │ SQLite file │               │ Local model │
                           └──────┬──────┘               └─────────────┘
                                  │ REST API
                           ┌──────▼──────┐
                           │ React UI    │
                           └─────────────┘
```

The backend owns mailbox synchronization, parsing, persistence, ML inference, and the HTTP API. The frontend requests data and submits labels or corrections; it does not connect to IMAP or access the database directly.

## Runtime components

### React client

The client provides the Smart Inbox, email list and details, category and priority filters, confidence and “Needs Review” indicators, manual labels, correction controls, and a dashboard category treemap. It communicates with FastAPI over a local HTTP connection. The treemap is an MVP requirement and is part of the frontend-first Open Design integration, initially using synthetic data.

#### Dashboard treemap

Each nonzero category is a rectangle whose area is proportional to its email count. Use consistent category colors, readable labels, and hover/focus details showing category, count, and percentage. Category selection filters or navigates to the corresponding Smart Inbox messages. Provide keyboard access and an equivalent category/count list so small tiles and color are not the only way to read or use the dashboard. Include loading, empty, and error states and responsive layouts.

The backend computes counts across **all locally stored messages**, independent of inbox pagination and filters. Resolve each message's effective category from its human label first, then its model prediction, otherwise Unclassified. Unclassified is a display bucket distinct from the Other category. Count each message once, derive percentages from the same total, and refresh the dashboard after sync, labeling, correction, or new predictions. Priority and confidence remain separate from the treemap's category counts.

The dashboard API returns aggregate category/count data and the total, rather than email bodies, senders, or subjects. Compute aggregates from existing SQLite records; no additional service or analytics store is needed. Render the chart locally without exporting email data to a chart provider.

### FastAPI application

The API coordinates application use cases and exposes inbox data and user actions. Keep routes thin: validate requests, call service-layer operations, and serialize responses. The service layer coordinates the repository, IMAP adapter, parser, and classifier.

Initial API capabilities should include:

- List and retrieve locally stored messages, with filtering and pagination.
- Start or request a mailbox sync and report its outcome.
- Add or change a category or priority label.
- Record a correction separately from the original prediction.
- Return model/evaluation status and dashboard category counts and totals for the treemap.

Exact route names and API versioning can be decided during implementation; this document does not prescribe a particular URL scheme.

### IMAP adapter and email parser

The IMAP adapter retrieves recent or unread messages and maps provider-specific responses into an internal message representation. The parser extracts the message identifier, sender, subject, received date, read state, attachment-presence flag, and a clean plain-text body. HTML-only content is converted to text before storage or inference.

Sync should be repeatable: use the provider message identifier (scoped to the account/mailbox as needed) to upsert rather than duplicate a message. Do not mark mail read, delete it, move it, or otherwise change mailbox state as part of MVP sync.

### Persistence

SQLite is the initial database and requires no separate server. Use a persistence boundary (for example, a repository layer) so a later move to PostgreSQL does not leak database details into API or ML code. SQLAlchemy and Alembic are candidate implementation choices, not prerequisites imposed by this design.

The conceptual data model is:

| Record | Purpose | Main information |
| --- | --- | --- |
| Email | Locally available inbox item | Provider message ID, sender, subject, plain-text body, received time, read state, attachment flag, sync metadata |
| Classification | Current model output | Category, confidence, priority, model/version reference, prediction time |
| Label / feedback | Human-provided ground truth | Category and priority labels, source (manual or correction), creation time |
| Sync state | Incremental retrieval bookkeeping | Account/mailbox reference, cursor or last-sync time, last result |

These are logical records; schema, retention, and whether feedback is stored as a separate table or fields are implementation decisions. Avoid storing email fields that are not needed by the MVP. Treat locally stored email and SQLite backups as sensitive user data.

### Classification and training

Category and priority are independent outputs. The first category baseline uses a scikit-learn pipeline over sender, subject, and body:

```text
normalized email text → TF-IDF → Logistic Regression → category + confidence
```

The starting category set is Recruitment, LinkedIn, Personal, Transaction, Newsletter, Promotion, Spam, and Other. The taxonomy may change after inspecting labeled data. Low-confidence predictions are surfaced as “Needs Review”; the threshold should be configurable and selected from validation results rather than assumed to be a universal constant.

Priority is High, Medium, or Low. Begin with transparent rules or a separate simple model; do not conflate priority with category. Model training is an explicit local command or controlled workflow in the MVP, not continuous or automatic retraining. Training must use a train/test split and report per-class precision, recall, F1, macro F1, and a confusion matrix. Accuracy alone is not sufficient for imbalanced labels.

Persist the fitted preprocessing and estimator together as a versioned local artifact (Joblib is the proposed format). The runtime loads the artifact for inference and handles a missing model gracefully, such as exposing predictions as unavailable until a model is trained. Artifacts and datasets containing personal data must be excluded from Git.

### Background synchronization

Start with an explicit “sync now” operation. If periodic sync is added for the MVP, use a lightweight in-process scheduler such as APScheduler, with one owner for the job and visible last-sync status. Avoid Celery, Redis, or a separate worker until measured workload or reliability requirements call for them.

## Main data flows

### Ingestion and prediction

1. A user configures an IMAP account using local configuration/secrets.
2. The backend fetches recent or unread messages.
3. The parser normalizes headers and converts the body to clean text.
4. The backend upserts the message locally using its stable provider identifier.
5. If a trained model is available, category and confidence are predicted; priority is assigned independently.
6. The Smart Inbox reads the stored message and prediction through the API.

### Labeling and feedback

1. The user assigns a category and/or priority, or corrects a prediction.
2. The API validates the label against the active taxonomy and stores the human label while retaining prediction history as needed.
3. The labeled example becomes eligible for a later local training run.
4. A training run evaluates a new model before replacing the active artifact.

## Suggested code organization

The current repository has an `app/` directory, but no application modules yet. A small initial structure could be:

```text
app/
├── api/          # FastAPI routes and request/response schemas
├── email/        # IMAP adapter and message parsing
├── ml/           # preprocessing, training, evaluation, inference
├── models/       # domain/schema definitions
├── services/     # sync, labeling, and inbox use cases
└── database/     # SQLite setup and repositories
frontend/         # React application (to be added)
data/             # Local-only data; sample fixtures may be checked in
models/           # Local-only trained artifacts
```

Keep private email data, account credentials, tokens, database files, and trained artifacts out of version control. Synthetic or anonymized examples may be committed for documentation and automated checks.

## Local deployment and configuration

The MVP should run from a clean local setup with the fewest necessary processes. Docker/Compose may package the React client and FastAPI backend; SQLite remains a mounted local file. A direct development workflow is also appropriate. PostgreSQL is a later option, not an MVP dependency.

Secrets come from environment variables or a local secrets mechanism and are never committed. `.env.example` documents variable names without real credentials. Bind local endpoints to loopback by default where practical. Sanitize logs and never log full message bodies, credentials, or tokens.

SMTP, cloud hosting, external LLM APIs, Redis, Celery, Kubernetes, and MLflow are outside the MVP runtime.

## Quality and delivery

The planned GitHub Actions workflow should run on pull requests and pushes to development branches. It should install dependencies, lint, run backend and ML checks, run frontend checks, build the application, and validate the Docker image when those components exist. ML checks should cover preprocessing, artifact loading, prediction shape/classes, and malformed or missing fields. Dashboard checks should cover aggregate totals, effective-category precedence, Unclassified messages, pagination independence, category navigation, refresh after corrections, and accessible empty/error states. CI fixtures must be synthetic or anonymized.

Continuous Integration is in scope; automatic production deployment is not required. A local release may package the application, Compose configuration, and an explicitly versioned model artifact without requiring a hosted service.

## Constraints and future evolution

The architecture intentionally leaves extension points for PostgreSQL, richer scheduling, more advanced classifiers, local LLM capabilities, and optional cloud integrations. None should be introduced before the local workflow is useful and reliable. If an LLM is later added, it should be an optional layer with explicit privacy controls; email content must not be sent to an external provider by default.

## MVP acceptance path

The end-to-end path is complete when a user can sync real mail over IMAP, review locally stored messages, label examples, train and evaluate a model, receive category/confidence and priority predictions, correct them, and use the Smart Inbox and an accurate category treemap locally with reproducible setup and CI checks.
