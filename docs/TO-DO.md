# Project To-Do: Local-First Smart Email Classification

## References and working order

- [Client brief](client-brief.md): product goals, categories, MVP scope, privacy expectations, and success criteria.
- [Architecture](architecture.md): component responsibilities, local storage, ML pipeline, data flows, and deployment constraints.

This checklist changes the delivery order to **frontend first**, using the frontend handed over from **Open Design** as the design and implementation base. Build and review the frontend with synthetic data before connecting the backend. The product scope and local-first requirements in the referenced documents still apply.

All items are pending. The Open Design handover is an input to the first milestone; its contents have not yet been reviewed. Mark a task complete only when its deliverable and relevant checks are complete.

## 1. Frontend first: receive and integrate the Open Design handover

### Handover and setup

- [ ] Receive the Open Design frontend source/export, assets, font information, design tokens, screen references, interaction notes, and local run instructions.
- [ ] Review the handover against the [client brief's product experience](client-brief.md#product-experience); record missing screens or behaviors before implementation.
- [ ] Include the required dashboard category treemap in the Open Design handover review; extend the handed-over design if the chart or its states are missing.
- [ ] Confirm asset and font usage rights and inspect dependencies and install scripts before integrating the export.
- [ ] Integrate the handed-over frontend under `frontend/`, adapting it to React where necessary and preserving the supplied visual foundation.
- [ ] Document the frontend runtime version, package manager, installation, development, test, and production build commands.
- [ ] Create synthetic email fixtures covering all eight categories, all three priorities, low confidence, unlabeled messages, and absent predictions.

### Smart Inbox behavior

- [ ] Implement the email list and details using the handover as the base.
- [ ] Add category and priority filters and a clearly defined Needs Review view for low-confidence predictions.
- [ ] Show category, confidence, priority, sender, subject, date, read state, and attachment presence where appropriate.
- [ ] Provide manual category and priority labeling and correction controls; distinguish human labels from model predictions.
- [ ] Build the required dashboard category treemap with synthetic counts; size rectangles by email count and use consistent category colors with category/count/percentage details.
- [ ] Make category selection navigate to or filter the Smart Inbox, with keyboard access and an equivalent category/count list for small tiles and accessible reading.
- [ ] Display counts for all locally stored messages, independently of inbox filters or pagination; include an Unclassified bucket distinct from Other and handle zero-count categories and an empty dataset clearly.
- [ ] Provide responsive treemap layouts and loading/error states using the Open Design visual foundation.
- [ ] Provide sync status and a sync action, with mocked responses until the backend is ready.
- [ ] Cover loading, empty inbox, no filter matches, connection/sync failure, save failure, and missing-model states.
- [ ] Support responsive layouts, keyboard navigation, visible focus, accessible form labels, and readable status/error messages.
- [ ] Keep UI data access behind a small API adapter so fixtures can be replaced with FastAPI responses.

### Frontend testing and security

- [ ] Configure linting, type checks where applicable, component tests, and a production build check.
- [ ] Test filtering, detail selection, confidence display, label/correction submission, save failures, and empty/error states using synthetic fixtures.
- [ ] Test keyboard access to the main workflow and check the agreed layouts against the Open Design references.
- [ ] Test treemap counts and percentages, category selection, keyboard navigation, skewed category sizes, and loading/empty/error states using synthetic fixtures.
- [ ] Render message content as escaped plain text; verify malicious HTML/script fixtures do not execute or load remote tracking content.
- [ ] Keep IMAP credentials and tokens out of frontend code, build-time variables, browser storage, and client logs.
- [ ] Review handed-over dependencies and remote assets; remove unnecessary tracking or services that send email data outside the machine.
- [ ] Render the treemap locally using aggregate data only; keep message content and personal metadata out of chart payloads, tooltips, and external analytics.

**Milestone complete when:** the handed-over design runs locally as a usable React Smart Inbox with a dashboard treemap and synthetic data, category navigation works, and frontend checks pass.

## 2. Agree the API contract and establish backend foundations

- [ ] Define frontend/backend request and response shapes for email listing/details, category and priority filters, pagination, labels/corrections, sync status, and category statistics.
- [ ] Define the treemap aggregate response with category counts and total messages, covering the full local dataset; use human category labels before predictions and place messages with neither in Unclassified.
- [ ] Specify stable email IDs, date formatting, category/priority values, confidence representation, missing predictions, and validation errors in the contract.
- [ ] Scaffold FastAPI according to the [architecture's code organization](architecture.md#suggested-code-organization), keeping routes, services, persistence, IMAP, and ML responsibilities clear.
- [ ] Add local configuration with documented safe defaults and a secret-free `.env.example`.
- [ ] Add `.gitignore` coverage for secrets, private emails/datasets, SQLite files and sidecars, local model artifacts, and generated files.
- [ ] Define how local credentials are supplied without writing plaintext passwords into the application database or source code.
- [ ] Bind the backend to loopback by default, allow only intended frontend origins, and choose protection against unauthorized state-changing requests from other origins.
- [ ] Add input validation and limits for pagination, labels, message identifiers, and sync requests; return sanitized errors.
- [ ] Add backend API tests using temporary local storage and synthetic data, including invalid inputs and access/origin restrictions.

**Milestone complete when:** the frontend contract is documented, the backend starts locally, and validated API operations can be exercised without a real mailbox.

## 3. Implement local storage and safe IMAP ingestion

- [ ] Create SQLite storage for emails, classifications, human labels/feedback, and sync state; choose the simplest suitable persistence and migration approach.
- [ ] Preserve model predictions separately from human corrections so inference cannot overwrite training labels.
- [ ] Define deduplication using stable IMAP identifiers, including account/mailbox scope and handling UID validity changes.
- [ ] Implement IMAP connectivity over verified TLS, with timeouts, bounded fetches, and useful sanitized connection errors.
- [ ] Fetch recent or unread mail without changing its read state or other mailbox flags; use read-only access and non-marking fetches.
- [ ] Parse sender, subject, clean plain-text body, received date, read state, message identifiers, and attachment presence.
- [ ] Convert HTML-only messages to text without executing HTML or fetching external resources; handle encodings, missing fields, and malformed MIME.
- [ ] Store only required fields; omit attachment downloads and full raw-message retention from the initial workflow.
- [ ] Implement repeatable upserts, sync progress/outcome, and safe retry after partial failures.
- [ ] Define local data retention/deletion and backup guidance, including protection of database files and backups.
- [ ] Test parsing with plain text, HTML, multipart content, malformed headers, missing fields, large messages, and attachments.
- [ ] Test deduplication, repeated sync, interrupted retrieval, database transactions, and retained human labels.
- [ ] Verify with mocked IMAP commands that sync never marks read, moves, deletes, or sends mail; keep automated tests independent of personal accounts.
- [ ] Audit error and debug logs to confirm they omit credentials, tokens, full email bodies, and unnecessary personal metadata.

**Milestone complete when:** a bounded IMAP sync stores useful local messages, repeat sync does not duplicate them, and mailbox state remains unchanged.

## 4. Connect the frontend and build the labeled dataset

- [ ] Replace synthetic data calls with the agreed API adapter and retain fixtures for development and automated tests.
- [ ] Connect email lists/details, filters, pagination, sync status, and dashboard treemap aggregates to SQLite-backed endpoints.
- [ ] Compute treemap counts from existing records without adding an analytics service; count each message once and refresh after sync, labels/corrections, and new predictions.
- [ ] Persist manual category and priority labels and prediction corrections through validated API operations.
- [ ] Show successful saves and recoverable failures accurately; preserve user changes while retrying a failed save.
- [ ] Make labeled messages available to local training, with a clear distinction between human labels and unverified predictions.
- [ ] Test frontend/backend integration for filtering, labeling, correcting, refresh/restart persistence, and API failures.
- [ ] Test treemap totals and percentages against stored messages, including human-label precedence, Unclassified messages, unchanged totals across inbox pages/filters, and refreshed category counts after correction.
- [ ] Recheck safe rendering using ingested message content and verify secret fields never appear in API responses.

**Milestone complete when:** a user can review locally ingested messages, inspect accurate dashboard category counts, and create reliable training labels from the Smart Inbox.

## 5. Train and evaluate the category baseline

- [ ] Build one shared preprocessing path for sender, subject, and body, used by training and inference.
- [ ] Train a scikit-learn pipeline containing TF-IDF and Logistic Regression on human-labeled examples.
- [ ] Handle insufficient labels or missing classes with a clear explanation instead of an invalid training run.
- [ ] Use a reproducible train/test split, with a validation subset or cross-validation within the training data for tuning; fit preprocessing only on training folds and check for duplicate-message leakage across splits.
- [ ] Report per-class precision, recall, F1, macro F1, and a confusion matrix; document class counts and model limitations.
- [ ] Select the Needs Review confidence threshold using validation data, retaining the held-out test set for final evaluation.
- [ ] Save the fitted preprocessing and estimator together in a local, versioned Joblib artifact with label mapping and evaluation metadata.
- [ ] Keep artifacts and private training data out of Git; load artifacts only from trusted local sources.
- [ ] Test preprocessing, saved-model loading, prediction classes/confidence, empty or malformed fields, and insufficient-data behavior.

**Milestone complete when:** a repeatable local training command produces an evaluated model that can be loaded and used for valid predictions.

## 6. Add inference, priority, and the feedback loop

- [ ] Load the approved category model in the backend and classify newly ingested messages locally.
- [ ] Assign High, Medium, or Low priority independently using documented simple rules or a separate baseline model.
- [ ] Persist category, confidence, priority, prediction time, and model version; expose them through the API.
- [ ] Apply the configured Needs Review threshold and display missing-model or inference-failure states without preventing inbox access.
- [ ] Keep user corrections authoritative in the UI and eligible for subsequent training; do not overwrite them during sync or inference.
- [ ] Provide an explicit local retraining command/workflow using accumulated labels; evaluate a replacement model before activating it.
- [ ] Test ingestion-to-prediction, confidence boundaries, independent priority logic, missing/corrupt artifacts, and preserved corrections.
- [ ] Verify inference makes no external AI requests and never logs raw message content.

**Milestone complete when:** new emails receive predictions, uncertain items can be reviewed, and corrections feed a later deliberate training run.

## 7. Add repeatable delivery and continuous integration

Start frontend CI during milestone 1, then extend it as backend and ML capabilities become available.

- [ ] Run frontend linting, relevant type checks, tests, and production builds in GitHub Actions on pull requests and pushes to development branches.
- [ ] Add backend linting, tests, and applicable type checks when the backend is introduced.
- [ ] Add ML preprocessing, artifact-loading, and inference checks using synthetic fixtures and a small test model.
- [ ] Add an integration/end-to-end check for inbox review, label correction, persistence, and prediction display using an isolated test database.
- [ ] Package frontend and backend for local Docker/Compose use with persistent SQLite/model mounts and no baked-in secrets or private data.
- [ ] Validate container builds in CI and restrict exposed ports to local access by default.
- [ ] Check dependencies for known vulnerabilities and scan repository changes for accidentally committed secrets.
- [ ] Document clean-clone setup, configuration, sync, labeling, training, evaluation, testing, backups, and local startup.
- [ ] Define a local release containing the application and configuration; distribute only explicitly approved model artifacts containing no private user data.

**Milestone complete when:** a clean checkout passes automated checks and starts locally with documented commands and safe configuration.

## 8. Complete MVP acceptance and security review

- [ ] Walk through the [client brief's definition of success](client-brief.md#definition-of-success) using an explicitly configured test account or approved local mailbox.
- [ ] Verify the full path: sync → local storage → labeling → training/evaluation → prediction → Smart Inbox → correction → later retraining.
- [ ] Verify the dashboard treemap matches local category totals, refreshes when categories change, and opens the expected messages from a selected category.
- [ ] Confirm operation without cloud infrastructure and without external AI calls; allow only expected network access such as IMAP and the local API during normal use.
- [ ] Confirm read-only mailbox behavior, protected secrets, sanitized logs, safe message rendering, and restricted local API access.
- [ ] Confirm automated fixtures, screenshots, CI outputs, container images, and release files contain no private emails or credentials.
- [ ] Verify database/model persistence across restart and understandable recovery from connection failures, missing models, and invalid inputs.
- [ ] Review accessibility and frontend fidelity against the Open Design handover with the final integrated states.
- [ ] Resolve failing checks and document remaining model limitations before declaring the MVP complete.
- [ ] Update the [architecture](architecture.md) and [client brief](client-brief.md) to reflect agreed implementation decisions and the frontend-first delivery order.

## Deferred work

Revisit these only after MVP acceptance and a demonstrated need:

- [ ] Optional periodic sync with APScheduler and a single scheduler owner.
- [ ] Additional dashboard visualizations beyond the required category treemap, if a demonstrated need remains.
- [ ] Alternative classifiers and embeddings, measured against the baseline.
- [ ] Local LLM summaries, action items, or low-confidence fallback with explicit privacy controls.
- [ ] PostgreSQL, separate workers, optional cloud integrations, or release automation.

Sending mail, automatic replies, mailbox modification, continuous retraining, and a full agent system remain outside the current MVP scope.
