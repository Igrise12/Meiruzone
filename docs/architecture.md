# Architecture

## Status and scope

This document describes the MVP architecture for the local-first smart email classifier. Tasks 1–6 are implemented: React Smart Inbox/API integration, FastAPI/SQLite, safe IMAP ingestion, persistent human labels, and local category training/evaluation with versioned artifacts. Approved model loading, sync-time category inference, independent bilingual priority rules, persisted review cutoffs/errors, and Model lab evaluation display are implemented.

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

The implemented inbox, labels, category-statistics, and sync foundation use `/api/v1`; see the [API contract](api-contract.md) for exact shapes and behavior. Model/evaluation endpoints remain future work.

### IMAP adapter and email parser

The IMAP adapter uses IMAPClient for protocol response parsing, mailbox-name encoding, and selective MIME-part fetches. One configured account/folder is opened read-only over verified implicit TLS, with 30-second connection/read timeouts. It selects the highest matching UIDs, excluding Deleted and additionally requiring UNSEEN in unread mode. Requests default to 50 messages and are capped at 100. Retrieval uses BODY.PEEK for headers and text parts, omitting attachment payloads and full raw-message retention.

The parser uses Python's email package and HTMLParser, with plain-text preference over HTML alternatives and no HTML execution or resource fetching. Headers/MIME headers share a 64 KiB budget and selected encoded text parts share a 1 MiB budget per message. MIME traversal stops at depth 20/100 parts. Malformed or oversized messages are skipped; missing fields have safe defaults. Received time prefers timezone-aware INTERNALDATE, then a valid aware Date header, then sync time. Read state comes from FLAGS; attachment presence includes non-body inline parts and attached messages. Library wire logging is suppressed to prevent DEBUG traces from exposing private content.

