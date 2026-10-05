# Meiruzone

A local-first Smart Inbox that will classify email, estimate its priority, and learn from user corrections. Meiruzone aims to make email easier to review while keeping message processing, storage, and machine-learning inference on the user's computer.

## Project status

The React Smart Inbox runs locally with synthetic email data. The FastAPI backend provides validated inbox, labeling, category statistics, and explicit read-only IMAP sync backed by SQLite. Tasks 1–3 are implemented. The frontend still uses its fixture adapter; frontend API integration and trained models remain planned work.

Development starts with the **Open Design frontend handover**, using its design and source as the foundation. The frontend runs with synthetic email data, followed by backend integration and the ML workflow. See the [project task list](docs/TO-DO.md) for the current delivery order and completion criteria.

## Planned MVP

- Connect an email account through IMAP and retrieve recent or unread messages.
- Parse and store the required email fields in a local SQLite database.
- Organize messages by category and a separate High, Medium, or Low priority.
- Display predictions, confidence, filters, email details, and basic statistics in a React Smart Inbox.
- Visualize category distribution in a dashboard treemap, with rectangle sizes based on email counts and category selection opening the matching inbox messages.
- Flag low-confidence predictions as **Needs Review**.
- Let users label messages, correct predictions, and retain feedback for later training.
- Train, evaluate, and run a traditional ML classifier locally.

The initial categories are **Recruitment, LinkedIn, Personal, Transaction, Newsletter, Promotion, Spam, and Other**. The taxonomy may be adjusted after inspecting labeled data.

## How the application will work

```mermaid
flowchart TD
    Account[Email account] -->|Read-only IMAP retrieval| Backend[FastAPI backend]
    Backend --> Parser[Email parsing and text cleanup]
    Parser --> Classifier[Category model and separate priority logic]
    Classifier --> Database[(Local SQLite database)]
    Backend <--> Database
    Backend <-->|Local API| Frontend[React Smart Inbox]
    Frontend -->|Labels and corrections through the API| Labels[Local labeled dataset]
    Labels --> Training[Explicit training and evaluation]
    Training --> Model[Local model artifact]
    Model --> Classifier
```

The category baseline uses **sender + subject + body → TF-IDF → Logistic Regression** to produce a category and confidence. Priority is assigned independently using simple rules or a separate baseline model. Retraining is a deliberate local operation in the MVP.

Model evaluation will include per-class precision, recall, F1, macro F1, and a confusion matrix, with held-out data to measure performance.

## Proposed technology

| Area | Planned approach |
| --- | --- |
| Frontend | React, based on the Open Design handover |
| Backend | Python and FastAPI |
| Email retrieval | IMAPClient over verified TLS |
| Local storage | SQLite |
| Machine learning | scikit-learn, TF-IDF, Logistic Regression |
| Model persistence | Local Joblib artifacts |
| Packaging | Docker and optional Docker Compose |
| Continuous integration | GitHub Actions |

React, FastAPI, SQLite, and safe IMAP ingestion are implemented. Machine learning, packaging, and CI remain later milestones.

## Privacy and security

The MVP is designed to process and store email locally without requiring cloud infrastructure or external AI services. IMAP retrieval uses verified TLS, read-only folder selection, and non-marking text-part fetches to preserve mailbox state. Attachment payloads stay on the server.

Credentials stay outside source code and the application database. Ignore rules exclude private local data, databases and sidecars, datasets, models, and secrets. Only synthetic examples belong in automated tests.

The frontend renders content as escaped plain text. The backend validates API inputs, restricts Host names and browser origins to explicitly allowed local values, and requires JSON plus a local request marker for writes. Errors and application logs omit private input and exception details. The documented startup disables HTTP access logging so search queries do not appear in logs.

## Development roadmap

