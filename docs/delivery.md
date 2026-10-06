# Local delivery and CI

Meiruzone runs directly from source or as two local Compose services. Both workflows keep email, SQLite, credentials, and category models on your machine. Startup never contacts IMAP; only an explicit sync does. The API contract and browser-origin restrictions are identical in both workflows.

## Clean-clone development setup

Use Python 3.12, uv 0.12.21, Node.js 24, and npm. From a clean checkout:

```bash
uv sync --locked
cd frontend
npm ci
cd ..
```

Optional private configuration:

```bash
umask 077
cp .env.example .env
chmod 600 .env
```

Set backend IMAP settings in this ignored file when ready to retrieve real mail. Without IMAP configuration the inbox starts empty and sync is unavailable; stored mail remains accessible. Never put credentials into Vite variables or frontend browser storage.

Start the backend and frontend in separate terminals:

```bash
uv run --locked --env-file .env uvicorn app.main:app --host 127.0.0.1 --port 8001 --no-access-log
```

```bash
cd frontend
npm run dev -- --host 127.0.0.1 --port 5173 --strictPort
```

Omit `--env-file .env` if no private file exists. Open <http://127.0.0.1:5173>. For an isolated synthetic demonstration, set `MEIRUZONE_DEMO=true` and use a separate database file. The [root guide](../README.md#sync-real-mail) covers configuration and bounded, read-only Recent/Unread sync; [labeling](../README.md#build-the-labeled-dataset), [training/evaluation](../README.md#train-and-evaluate-the-category-model), and [activation](../README.md#activate-and-serve-category-predictions) document the complete workflow.

## Docker Compose startup

Requirements: Docker Engine and Docker Compose 2.24+ on Linux, with permission to use the Docker daemon. Containers use a fixed Python 3.12.13 runtime and locked dependencies. Images and build tools are pinned to immutable digests. Dependency/image downloads require network access during setup and builds; mailbox access is needed only for explicit real IMAP sync. No external AI service is used.

Prepare private mount directories and match the backend container to your host user. Run as your ordinary user, not root:

```bash
umask 077
mkdir -p data models
chmod 700 data models
export MEIRUZONE_UID="$(id -u)"
export MEIRUZONE_GID="$(id -g)"
docker compose up --build --detach --wait
```

Save those numeric UID/GID values in `.env` for later shells, especially if they differ from the template's 1000. The optional `.env` is supplied only to the backend at runtime. It is excluded from both image build contexts. Default relative database/model paths work from `/app` inside the backend. Use `data/<filename>.sqlite3` and `models/<run>` for mounted files; host absolute paths must be translated to these container paths.

Open <http://127.0.0.1:5173>; the API is <http://127.0.0.1:8001/api/v1>. Both published ports bind to loopback. Uvicorn listens on all interfaces *inside* its container so Docker can forward traffic, with one worker per SQLite database. The frontend serves built assets through unprivileged Nginx and uses the existing loopback API adapter. Access logging is disabled.

`MEIRUZONE_DATA_DIRECTORY` and `MEIRUZONE_MODELS_DIRECTORY` select existing host directories; defaults are `./data` and `./models`. They must be owned by the selected UID/GID. Compose refuses to create missing directories, preventing accidental root-owned storage. The backend can write SQLite, while the normal model mount is read-only. Both services run without root privileges, drop Linux capabilities, and prevent privilege escalation. Runtime files retain the existing 0700 directory / 0600 file policy.

If a host port is occupied, set `MEIRUZONE_API_PORT` and/or `MEIRUZONE_FRONTEND_PORT` to free ports in `.env`. Update `MEIRUZONE_FRONTEND_ORIGINS` to allow the exact new loopback browser origins, and run `docker compose up --build --detach --wait`. Compose selects the matching public loopback API URL at frontend build time. Port changes never broaden access beyond loopback.

`MEIRUZONE_ENV_FILE` selects another backend configuration file. When changing this setting, pass the same file with `docker compose --env-file <file>` if it also contains Compose interpolation settings. A missing default `.env` is allowed. Avoid printing `docker compose config` with private configuration: use `docker compose config --quiet` to validate without exposing resolved credentials.

Startup creates/migrates SQLite but does not train, select, or download a model. Missing or incompatible models leave review and priority rules available. Stop services with `docker compose down`; host-mounted data/models remain intact. Recreate the backend after configuration or model selection changes:

```bash
docker compose up --detach --force-recreate --wait
```

### Training, evaluation, and activation in the container

Label stored messages in the inbox first. Training still requires at least two categories with ten distinct usable human labels each. The synthetic demo alone is insufficient. Run training with writable model access only for this one-off command:

```bash
docker compose run --rm --no-deps \
  --volume "${MEIRUZONE_MODELS_DIRECTORY:-$PWD/models}:/app/models:rw" \
  backend python -m app.train
```

The command reuses the backend image and reads the mounted database without changing it or contacting IMAP. It prints aggregate evaluation and saves a private version under the mounted models directory. Inspect the report, then explicitly approve the run by setting `MEIRUZONE_MODEL_DIRECTORY=models/category-<run>` in backend configuration. Recreate the services and inspect Model lab before syncing.

For a custom host model directory, export `MEIRUZONE_MODELS_DIRECTORY` with the same absolute path configured in `.env` before the command: the shell expands the volume argument, while Compose reads `.env` independently. Use a new version directory for each run; existing models remain preserved.

