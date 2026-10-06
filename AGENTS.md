<!-- CODEGRAPH_START -->
## CodeGraph

When `.codegraph/` exists at the repository root, use CodeGraph before grep/find or reading files to locate or understand code. Prefer the `codegraph_explore` MCP tool when available; otherwise run `codegraph explore "<question or symbols>"` from the repository root. Ask it for current source by file or symbol when needed. If `.codegraph/` is absent, skip CodeGraph.
<!-- CODEGRAPH_END -->

## Project structure

Meiruzone is a local-first email classifier. `app/` contains the FastAPI backend, SQLite storage, read-only IMAP sync, parsing, and model training/inference. `frontend/` contains the React and TypeScript Smart Inbox. `docker/` and `compose.yaml` package the app locally. `docs/` contains product, architecture, delivery, user, and acceptance guidance. Python tests live in `tests/`; frontend tests live in `frontend/tests/`.

## Development commands

- `uv sync --locked` installs the locked Python environment.
- `uv run --locked python -m unittest discover -s tests` runs backend tests.
- In `frontend/`, run `npm ci`, `npm test`, `npm run lint`, `npm run typecheck`, and `npm run build` as needed.
- `npm run test:integration` and `npm run test:containers` are opt-in checks; see `docs/delivery.md` for setup.

## Conventions and safety

Use four spaces and `snake_case` in Python; follow the existing TypeScript and React patterns in `frontend/src/`. Keep modules focused and dependencies justified. Update `uv.lock` or `frontend/package-lock.json` with their package managers when dependencies change.

Use synthetic email fixtures and isolated storage in tests. Keep `.env`, mailbox data, SQLite databases, and trained models private. Credentials belong in local environment configuration; `.env.example` must contain safe placeholders only. Do not commit personal email or model artifacts.

Commit focused changes with short scope prefixes such as `docs:`, `backend:`, and `frontend:`. Document local run and verification commands for new components. Pull requests should explain rationale and checks, include UI screenshots when relevant, and call out configuration or privacy effects.