1. Receive and integrate the Open Design frontend, including the dashboard treemap, with synthetic data, interaction tests, and security checks.
2. Agree the frontend/backend API contract and establish FastAPI foundations.
3. Implement local storage and safe IMAP ingestion.
4. Connect the frontend and dashboard aggregates to local data and build a human-labeled dataset.
5. Train and evaluate the category baseline.
6. Add inference, independent priority assignment, and the feedback loop.
7. Complete local packaging, reproducible setup, and CI.
8. Validate the complete MVP workflow and review security.

Frontend CI should start in the first phase and expand as backend and ML components are introduced.

## Repository structure

```text
Meiruzone/
├── app/                  # FastAPI routes, models, services, SQLite, configuration
├── docker/               # Placeholder for container configuration
├── docs/
│   ├── architecture.md   # Proposed system design and data flows
│   ├── api-contract.md   # Implemented HTTP shapes and frontend adapter mapping
│   ├── client-brief.md   # Product goals, scope, and success criteria
│   └── TO-DO.md          # Frontend-first implementation checklist
├── frontend/             # Vite + React + TypeScript Smart Inbox preview
│   ├── src/              # Inbox UI, synthetic fixtures, adapter, and treemap
│   ├── tests/            # Component and aggregate tests
│   └── README.md         # Frontend setup and verification commands
├── playground/           # Placeholder for experiments and notebooks
├── tests/                # Backend API/storage tests with temporary synthetic data
├── data/                 # Ignored local database; created at backend startup
├── .env.example          # Safe backend configuration template
├── hello.py              # Python starter entry point
├── pyproject.toml        # Python metadata and dependencies
└── uv.lock               # Locked Python dependencies
```

The backend creates local data storage on startup. The model artifact directory will be added with the ML workflow.

## Set up the backend

Prerequisites: Git, Python 3.12 or newer, and `uv`.

```bash
git clone --branch development https://github.com/Igrise12/Meiruzone.git
cd Meiruzone
uv sync
uv run uvicorn app.main:app --host 127.0.0.1 --port 8000 --no-access-log
```

Run commands from the repository root. The backend creates an empty SQLite database at `data/meiruzone.sqlite3`, without contacting a mailbox. The application schema is available at `http://127.0.0.1:8000/openapi.json`; see the [API contract](docs/api-contract.md) for examples and the task 4 frontend mapping. Interactive API documentation is disabled to avoid external assets. The unused starter remains runnable with `uv run hello.py`.

To exercise the API with ten synthetic messages, use a separate demo database:

```bash
MEIRUZONE_DEMO=true MEIRUZONE_DATABASE_PATH=data/demo.sqlite3 uv run uvicorn app.main:app --host 127.0.0.1 --port 8000 --no-access-log
```

Demo messages seed once in an empty database; the seeder leaves existing records alone. Corrections survive restart, and demo sync is an explicitly identified no-op. Use separate databases for demo and personal mail.

```bash
curl 'http://127.0.0.1:8000/api/v1/emails?needsReview=true&limit=10'
curl http://127.0.0.1:8000/api/v1/category-stats
curl -X PATCH http://127.0.0.1:8000/api/v1/emails/demo-01/labels \
  -H 'Content-Type: application/json' -H 'X-Meiruzone-Request: 1' \
  --data '{"category":"Personal","source":"correction"}'
curl -X POST http://127.0.0.1:8000/api/v1/sync \
  -H 'Content-Type: application/json' -H 'X-Meiruzone-Request: 1' \
  --data '{"mode":"recent","limit":50}'
```

### Local configuration

Use process environment variables, or copy the safe `.env.example` to an ignored `.env`, keep it readable only by your user, and load it explicitly:

```bash
uv run --env-file .env uvicorn app.main:app --host 127.0.0.1 --port 8000 --no-access-log
```

