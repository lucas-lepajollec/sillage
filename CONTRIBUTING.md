# Contributing

Keep changes focused on the folder → scan → select → translate → sidecar workflow. Read [AGENTS.md](AGENTS.md), [architecture](docs/research.md) and [limits](docs/limits.md) first. Media-server integrations, OCR, speech transcription, remuxing and multi-user management are outside the current scope.

## Setup

Install Python 3.12+, uv, Node 22+, FFmpeg/ffprobe and Docker. From a fresh clone:

```bash
uv sync --frozen --extra dev --extra sync --python 3.12
npm --prefix frontend ci
npm --prefix frontend run build
```

On Linux/macOS, `MEDIA_ROOTS=/absolute/media ./scripts/dev.sh` serves the application on loopback port 2499. For frontend hot reload, run `uv run uvicorn sillage.app:create_app --factory --host 127.0.0.1 --port 2500 --no-access-log` and `npm --prefix frontend run dev` in separate terminals, then open `http://127.0.0.1:2499` (Vite proxies `/api` to the backend on port 2500). On PowerShell, set `$env:MEDIA_ROOTS = 'C:\Media'` before starting those same two commands. Docker runs the production Linux worker.

## Checks

```bash
uv run ruff check backend tests scripts
uv run --extra dev --extra sync pytest -q
npm --prefix frontend run check
npm --prefix frontend run build
```

Install Chromium once with `cd frontend` then `npx playwright install chromium`. Run `npm run test:e2e`; it launches disposable fixture services itself. Linux CI also installs browser OS dependencies. For the production container, run `docker build -t sillage:local .` and `uv run python tests/docker_smoke.py`. All these checks use generated/shareable fixtures and deterministic test-only providers; no API key or paid request is needed.

## Pull requests

Use a topic branch and open a PR on GitHub. Describe the user-visible result, validation, compatibility and any data/timing risk. Add regression tests for fragile parsing, publication, provider or checkpoint changes. Update documentation with behavior. Keep private checkout notes in ignored .project-local/ and AGENTS.override.md.

Maintainers use Forgejo as the authoritative Git origin; GitHub is the public review/CI surface. Mirror repository-owned branches from Forgejo. Merge a protected PR once on GitHub, then fast-forward that exact result to Forgejo and verify parity. Do not create independent merges or move release tags. Contributors can use normal GitHub forks.

Follow [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md). Sensitive reports follow [SECURITY.md](SECURITY.md).