Each message is identified by account/folder/UIDVALIDITY/UID and mapped to an opaque local ID. Account scope hashes host/port/username and excludes passwords. Message-ID is stored as optional internal metadata and is not unique. UIDVALIDITY changes stop sync before fetching, preserving all local records and labels. Recovery uses a separate database, as documented in the [setup guide](../README.md#sync-real-mail). Remote flag changes are refreshed only in the selected window; remote removal never deletes local records. Sync uses logout and never marks read, moves, deletes, or sends mail.

### Persistence

SQLite uses the standard-library `sqlite3` module and a repository boundary. Version 2 adds scoped mailbox/message identity and progress fields to version 1's emails, predictions, human labels, and singleton sync state. Version 3 adds each prediction's review cutoff (legacy default 70; null means review all) and sanitized category error. Numbered migrations are transactional and preserve existing records and demo state. Foreign keys, value constraints, parameterized queries, and short transactions remain in use. Schema versioning uses `PRAGMA user_version`; unknown versions are rejected without resetting data.

The conceptual data model is:

| Record | Purpose | Main information |
| --- | --- | --- |
| Email | Locally available inbox item | Provider message ID, sender, subject, plain-text body, received time, read state, attachment flag, sync metadata |
| Classification | Current model output | Category, confidence, priority, model/version reference, prediction time |
| Label / feedback | Human-provided ground truth | Category and priority labels, source (manual or correction), creation time |
| Mailbox / IMAP identity | Repeatable scoped upserts | Account scope, folder, expected UIDVALIDITY, UID, local email ID, optional Message-ID |
| Sync state | Bounded retrieval bookkeeping | Running/last outcome, timestamps, imported/processed/total/skipped, sanitized error code |

Human labels store independently optional category and priority plus a server timestamp and manual/correction source, without feedback history. Partial label updates preserve omitted fields and never update predictions. The frontend saves only newly confirmed or changed fields, keeps unsaved drafts during failures/refreshes, and reads the server Needs Review flag. Unconfirmed choices are blank instead of default ground truth. `Repository.category_training_examples()` joins messages with human categories only; unverified predictions and priority-only labels are excluded. The sync service fills missing category/priority outputs before persistence, preserving completed predictions and all human labels. Each message, identity mapping, prediction, and progress update commit atomically. Inference failures retain the message and priority and remain separate from IMAP outcomes. Skips/failures retain previous imports for safe retry. Local mail is retained until explicit local deletion; database/backup permissions, SQLite backup, restore, and deletion procedures are in the [setup guide](../README.md#local-data-retention-backup-and-deletion).

### Classification and training

Category and priority are independent outputs. `uv run python -m app.train` trains the category baseline from human labels using a read-only version 2 or 3 SQLite connection. It does not initialize/migrate storage, seed messages, access IMAP, or activate a model. The scikit-learn pipeline combines sender name/address, subject, and body:

```text
normalized email text → TF-IDF → Logistic Regression → category + confidence
```

The starting category set is Recruitment, LinkedIn, Personal, Transaction, Newsletter, Promotion, Spam, and Other. Training requires at least two categories with ten distinct usable examples each; missing and underrepresented categories are reported and excluded. Shared preprocessing applies Unicode NFKC, case folding, and whitespace cleanup; missing fields are empty, invalid field types are rejected, and tokenless examples are excluded. Exact normalized duplicates collapse before splitting; conflicting duplicate labels stop training. Similar templates/threads are not grouped, a documented limitation.

Seed 42 produces stratified approximately 60/20/20 training/validation/test splits after deterministic content ordering. Full pipelines fit only the training split, preventing held-out vocabulary/IDF leakage. Validation macro F1 selects Logistic Regression C from 0.1/1/10 with smaller-C tie breaking; TF-IDF keeps its defaults without a stop-word list. The selected fitted model is not refitted on validation/test examples. The test set is evaluated once after selection, reporting per-class precision/recall/F1/support, macro F1, and a confusion matrix ordered by the saved supported classes.

Confidence is maximum class probability × 100. The validation-selected cutoff accepts at least five messages at 90% or greater observed accuracy, taking the lowest qualifying confidence; equality is accepted. A null cutoff means review all, including confidence 100. Validation/test review coverage and accepted accuracy are recorded separately. Validation reuse for tuning/cutoff selection and small sample counts limit reliability; probabilities are uncalibrated and validation accuracy does not guarantee future accuracy. Each inference persists its artifact cutoff; switching models does not change earlier cutoffs. An explicitly configured numeric review threshold overrides all saved cutoffs at read time, including review-all. SQL filtering and response flags use the same comparison; human category labels suppress review, while missing categories/confidence stay outside it.

Priority is High, Medium, or Low. `priority-rules-v1` independently matches normalized English/Indonesian subject/body signals with High precedence, recognized negated-action suppression, and a Medium default; it continues when category inference is unavailable. Exact phrases and limitations are documented in the [priority rules](../README.md#independent-priority-rules). Model training is an explicit local command or controlled workflow in the MVP, not continuous or automatic retraining. Training must use a train/test split and report per-class precision, recall, F1, macro F1, and a confusion matrix. Accuracy alone is not sufficient for imbalanced labels.

Each training run atomically publishes a private version directory under ignored `models/`, containing a Joblib bundle of fitted preprocessing/estimator/metadata and an aggregate JSON evaluation report. Metadata records artifact/preprocessing versions, model version/time, supported class ordering, class/split counts, parameters, review cutoff, limitations, and exact dependency versions. A staged load check precedes publication; failures preserve older runs. Directories/files use 0700/0600 permissions. The loader requires an explicitly selected trusted local run and rejects missing/corrupt/incompatible artifacts; checks do not make untrusted Joblib files safe. Model vocabularies can contain private terms and must remain out of Git. See the [training guide](../README.md#train-and-evaluate-the-category-model) for commands, privacy, metrics, and recovery. The backend loads the explicitly approved `MEIRUZONE_MODEL_DIRECTORY` once at startup; changing it requires restart. Unconfigured/invalid models leave inbox/sync available. `GET /api/v1/model` supplies sanitized status, version, supported categories, effective cutoff/override state, and allowlisted aggregate evaluation. Model lab uses saved class order for matrix axes and leaves excluded categories without scores. Per-message `categoryError` distinguishes unavailable models from inference failures; subsequent sync retries missing categories. Demo mode does not load models. No automatic retraining, model selection, or backfill occurs.

### Background synchronization

The current “sync now” operation is synchronous, with persisted progress available to concurrent GET requests. An atomic database claim rejects overlapping POST requests with 409. Successful/partial runs return 200; failures before processing return sanitized 503 errors. Startup recovers running records as interrupted without discarding commits. Run one backend process/worker per database. Periodic scheduling remains deferred.

## Main data flows

### Ingestion and prediction

1. A user configures an IMAP account using local configuration/secrets.
2. The backend fetches recent or unread messages.
3. The parser normalizes headers and converts the body to clean text.
4. The backend reads any previous prediction using the scoped provider identity.
5. Missing category/confidence outputs use the approved model when available; missing priority uses independent text rules. Category failures retain a sanitized error and priority.
6. Message, identity, predictions, and progress commit atomically, preserving completed predictions and human labels.
7. The Smart Inbox reads the stored message and prediction through the API.

### Labeling and feedback

1. The user assigns a category and/or priority, or corrects a prediction.
2. The API validates the label against the active taxonomy and stores the human label while retaining prediction history as needed.
3. The labeled example becomes eligible for a later local training run.
4. A training run evaluates a new model before replacing the active artifact.

## Suggested code organization

The small backend uses focused modules with the same responsibility boundaries:

```text
app/
├── main.py       # Composition, lifespan, access controls, sanitized errors
├── api.py        # Thin HTTP routes
├── models.py     # Domain records and request/response schemas
├── services.py   # Inbox, labeling, aggregates, and sync orchestration
├── database.py   # SQLite initialization and repository
├── config.py     # Backend environment configuration
├── imap.py       # Verified TLS, read-only selection, selective bounded fetches
├── parser.py     # Header decoding, normalized records, safe HTML-to-text
├── ml.py         # Shared category preprocessing, trusted loading, prediction helper
├── train.py      # Explicit category fitting, validation/test evaluation, atomic artifacts
└── demo.py       # Synthetic seed records
frontend/         # React Smart Inbox, HTTP/fixture adapters, and integration checks
tests/            # Synthetic API/config/storage/IMAP/parser/ML checks
data/             # Ignored local databases
models/           # Ignored private versioned model artifacts and evaluation reports
```

Keep private email data, account credentials, tokens, database files, and trained artifacts out of version control. Synthetic or anonymized examples may be committed for documentation and automated checks.

## Local deployment and configuration

The MVP should run from a clean local setup with the fewest necessary processes. Docker/Compose may package the React client and FastAPI backend; SQLite remains a mounted local file. A direct development workflow is also appropriate. PostgreSQL is a later option, not an MVP dependency.

Secrets come from backend process environment variables and are never committed. An ignored private `.env` may be explicitly loaded by `uv run --env-file`; `.env.example` contains safe placeholders. Password/app-password login is supported through backend-only IMAP settings; passwords are masked, excluded from settings serialization, and never stored in SQLite or returned by the API. OAuth and simultaneous account/folder configuration remain future work.

The documented Uvicorn startup binds to `127.0.0.1:8001` with access logging disabled. Host names are limited to loopback, and browser origins to an explicit local allowlist. All writes require JSON and `X-Meiruzone-Request: 1`, with an actual 4096-byte body limit; foreign/null origins are rejected. This protects against unsolicited browser writes, not programs already running as the local user. Errors and application logs omit input values, bodies, and private exception details. See the [implemented API contract](api-contract.md) and root README for startup, configuration, and verification.

SMTP, cloud hosting, external LLM APIs, Redis, Celery, Kubernetes, and MLflow are outside the MVP runtime.

## Quality and delivery

The GitHub Actions workflow runs on pull requests, development/main pushes, and manual dispatch with read-only permissions and SHA-pinned actions. Separate jobs install locked dependencies and run backend/ML tests, Ruff and focused configuration/API-model typing, frontend checks/builds/audits, real HTTP integration, digest-pinned container builds and a synthetic Chromium workflow, and redacted Git-history secret scanning. ML checks cover preprocessing, artifact loading, prediction shape/classes, and malformed or missing fields. Dashboard checks cover aggregate totals, effective-category precedence, Unclassified messages, pagination independence, category navigation, refresh after corrections, and accessible empty/error states. Fixtures use isolated synthetic data. The [delivery guide](delivery.md) documents clean-clone setup, loopback-only Compose defaults, persistent private host mounts, one-off training, backups, checks, and source releases that exclude private data/models.

Continuous Integration is in scope; automatic production deployment is not required. A local release may package the application, Compose configuration, and an explicitly versioned model artifact without requiring a hosted service.

## Constraints and future evolution

The architecture intentionally leaves extension points for PostgreSQL, richer scheduling, more advanced classifiers, local LLM capabilities, and optional cloud integrations. None should be introduced before the local workflow is useful and reliable. If an LLM is later added, it should be an optional layer with explicit privacy controls; email content must not be sent to an external provider by default.

## MVP acceptance path

The end-to-end path is complete when a user can sync real mail over IMAP, review locally stored messages, label examples, train and evaluate a model, receive category/confidence and priority predictions, correct them, and use the Smart Inbox and an accurate category treemap locally with reproducible setup and CI checks.

The [task 8 acceptance report](acceptance.md) separates local synthetic evidence from final acceptance. Real HTTP checks now derive training data entirely from API-confirmed human labels, verify read-only training, require explicit model selection/restart for each version, and preserve completed predictions and corrections through replacement. Chromium checks built containers, keyboard controls, mobile overflow, loading/error recovery and browser network destinations; screenshots use synthetic data only. Clean extracted source is also verified without checkout Git metadata.

As of 5 October 2026, automated acceptance passes but the MVP is not yet accepted. The dedicated live IMAP walkthrough, including provider-side flag comparison, and final fidelity comparison with the original Open Design handover remain required. Hosted CI evidence is distinct from local command results. No public API or runtime architecture changes were needed for this review.