| Variable | Default |
| --- | --- |
| `MEIRUZONE_DATABASE_PATH` | `data/meiruzone.sqlite3` relative to the working directory |
| `MEIRUZONE_DEMO` | `false` |
| `MEIRUZONE_REVIEW_THRESHOLD` | `70`, in the range 0–100 |
| `MEIRUZONE_FRONTEND_ORIGINS` | `http://localhost:5173,http://127.0.0.1:5173` |
| `MEIRUZONE_IMAP_HOST` | Unconfigured; hostname or IP address, without a URL |
| `MEIRUZONE_IMAP_PORT` | `993`, in the range 1–65535; always implicit TLS |
| `MEIRUZONE_IMAP_USERNAME` | Unconfigured |
| `MEIRUZONE_IMAP_PASSWORD` | Unconfigured; password or provider app password |
| `MEIRUZONE_IMAP_MAILBOX` | `INBOX`; one configurable folder |

Origins must be explicit loopback origins without paths or wildcards. To allow a different frontend port, add its exact origin to the comma-separated list. IMAP host, username, and a nonempty password are all required to enable real sync. Incomplete configuration keeps local inbox access available and reports sync unavailable. Control characters in IMAP configuration are rejected; passwords are masked in settings and excluded from serialization. The account scope stores a hash of host/port/username, with no password.

SQLite files are created with user-only permissions. Schema version 2 uses `PRAGMA user_version`, with a transactional migration from version 1 preserving emails, predictions, labels, and demo state. Unknown versions are refused without deleting data. Ingestion updates message fields while leaving predictions and human labels intact.

### Sync real mail

Copy `.env.example` to an ignored `.env`, set the provider's IMAP host, username, and password/app password, keep `MEIRUZONE_DEMO=false`, and choose a personal-mail database. Protect the file with `chmod 600 .env`, then start the backend using the `--env-file .env` command above. Startup creates/migrates local storage without contacting IMAP. Run one backend process with one Uvicorn worker per database.

Use the earlier `POST /api/v1/sync` example to retrieve up to 50 recent messages, or request `{"mode":"unread","limit":50}` for unread mail. The maximum limit is 100. Recent mode selects the highest UIDs; unread mode additionally requires UNSEEN. Both exclude messages flagged Deleted. Each sync refreshes only that newest matching window, including read state; older records remain as previously stored. Remote deletion never removes a local copy.

IMAPClient supplies parsed protocol responses and mailbox-name encoding, avoiding a custom IMAP response parser. Connections verify certificates and hostnames and use 30-second connection/read timeouts. Headers and selected MIME headers share a 64 KiB budget per message; selected encoded text payloads share a 1 MiB budget. MIME traversal is capped at depth 20 and 100 parts. Plain text is preferred over HTML alternatives. HTML conversion runs locally, ignores scripts/styles, and makes no network requests. Received time uses timezone-aware INTERNALDATE, then a valid timezone-aware Date header, then sync time. Missing sender/subject use `Unknown sender`/`(No subject)`; messages without a usable text body store an empty body. Malformed or oversized messages are skipped without fetching attachments.

