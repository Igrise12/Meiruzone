# Meiruzo frontend

The React Smart Inbox uses the local FastAPI API by default. Lists, filters, 50-message pages, selected-message details, sync status, labels, and dashboard aggregates read from SQLite through the backend. Email bodies render as escaped plain text. Credentials belong only in the backend environment.

## Requirements

- Node.js 20.19+ or 22.12+ and npm 10+.
- Python 3.12+ and the backend environment created with `uv sync`.

## Run with local data

From the repository root, start the backend:

```bash
uv sync
uv run uvicorn app.main:app --host 127.0.0.1 --port 8001 --no-access-log
```

In another terminal, from `frontend/`:

```bash
npm install
npm run dev -- --host 127.0.0.1 --port 5173 --strictPort
```

Open `http://127.0.0.1:5173`. The default backend starts with an empty database and sync disabled until IMAP is configured. Follow the root README to configure real mail locally. Startup and inbox review do not contact IMAP; only an explicit sync does. Recent/Unread sync retrieves up to 50 matching messages. Running, partial, failed, and unavailable outcomes retain locally stored messages.

To test API persistence with synthetic mail, replace the backend command with:

```bash
MEIRUZONE_DEMO=true MEIRUZONE_DATABASE_PATH=data/demo.sqlite3 uv run uvicorn app.main:app --host 127.0.0.1 --port 8001 --no-access-log
```

The UI identifies backend demo mode; its sync is a no-op. Human corrections persist in that separate SQLite database.

`VITE_API_BASE_URL` can select another loopback API, for example `http://127.0.0.1:8765/api/v1`. Remote hosts, embedded credentials, query strings, and URL fragments are rejected. The default is `http://127.0.0.1:8001/api/v1`. These Vite settings are public build configuration; never put credentials in them. Restart Vite or rebuild after changing them.

The backend allowlist must include the browser's exact origin. The default allows localhost/127.0.0.1 on port 5173. For `npm run preview`, explicitly add its loopback origin on port 4173 to `MEIRUZONE_FRONTEND_ORIGINS` and restart the backend.

## Offline fixture mode

From `frontend/`:

```bash
VITE_DATA_SOURCE=fixtures npm run dev
```

Fixture mode uses only synthetic messages. Its labels remain in browser local storage, separate from SQLite, and are never automatically imported into the API. An API connection failure shows a retry state; it never switches to fixtures.

## Labels, counts, and export

Category and priority are independent. Unconfirmed fields start as Not labeled; choosing priority alone does not confirm a suggested category. Save submits only newly confirmed or changed values. The backend assigns the timestamp and retains original predictions. Unsaved drafts survive failed saves, selection changes, and data refreshes in the current page session; a browser reload discards unsaved edits. Existing labels cannot be cleared in this API version.

The treemap and inbox counters cover all stored messages regardless of filters/pages. Save, sync completion, and Refresh inbox reload current records and aggregates. Needs Review uses each prediction's saved cutoff unless backend configuration explicitly overrides it; null cutoffs review every unconfirmed category prediction. CSV export reads every human-labeled page, preserves separate predicted/confirmed columns, escapes spreadsheet formulas, and downloads no incomplete file after a fetch failure. Export is disabled while a known sync runs.

The CSV is a review export without message bodies. Local category training reads the full human-category dataset using `Repository.category_training_examples()`; see the root README. Training is an explicit local command; Model lab displays approved model status, supported categories, effective cutoff, saved per-class/macro metrics, and a confusion matrix in saved class order. See the root README for training, approval, configuration, and restart. Missing/invalid models and per-message inference failures keep message review and labeling available; priority rules still run. Fixture mode shows demo status and no evaluated metrics.

## Checks

From `frontend/`:

```bash
npm test
npm run test:integration
npm run lint
npm run typecheck
npm run build
npm run preview
```

Use `npm ci` for clean checkouts and CI. The [delivery guide](../docs/delivery.md) documents the two-service Compose package and its Chromium browser check (`npx playwright install --with-deps chromium`, then `npm run test:containers`). Container checks use temporary synthetic storage and rebuild the production images.

`npm test` runs synthetic adapter/component/treemap tests. The separate integration command requires the repository's `.venv` and permission to bind a loopback port. It starts and cleans up its own HTTP backend and temporary database, mocks IMAP, and trains a small synthetic model and verifies ingestion-to-inference, safe rendering, correction, aggregate refresh, active-model and label persistence across frontend reload/backend restart, CSV export, and origin restrictions. It never contacts a personal mailbox. These commands use the project's Bash/local Linux workflow.

`npm run build` checks TypeScript and creates `dist/`. Production data-source/API URL settings are selected at build time.

Task 8 adds a second HTTP acceptance case that labels synced synthetic messages through the API, trains from SQLite, explicitly selects/restarts model versions, and verifies UI category/priority correction and later retraining. The container browser check also covers keyboard controls, visible focus, 390 px list/detail layouts, safe plain-text content, loading/error recovery, and requests limited to its loopback frontend/API origins. It writes synthetic screenshots under ignored `test-results/`; reviewed captures and remaining live-account/Open Design gates are recorded in the [acceptance report](../docs/acceptance.md). Passing these automated checks alone does not complete live MVP acceptance.