Artifacts record exact Python/scikit-learn/NumPy/SciPy/Joblib versions. Train and serve in the same container image; after an incompatible runtime/dependency update, retrain rather than weakening loader checks. Direct-source models may be incompatible with the container. Joblib can execute code: load only trusted locally produced artifacts. Original predictions and human corrections remain authoritative under the existing inference policy.

### Backup and restore

Before backing up, stop the backend (`docker compose stop backend`). Follow the [SQLite backup/restore procedure](../README.md#local-data-retention-backup-and-deletion), using the configured host data mount. Python's standard-library SQLite backup operation works without installing application dependencies; substitute `python3` for `uv run python` when using only Docker.

Keep backups private, preserve existing files, and verify `PRAGMA integrity_check`. Restore to a new filename inside the host data directory, set `MEIRUZONE_DATABASE_PATH=data/<new-filename>.sqlite3`, enforce 0600 permissions and matching ownership, then recreate services and verify labels. Back up model runs separately with their private permissions. `docker compose down` does not remove these host directories. Explicit deletion and retention remain described in the root guide.

## Local verification and GitHub Actions

Backend checks from the root:

```bash
uv sync --locked
uv run --locked ruff check .
uv run --locked mypy
uv run --locked python -m unittest discover -s tests
uv lock --check
uv run --locked pip-audit --strict --progress-spinner off
```

Ruff checks syntax, undefined/unused names, and basic Python errors. Mypy checks configuration and public API models with the Pydantic plugin; SQLite/ML internals remain covered by focused runtime tests. The dev group adds only the tools required for these checks; the backend image excludes all dev dependencies.

Frontend and real HTTP integration checks:

```bash
cd frontend
npm ci
npm run lint
npm run typecheck
npm test
npm run build
npm run test:integration
npm audit
```

The HTTP integration test starts a temporary loopback API, mocks IMAP, trains a small synthetic model, and checks prediction display, correction, aggregate refresh, and persistence after restart. It needs the root `.venv` created by `uv sync --locked`.

For the built-container browser check, run from `frontend/`:

```bash
npx playwright install --with-deps chromium
npm run test:containers
```

The test builds both images, uses free loopback ports, a unique Compose project and temporary database/model/configuration directories, and never reads your private `.env` or data mounts. It verifies empty startup, loopback port publication, non-root execution, SQLite permissions, a read-only model mount, excluded dev/private files, synthetic prediction display, correction, and persistence after container recreation. It also trains through the writable one-off mount, reloads the retained synthetic artifact, and checks private permissions and inference. Containers and temporary test storage are cleaned up. Linux host UID/GID support is required. Browser installation may require OS package-manager privileges for missing system libraries.

To scan Git history and current files locally without displaying secret values:

```bash
docker run --rm --user "$(id -u):$(id -g)" --volume "$PWD:/repo:ro" \
  zricethezav/gitleaks:v8.30.1@sha256:c00b6bd0aeb3071cbcb79009cb16a60dd9e0a7c60e2be9ab65d25e6bc8abbb7f \
  git /repo --redact --no-banner
docker run --rm --user "$(id -u):$(id -g)" --volume "$PWD:/repo:ro" \
  zricethezav/gitleaks:v8.30.1@sha256:c00b6bd0aeb3071cbcb79009cb16a60dd9e0a7c60e2be9ab65d25e6bc8abbb7f \
  dir /repo --redact --no-banner
```

Run the directory scan only in a clean checkout: ignored personal `.env` files are intentionally private and can trigger findings. Never upload them or a scanner report containing secret values.

GitHub Actions runs backend/ML, frontend, HTTP integration, built-container browser checks, and a redacted history secret scan on pull requests, pushes to `development`/`main`, and manual dispatch. Actions have read-only repository permissions, no persisted checkout credentials, and immutable SHA pins. Dependency audits fail on known advisories; scanner failures are not silently ignored. Update vulnerable dependency pins through uv/npm, rerun relevant checks, and document any narrowly justified exception rather than broadly suppressing a scanner. CI uses no personal mailbox, model, database, or account secrets. Hosted results become available after the workflow is pushed.

## Versioned local source release

The initial source-release version is `0.1.0`. After required checks pass and the intended files are committed, review that commit and create the local tag and archive:

```bash
git tag v0.1.0
mkdir -p dist
git archive --format=tar.gz --prefix=meiruzone-0.1.0/ \
  --output=dist/meiruzone-0.1.0.tar.gz v0.1.0
sha256sum dist/meiruzone-0.1.0.tar.gz > dist/meiruzone-0.1.0.tar.gz.sha256
```

Use a new version/tag for later releases; never overwrite an existing release tag. The source archive includes application code, frontend sources, lockfiles, Docker/Compose configuration, safe `.env.example`, tests, and setup documentation. It requires the documented dependency/image downloads for installation. Nothing is automatically pushed, published to a registry, or deployed.

Git archives include committed files only; `.gitattributes` excludes private environment files, data, mail, backups, datasets, and model artifacts even if accidentally tracked. Review archive contents and run setup/checks from an extracted clean copy before distributing. Default releases contain no category model. If a separate model is explicitly approved for distribution, inspect its provenance and vocabulary for private terms and record its version/checksum/runtime requirements; approval of application code does not approve private model data.