Poll `GET /api/v1/sync` from another client to observe progress. The synchronous POST returns its final outcome: HTTP 200 for succeeded/partial, 503 when sync cannot proceed, and 409 for an overlapping request. `imported` counts new rows; `processed` counts successfully stored or skipped messages, and `total` is the selected UID count. Partial failures retain committed imports, so retrying safely upserts them. A restart marks an unfinished run with `sync_interrupted`. See the [API contract](docs/api-contract.md#sync) for counters and error codes. IMAPClient wire logs are suppressed even when application DEBUG logging is enabled; keep Uvicorn access logging disabled as documented.

If a folder's UIDVALIDITY changes, sync stops with `imap_uidvalidity_changed` before fetching messages. Keep the existing database and its human labels, stop the backend, set `MEIRUZONE_DATABASE_PATH` to a new unused file, and restart to import the new folder generation. Labels stay in the old database; automatic reconciliation or label transfer is outside this recovery policy. OAuth and simultaneous account/folder selection remain future capabilities.

### Local data retention, backup, and deletion

Emails and human labels are retained until you explicitly remove local data. Database files, sidecars, private `.env` files, and backups contain sensitive information. Keep private directories user-only (`0700`) and files user-only (`0600`), use encrypted storage where needed, and keep these files out of Git and shared folders. The ignore rules include SQLite files/sidecars, `/data/`, `/backups/`, and private environment files.

Stop the backend before backup or restore. For the default database, create a backup using Python's SQLite backup operation (choose a new backup filename for each run):

```bash
umask 077
mkdir -p backups
chmod 700 backups
uv run python - <<'PY'
import os
import sqlite3
from contextlib import closing
from pathlib import Path

source = Path("data/meiruzone.sqlite3").resolve()
backup = Path("backups/meiruzone-backup.sqlite3")
descriptor = os.open(backup, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
os.close(descriptor)
with closing(sqlite3.connect(source.as_uri() + "?mode=ro", uri=True)) as original:
    with closing(sqlite3.connect(backup)) as saved:
        original.backup(saved)
        assert saved.execute("PRAGMA integrity_check").fetchone() == ("ok",)
PY
```

Adjust `source` for a custom database. The exclusive create prevents overwriting an existing backup. To restore, verify the backup with `PRAGMA integrity_check`, copy it to a new unused database filename, enforce `0600` permissions, and set `MEIRUZONE_DATABASE_PATH` to that filename before starting the backend. Preserve the previous database until the restored inbox and labels have been checked. Backups preserve schema version and are migrated on startup when supported.

For complete local deletion, stop the backend and remove the configured database plus its matching `-journal`, `-wal`, and `-shm` sidecars, and any backups you choose to delete. This removes local emails and labels, leaves the provider mailbox unchanged, and creates an empty database on next startup. Later sync can import provider messages again. File removal does not guarantee forensic erasure from the underlying storage; backup copies follow their own retention.

Frontend setup commands are documented in [frontend/README.md](frontend/README.md). Its browser-stored demo labels remain separate from SQLite.

## Run the frontend preview

Requirements: Node.js 20.19+ or 22.12+ and npm 10+. From `frontend/`:

```bash
npm install
npm run dev
```

Vite prints the local preview URL. Check the frontend with `npm test`, `npm run lint`, `npm run typecheck`, and `npm run build`. The demo does not connect to a mailbox; confirmed labels stay in browser local storage.

## Testing and quality

Run backend checks from the repository root:

```bash
uv run python -m unittest discover -s tests
uv lock --check
```

Backend tests use temporary SQLite files and synthetic messages, covering API validation, access restrictions, migration rollback, MIME parsing, selective IMAP fetches, TLS/timeouts, deduplication, interrupted/concurrent sync, retained labels/predictions, and sanitized errors/debug logs. No personal mailbox or credentials are needed. Frontend checks are listed above. CI and the remaining integration/ML checks are planned:

- Frontend filtering, labeling, correction, treemap category navigation, loading/error states, accessibility, and safe content rendering.
- Dashboard category counts, percentages, human-label precedence, Unclassified messages, and refresh after sync or corrections.
- Backend input validation, persistence, API integration, and local access restrictions.
- ML preprocessing, saved-model loading, valid predictions, missing fields, and missing or corrupt models.
- The full ingestion-to-correction workflow using isolated storage and synthetic fixtures.
- Linting, applicable type checks, production/container builds, dependency checks, and secret scanning in CI.

See [TO-DO.md](docs/TO-DO.md) for testing and security tasks attached to each milestone.

## MVP scope boundaries

The first release will not send or reply to email, delete or move messages, replace a complete email client, or perform automatic continuous retraining. Large Transformer models, LLM features, cloud deployment, and distributed infrastructure are deferred.

Future experiments may add local LLM summaries, action items, semantic search, or low-confidence fallback after the core workflow is reliable.

## Project documentation

- [Client brief](docs/client-brief.md): intended users, product experience, MVP scope, and success criteria.
- [Architecture](docs/architecture.md): proposed components, data flows, local deployment, and constraints.
- [API contract](docs/api-contract.md): implemented endpoints, examples, validation, and frontend mapping.
- [Task list](docs/TO-DO.md): current frontend-first delivery order, testing, security, and milestone acceptance.
