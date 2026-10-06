# MVP acceptance and security review

Reviewed on **5 October 2026 (Asia/Jakarta)** against the implemented tasks 1–7 and task 8 in [the delivery checklist](TO-DO.md#8-complete-mvp-acceptance-and-security-review). All evidence below uses synthetic messages and isolated storage. **The MVP is not yet accepted:** the dedicated live IMAP account and original Open Design references remain unavailable.

## Checklist evidence

| Task 8 requirement | Result | Evidence and limits |
| --- | --- | --- |
| Dedicated test account walkthrough | Pending | No local `.env` or complete IMAP environment configuration was available. No real mailbox was accessed. |
| Sync → storage → labeling → training/evaluation → prediction → inbox → correction → retraining | Passed with synthetic IMAP | Two real HTTP integration cases pass. The new case starts without a model, imports 40 messages, confirms all training categories through HTTP, trains from SQLite, explicitly selects a model after restart, corrects category and priority in the UI, retrains from 41 human category labels, and explicitly activates the replacement. |
| Accurate, refreshed treemap and category navigation | Passed | HTTP aggregates match independently queried SQLite effective-category totals before/after corrections and replacement. Unclassified counts, filter/pagination independence, refresh, and category navigation are covered by API/component/treemap tests and Chromium. |
| Local operation and expected network access | Passed for reviewed paths | The built browser requests only its exact loopback frontend/API origins; a synthetic tracking URL stays plain text and receives no request. The HTTP fixture rejects outbound `socket.create_connection` calls; training tests reject network access. Runtime source review finds IMAP as the external application transport and no external AI/cloud client. Live provider traffic remains unverified. |
| Read-only mailbox, secret/log protection, safe rendering, API restrictions | Passed in automated review | IMAP checks verify TLS, read-only selection and UID `BODY.PEEK` fetches. Tests cover sanitized credentials/errors/debug logs, escaped text, Host/Origin restrictions, required write headers, JSON/body limits and invalid inputs. Provider-side unchanged FLAGS still need the live walkthrough. |
| Private-data exclusion from fixtures, screenshots, CI, images and release files | Passed for local artifacts and configuration | Fixtures/configuration are synthetic; no account secret is provided to CI. Images exclude private/dev files. A temporary source archive excludes deliberately staged synthetic environment, database, message, model and CodeGraph files while retaining `.env.example`. Redacted history and clean-source directory scans find no leaks. No new hosted CI output or published release was produced. |
| Persistence and understandable recovery | Passed | Database labels and original predictions survive HTTP/backend restart and container recreation. Models retain private permissions and reload in a fresh process. Backend/component tests cover connection failures, interrupted sync, missing/corrupt/incompatible models and invalid inputs; Chromium verifies empty startup, a failed inbox request, successful retry and loading feedback. |
| Accessibility and fidelity to original handover | Partial | Chromium checks keyboard navigation, visible focus, category selection, native dialog Enter/Escape, labeled controls, mobile list/detail navigation and no horizontal page overflow at 390 px. Seven synthetic screenshots were visually inspected. Original-reference comparison remains pending; this is not a comprehensive accessibility certification. |
| Resolve failed checks, document limitations and declare acceptance | Partial | The source-archive test failure was fixed and checks pass. Model limits are recorded below. Final acceptance remains open until the live account and original-reference gates pass. |
| Update architecture and client brief | Passed | Both documents retain frontend-first delivery and now distinguish automated evidence from final live/fidelity acceptance. |

## Verification results

Commands are documented in [the delivery guide](delivery.md#local-verification-and-github-actions). Python 3.12.13, uv 0.12.21, Node.js 24.21.0, Docker Engine 29.8.2 and Compose 5.3.1 were used.

| Check | Result |
| --- | --- |
| `uv sync --locked` in extracted clean source | Passed; environment created from the lockfile |
| `uv run --locked python -m unittest discover -s tests` | 70 passed, including the extracted-source rerun |
| Ruff, focused mypy, `uv lock --check` | Passed |
| `npm ci`, lint, typecheck, `npm test`, production build in clean source | Passed; 33 frontend tests; the two opt-in HTTP cases are skipped by the default command |
| `npm run test:integration` in clean source | Two passed, including database-derived training and later replacement |
| `npm run test:containers` | One Chromium workflow passed against freshly built images |
| Python `pip-audit --strict` and `npm audit` | Passed; no known vulnerabilities reported at review time |
| Redacted Gitleaks history and clean-source directory scans | Passed |
| Temporary source-package private-file exclusion probes | Passed; extracted source also installs and passes checks |
| `git diff --check` | Passed |
| Hosted GitHub Actions | Not run for these changes; local results are not hosted CI evidence |

The filesystem/network sandbox initially prevented uv cache writes, local HTTP ports, dependency-advisory requests and TestClient execution. Checks were rerun with a writable temporary cache and permitted execution. The matching headless Chromium build was downloaded to a temporary directory; use the documented Playwright install step on a new machine. A transient automatic-approval service capacity error was retried successfully. These resolved execution constraints are not product failures.

Clean-package testing reproduced one test failure: `git check-ignore` assumed a checkout `.git` directory. The privacy test now copies the shipped `.gitignore` into an isolated temporary Git repository. Its focused regression and the full 70-test suite pass without Git metadata in the extracted application source. Browser-test selector/evaluation mistakes were corrected before the successful final run. Application behavior, dependencies and public API contracts are unchanged.

## Synthetic screenshots

These contain only `example.test` messages and an intentionally displayed, inert `tracker.invalid` string. Viewports were 1440×900 and 390×844; captures include the full page. The original Open Design references have not been substituted with these screenshots.

- [Desktop inbox](acceptance-screenshots/desktop-inbox.png)
- [Mobile inbox](acceptance-screenshots/mobile-inbox.png) and [mobile detail](acceptance-screenshots/mobile-detail.png)
- [Needs Review and keyboard focus](acceptance-screenshots/needs-review.png)
- [Empty inbox / unavailable model](acceptance-screenshots/empty-inbox.png)
- [Inbox failure](acceptance-screenshots/inbox-error.png) and [category loading](acceptance-screenshots/loading-inbox.png)

Screenshots are generated in ignored `frontend/test-results/` by the container check. Only the reviewed synthetic captures above were copied into documentation. Future captures from real mail must stay private.

## Model and security limits

- The HTTP acceptance model supports **Recruitment and Spam** using 20 distinct human-labeled examples each, then 41 labels after one correction. Other categories remain supported by the product taxonomy and broader fixtures, but cannot be predicted by this two-class artifact. These deliberately simple synthetic messages validate the workflow, not personal-mail accuracy.
- Ten distinct usable examples per category, in at least two categories, is a training floor. Small held-out samples and exact-duplicate-only grouping can inflate reported scores; similar templates/threads are not grouped.
- Confidence is an uncalibrated class probability. Validation is reused for parameter/cutoff selection; the observed 90% acceptance target is not a future accuracy guarantee. A null cutoff reviews all unconfirmed category predictions.
- Training is deliberate, reads human category labels rather than unverified predictions, and does not activate a model. Activation requires an explicitly selected trusted artifact and backend restart. Completed predictions and human corrections remain intact; newly synced or previously missing categories use the selected model. Priority rules operate independently and remain a phrase-based bilingual baseline.
- Joblib artifacts require trusted local provenance and can contain private vocabulary. Exact runtime compatibility checks and permissions do not make untrusted artifacts safe. Do not distribute personal models with the default source release.
- Loopback and browser-write restrictions address unsolicited web requests, not malicious programs running as the local user. Runtime network checks cover the exercised browser/fixture paths; no real provider connection or operating-system-wide network isolation was tested.

## Remaining acceptance procedure

1. Provide the dedicated account's configuration through an ignored private environment file, and make the original Open Design export/screenshots available locally. Do not paste credentials into chat or enable private captures in CI.
2. Use isolated ignored database/model directories and `MEIRUZONE_DEMO=false`. Preload at least ten distinct usable synthetic messages in each of two categories, plus additional messages for first-model and replacement-model inference. Account preparation is separate from Meiruzone's read-only operation.
3. Record UIDVALIDITY and UID/FLAGS through read-only provider access; run Recent and Unread sync, then repeat sync. Confirm stable identities, no duplicates and unchanged provider flags.
4. Label category and priority in Smart Inbox, train with the documented local command, and review supported classes, per-class precision/recall/F1, macro F1, confusion matrix and review cutoff. Keep artifacts/configuration private.
5. Explicitly select the run, restart and sync fresh/missing predictions. Check confidence, priority, Needs Review and displayed model evaluation. Compare dashboard counts with local data and navigate from a category.
6. Correct a prediction, retrain, verify the active model remains unchanged until explicit selection/restart, then ingest an additional message with the replacement. Verify older predictions, corrections and model versions survive restart.
7. Compare final desktop/mobile and loading/empty/error/review states with the original handover. Record reference identity and any discrepancies without adding private screenshots to the repository.
8. Record dated, sanitized outcomes here and complete the remaining task 8 boxes only after these gates pass. Run hosted CI before merging when that workflow is available. No publishing, deployment or release tag is authorized by this acceptance review.
