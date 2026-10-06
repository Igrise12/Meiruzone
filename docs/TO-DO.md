# Project To-Do: Local-First Smart Email Classification

## References and working order

- [Client brief](client-brief.md): product goals, categories, MVP scope, privacy expectations, and success criteria.
- [Architecture](architecture.md): component responsibilities, local storage, ML pipeline, data flows, and deployment constraints.

This checklist changes the delivery order to **frontend first**, using the frontend handed over from **Open Design** as the design and implementation base. Build and review the frontend with synthetic data before connecting the backend. The product scope and local-first requirements in the referenced documents still apply.

Tasks 1–7 are complete. Task 2 brought forward the initial SQLite storage foundation; task 3 adds safe IMAP ingestion and real sync bookkeeping, task 5 adds explicit category training/evaluation with private versioned artifacts, task 6 connects approved inference, bilingual priority rules, persisted cutoffs/errors, and deliberate feedback, and task 7 adds locked CI, local Compose packaging, and release documentation. Full MVP acceptance remains task 8. Mark a task complete only when its deliverable and relevant checks are complete.

## 1. Frontend first: receive and integrate the Open Design handover

### Handover and setup

- [x] Receive the Open Design frontend source/export, assets, font information, design tokens, screen references, interaction notes, and local run instructions.
- [x] Review the handover against the [client brief's product experience](client-brief.md#product-experience); record missing screens or behaviors before implementation.
- [x] Include the required dashboard category treemap in the Open Design handover review; extend the handed-over design if the chart or its states are missing.
- [x] Confirm asset and font usage rights and inspect dependencies and install scripts before integrating the export.
- [x] Integrate the handed-over frontend under `frontend/`, adapting it to React where necessary and preserving the supplied visual foundation.
- [x] Document the frontend runtime version, package manager, installation, development, test, and production build commands.
- [x] Create synthetic email fixtures covering all eight categories, all three priorities, low confidence, unlabeled messages, and absent predictions.

### Smart Inbox behavior

- [x] Implement the email list and details using the handover as the base.
- [x] Add category and priority filters and a clearly defined Needs Review view for low-confidence predictions.
- [x] Show category, confidence, priority, sender, subject, date, read state, and attachment presence where appropriate.
- [x] Provide manual category and priority labeling and correction controls; distinguish human labels from model predictions.
- [x] Build the required dashboard category treemap with synthetic counts; size rectangles by email count and use consistent category colors with category/count/percentage details.
- [x] Make category selection navigate to or filter the Smart Inbox, with keyboard access and an equivalent category/count list for small tiles and accessible reading.
- [x] Display counts for all locally stored messages, independently of inbox filters or pagination; include an Unclassified bucket distinct from Other and handle zero-count categories and an empty dataset clearly.
- [x] Provide responsive treemap layouts and loading/error states using the Open Design visual foundation.
- [x] Provide sync status and a sync action, with mocked responses until the backend is ready.
- [x] Cover loading, empty inbox, no filter matches, connection/sync failure, save failure, and missing-model states.
- [x] Support responsive layouts, keyboard navigation, visible focus, accessible form labels, and readable status/error messages.
- [x] Keep UI data access behind a small API adapter so fixtures can be replaced with FastAPI responses.

### Frontend testing and security

- [x] Configure linting, type checks where applicable, component tests, and a production build check.
- [x] Test filtering, detail selection, confidence display, label/correction submission, save failures, and empty/error states using synthetic fixtures.
- [x] Test keyboard access to the main workflow and check the agreed layouts against the Open Design references.
- [x] Test treemap counts and percentages, category selection, keyboard navigation, skewed category sizes, and loading/empty/error states using synthetic fixtures.
- [x] Render message content as escaped plain text; verify malicious HTML/script fixtures do not execute or load remote tracking content.
- [x] Keep IMAP credentials and tokens out of frontend code, build-time variables, browser storage, and client logs.
- [x] Review handed-over dependencies and remote assets; remove unnecessary tracking or services that send email data outside the machine.
- [x] Render the treemap locally using aggregate data only; keep message content and personal metadata out of chart payloads, tooltips, and external analytics.

**Milestone complete when:** the handed-over design runs locally as a usable React Smart Inbox with a dashboard treemap and synthetic data, category navigation works, and frontend checks pass.

## 2. Agree the API contract and establish backend foundations

- [x] Define frontend/backend request and response shapes for email listing/details, category and priority filters, pagination, labels/corrections, sync status, and category statistics.
- [x] Define the treemap aggregate response with category counts and total messages, covering the full local dataset; use human category labels before predictions and place messages with neither in Unclassified.
- [x] Specify stable email IDs, date formatting, category/priority values, confidence representation, missing predictions, and validation errors in the contract.
- [x] Scaffold FastAPI according to the [architecture's code organization](architecture.md#suggested-code-organization), keeping routes, services, persistence, IMAP, and ML responsibilities clear.
- [x] Add local configuration with documented safe defaults and a secret-free `.env.example`.
- [x] Add `.gitignore` coverage for secrets, private emails/datasets, SQLite files and sidecars, local model artifacts, and generated files.
- [x] Define how local credentials are supplied without writing plaintext passwords into the application database or source code.
- [x] Bind the backend to loopback by default, allow only intended frontend origins, and choose protection against unauthorized state-changing requests from other origins.
- [x] Add input validation and limits for pagination, labels, message identifiers, and sync requests; return sanitized errors.
- [x] Add backend API tests using temporary local storage and synthetic data, including invalid inputs and access/origin restrictions.

**Milestone complete when:** the frontend contract is documented, the backend starts locally, and validated API operations can be exercised without a real mailbox.

**Implementation and verification:** the [API contract](api-contract.md) documents versioned endpoints and the future frontend mapping. FastAPI uses standard-library SQLite with a version 1 schema, separate predictions and human labels, opt-in synthetic seeding, and explicit demo sync. All 20 backend tests, 12 frontend tests, frontend lint/type/build checks, `uv lock --check`, and a real loopback Uvicorn smoke check passed. The frontend fixture adapter remains active; IMAP and ML are deferred.

## 3. Implement local storage and safe IMAP ingestion

- [x] Create SQLite storage for emails, classifications, human labels/feedback, and sync state; choose the simplest suitable persistence and migration approach. Task 2 introduced `sqlite3`, current human labels, and `PRAGMA user_version`; task 3 adds a transactional version 2 migration for scoped IMAP identity and real sync progress.
- [x] Preserve model predictions separately from human corrections so inference cannot overwrite training labels.
- [x] Define deduplication using stable IMAP identifiers, including account/mailbox scope and handling UID validity changes.
- [x] Implement IMAP connectivity over verified TLS, with timeouts, bounded fetches, and useful sanitized connection errors.
- [x] Fetch recent or unread mail without changing its read state or other mailbox flags; use read-only access and non-marking fetches.
- [x] Parse sender, subject, clean plain-text body, received date, read state, message identifiers, and attachment presence.
- [x] Convert HTML-only messages to text without executing HTML or fetching external resources; handle encodings, missing fields, and malformed MIME.
- [x] Store only required fields; omit attachment downloads and full raw-message retention from the initial workflow.
- [x] Implement repeatable upserts, sync progress/outcome, and safe retry after partial failures.
- [x] Define local data retention/deletion and backup guidance, including protection of database files and backups.
- [x] Test parsing with plain text, HTML, multipart content, malformed headers, missing fields, large messages, and attachments.
- [x] Test deduplication, repeated sync, interrupted retrieval, database transactions, and retained human labels.
- [x] Verify with mocked IMAP commands that sync never marks read, moves, deletes, or sends mail; keep automated tests independent of personal accounts.
- [x] Audit error and debug logs to confirm they omit credentials, tokens, full email bodies, and unnecessary personal metadata.

**Milestone complete when:** a bounded IMAP sync stores useful local messages, repeat sync does not duplicate them, and mailbox state remains unchanged.

**Implementation and verification:** IMAPClient performs verified-TLS, read-only sync for one configured account/folder using password/app-password login. Retrieval selects the highest matching UIDs and fetches bounded headers/text parts without attachment payloads. Separate identity mappings, per-message transactions, persisted progress, partial retry, overlap rejection, and interrupted-run recovery preserve predictions and human labels. UIDVALIDITY changes stop sync and preserve the existing database; recovery uses a separate file. All 50 backend tests, `uv lock --check`, `git diff --check`, a real loopback Uvicorn smoke, and the documented backup/restore procedure passed with isolated synthetic data. Parsing, command safety, TLS/timeouts, deduplication, migration rollback, progress races, and sanitized DEBUG logs are covered. No personal mailbox was contacted. Frontend API integration and ML remain tasks 4–6.

## 4. Connect the frontend and build the labeled dataset

- [x] Replace synthetic data calls with the agreed API adapter and retain fixtures for development and automated tests.
- [x] Connect email lists/details, filters, pagination, sync status, and dashboard treemap aggregates to SQLite-backed endpoints.
- [x] Compute treemap counts from existing records without adding an analytics service; count each message once and refresh after sync, labels/corrections, and new predictions.
- [x] Persist manual category and priority labels and prediction corrections through validated API operations.
- [x] Show successful saves and recoverable failures accurately; preserve user changes while retrying a failed save.
- [x] Make labeled messages available to local training, with a clear distinction between human labels and unverified predictions.
- [x] Test frontend/backend integration for filtering, labeling, correcting, refresh/restart persistence, and API failures.
- [x] Test treemap totals and percentages against stored messages, including human-label precedence, Unclassified messages, unchanged totals across inbox pages/filters, and refreshed category counts after correction.
- [x] Recheck safe rendering using ingested message content and verify secret fields never appear in API responses.

**Milestone complete when:** a user can review locally ingested messages, inspect accurate dashboard category counts, and create reliable training labels from the Smart Inbox.

**Implementation and verification:** the frontend now defaults to a loopback-only HTTP adapter with explicit offline fixture mode. Server filters, 50-message pagination, selected details, authoritative Needs Review, partial labels, retained drafts, persisted sync outcomes/progress, and complete SQLite dashboard counts are connected. `hasHumanLabel` supports global label counts and paged review CSV export; formulas are escaped and incomplete downloads are refused. `Repository.category_training_examples()` exposes human category ground truth without predictions or priority-only examples, using the existing schema. All 52 backend tests, 29 frontend tests, the real HTTP integration check, frontend lint/type/build checks, `uv lock --check`, and `git diff --check` passed. The integration check uses mocked IMAP and temporary synthetic storage, including ingested markup, aggregate refresh, frontend reload/backend restart persistence, and forbidden origins. Desktop (1440 px) and mobile (390 px) layouts, category-only saves, failure recovery, and absence of horizontal overflow were checked in the browser. No personal mailbox was contacted; ML remains tasks 5–6.

## 5. Train and evaluate the category baseline

- [x] Build one shared preprocessing path for sender, subject, and body, used by training and inference.
- [x] Train a scikit-learn pipeline containing TF-IDF and Logistic Regression on human-labeled examples.
- [x] Handle insufficient labels or missing classes with a clear explanation instead of an invalid training run.
- [x] Use a reproducible train/test split, with a validation subset or cross-validation within the training data for tuning; fit preprocessing only on training folds and check for duplicate-message leakage across splits.
- [x] Report per-class precision, recall, F1, macro F1, and a confusion matrix; document class counts and model limitations.
- [x] Select the Needs Review confidence threshold using validation data, retaining the held-out test set for final evaluation.
- [x] Save the fitted preprocessing and estimator together in a local, versioned Joblib artifact with label mapping and evaluation metadata.
- [x] Keep artifacts and private training data out of Git; load artifacts only from trusted local sources.
- [x] Test preprocessing, saved-model loading, prediction classes/confidence, empty or malformed fields, and insufficient-data behavior.

**Milestone complete when:** a repeatable local training command produces an evaluated model that can be loaded and used for valid predictions.

**Implementation and verification:** `uv run python -m app.train` reads confirmed category labels through a read-only version 2 SQLite connection, without storage initialization, migration, seeding, or IMAP access. Shared Unicode/case/whitespace preprocessing, exact duplicate collapse/conflict detection, and a ten-distinct-example floor train at least two supported categories and report excluded categories. Seeded stratified 60/20/20 splits keep TF-IDF fitting on training data; validation macro F1 selects C from 0.1/1/10, and validation selects a 90% accepted-accuracy cutoff with at least five accepted examples or review-all fallback. The unchanged selected model receives one held-out evaluation. Private, atomically published Joblib/JSON runs record class ordering, metrics, cutoff, versions, counts, and limitations; loading checks compatibility and requires trusted local provenance. All 62 backend/ML tests (including 10 focused ML tests), the real training-command smoke with temporary synthetic storage, fresh-process model loading/predictions, `uv lock --check`, and `git diff --check` passed. Tests confirm held-out vocabulary isolation, threshold boundaries/fallback, private permissions, read-only storage, sanitized output, and retained prior artifacts after failures. No personal mailbox or database was accessed. Backend activation, automatic inference, priority, and applying the artifact cutoff remain task 6.

## 6. Add inference, priority, and the feedback loop

- [x] Load the approved category model in the backend and classify newly ingested messages locally.
- [x] Assign High, Medium, or Low priority independently using documented simple rules or a separate baseline model.
- [x] Persist category, confidence, priority, prediction time, and model version; expose them through the API.
- [x] Apply the configured Needs Review threshold and display missing-model or inference-failure states without preventing inbox access.
- [x] Keep user corrections authoritative in the UI and eligible for subsequent training; do not overwrite them during sync or inference.
- [x] Provide an explicit local retraining command/workflow using accumulated labels; evaluate a replacement model before activating it.
- [x] Test ingestion-to-prediction, confidence boundaries, independent priority logic, missing/corrupt artifacts, and preserved corrections.
- [x] Verify inference makes no external AI requests and never logs raw message content.

**Milestone complete when:** new emails receive predictions, uncertain items can be reviewed, and corrections feed a later deliberate training run.

**Implementation and verification:** the backend loads one explicitly selected trusted run at startup; changing selection requires restart. Sync fills missing category and independent English/Indonesian priority outputs, records sanitized category failures without blocking ingestion, and preserves completed predictions and all human labels. Transactional schema version 3 adds saved cutoffs (legacy 70; null reviews all) and category errors. Explicit numeric overrides apply at read time; SQL review filters and response flags agree. Training stays read-only across versions 2/3 and never activates replacements. The local model endpoint exposes only validated aggregate metrics; Model lab displays active status and saved class ordering. All 70 backend/ML tests, 33 frontend tests, the real HTTP integration check, frontend lint/type/build checks, `uv lock --check`, and `git diff --check` passed. Checks cover saved-model inference, bilingual rules/negations, 0/100/equality/review-all/override cutoffs, corrupt/missing/incompatible artifacts, migration and inference-write rollback, correction-to-retraining and explicit replacement, retained original predictions, restart persistence, and sanitized logs/no external inference requests. TestClient checks ran outside the sandbox because its local thread portal stalled under sandbox restrictions. The synthetic preview was inspected at 1440 px and 390 px with no horizontal overflow; displayed confidence/cutoffs round to one decimal while review uses full precision. No personal mailbox, database, or model was accessed. Packaging/CI and full MVP acceptance remain tasks 7–8.

## 7. Add repeatable delivery and continuous integration

CI covers frontend, backend, ML, real HTTP integration, built-container browser checks, and secret scanning.

- [x] Run frontend linting, relevant type checks, tests, and production builds in GitHub Actions on pull requests and pushes to development branches.
- [x] Add backend linting, tests, and applicable type checks when the backend is introduced.
- [x] Add ML preprocessing, artifact-loading, and inference checks using synthetic fixtures and a small test model.
- [x] Add an integration/end-to-end check for inbox review, label correction, persistence, and prediction display using an isolated test database.
- [x] Package frontend and backend for local Docker/Compose use with persistent SQLite/model mounts and no baked-in secrets or private data.
- [x] Validate container builds in CI and restrict exposed ports to local access by default.
- [x] Check dependencies for known vulnerabilities and scan repository changes for accidentally committed secrets.
- [x] Document clean-clone setup, configuration, sync, labeling, training, evaluation, testing, backups, and local startup.
- [x] Define a local release containing the application and configuration; distribute only explicitly approved model artifacts containing no private user data.

**Milestone complete when:** a clean checkout passes automated checks and starts locally with documented commands and safe configuration.

**Implementation and verification:** SHA-pinned, read-only GitHub Actions jobs run locked Python/Node checks on pull requests, development/main pushes, and manual dispatch. Ruff and focused Pydantic/mypy checks cover configuration/API models; existing synthetic ML and real HTTP integration checks are reused. Digest-pinned multi-stage images serve built React through unprivileged Nginx and run one FastAPI worker, with loopback-only default ports, host UID/GID support, private SQLite/model mounts, and read-only serving models. The [delivery guide](delivery.md) documents clean setup, configuration, training/evaluation/activation, backups, checks, and a model-free versioned source release. Archive exclusion was checked with synthetic accidentally tracked private files. All 70 backend tests, 33 frontend tests, the real HTTP integration check, frontend lint/type/build checks, Ruff/mypy, lockfile checks, actionlint, and the built-container Chromium check passed, including clean-source installs. The browser check verifies empty startup, runtime permissions, saved prediction display/correction, container-recreation persistence, one-off synthetic training, retained model permissions/loading/inference, and isolated free loopback ports. Python/npm audits and redacted Git-history scans passed; vulnerable development-only Pygments/Tornado pins were updated through uv. Docker checks used elevated execution after sandbox daemon denial; workflow validation succeeded with a narrowly scoped file mount. No personal mailbox, database, or model was accessed. Hosted Actions will run after these files are pushed; no release tag, publication, or deployment was performed. Full MVP acceptance remains task 8.

## 8. Complete MVP acceptance and security review

- [ ] Walk through the [client brief's definition of success](client-brief.md#definition-of-success) using an explicitly configured test account or approved local mailbox.
- [x] Verify the full path: sync → local storage → labeling → training/evaluation → prediction → Smart Inbox → correction → later retraining.
- [x] Verify the dashboard treemap matches local category totals, refreshes when categories change, and opens the expected messages from a selected category.
- [x] Confirm operation without cloud infrastructure and without external AI calls; allow only expected network access such as IMAP and the local API during normal use.
- [x] Confirm read-only mailbox behavior, protected secrets, sanitized logs, safe message rendering, and restricted local API access.
- [x] Confirm automated fixtures, screenshots, CI outputs, container images, and release files contain no private emails or credentials.
- [x] Verify database/model persistence across restart and understandable recovery from connection failures, missing models, and invalid inputs.
- [ ] Review accessibility and frontend fidelity against the Open Design handover with the final integrated states.
- [ ] Resolve failing checks and document remaining model limitations before declaring the MVP complete.
- [x] Update the [architecture](architecture.md) and [client brief](client-brief.md) to reflect agreed implementation decisions and the frontend-first delivery order.

**Acceptance status (5 October 2026):** automated synthetic acceptance and security checks pass; the MVP remains **not accepted**. The [acceptance report](acceptance.md) maps evidence and limits to every checkbox, records clean-source verification and reviewed synthetic screenshots, and documents the remaining procedure. Two real HTTP cases cover API-confirmed labels → SQLite training/evaluation → explicit model activation/restart → inference → UI category/priority correction → later retraining, retaining older artifacts and predictions. All 70 backend tests, 33 frontend tests, frontend lint/type/build, Ruff/mypy/lockfile checks, dependency audits, redacted secret scans, and the built-container Chromium workflow pass. The source-archive privacy test was fixed to run without checkout Git metadata. Dedicated live-account acceptance and fidelity against the original Open Design references remain open because neither prerequisite was available. Hosted Actions were not run for these changes; no real mailbox, private model, release tag, publication or deployment was used.

## Deferred work

Revisit these only after MVP acceptance and a demonstrated need:

- [ ] Optional periodic sync with APScheduler and a single scheduler owner.
- [ ] Additional dashboard visualizations beyond the required category treemap, if a demonstrated need remains.
- [ ] Alternative classifiers and embeddings, measured against the baseline.
- [ ] Local LLM summaries, action items, or low-confidence fallback with explicit privacy controls.
- [ ] PostgreSQL, separate workers, optional cloud integrations, or release automation.

Sending mail, automatic replies, mailbox modification, continuous retraining, and a full agent system remain outside the current MVP scope.
