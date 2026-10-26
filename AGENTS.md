# Sillage maintainer instructions

Sillage is a focused, self-hosted subtitle translation studio: browse mounted media, select MKV tracks, translate text, validate and publish external sidecars. French UI; English public documentation.

## Preserve media and translation boundaries

- Never write, remux or re-encode source MKVs or source sidecars.
- Confine every media path to configured canonical roots; subprocesses use argument lists, never interpolated shell strings.
- LLMs receive stable IDs and protected text only. Validate complete IDs, placeholders, event structure and timestamps before publishing.
- Preserve source timing by default. Explicit synchronization must remain separate, guarded and reviewable.
- Preserve unsupported drawings/karaoke/animations with warnings; never claim universal ASS support.
- Export through exclusive atomic publication. Never replace existing output automatically.
- Keep provider secrets on the backend, encrypted at rest and excluded from logs/API responses.

## Development and verification

Python 3.12+, uv, Node 22+, Docker and FFmpeg/ffprobe:

```bash
uv sync --frozen --extra dev --extra sync --python 3.12
npm --prefix frontend ci
uv run ruff check backend tests scripts
uv run --extra dev --extra sync pytest -q
npm --prefix frontend run check
npm --prefix frontend run build
npm --prefix frontend run test:e2e
docker build -t sillage:local .
uv run python tests/docker_smoke.py
```

The browser suite starts disposable generated media and a test-only HTTP provider. No production simulator or credential discovery. Real providers and real-player acceptance are separate from deterministic tests.

Update documentation and meaningful tests when behavior changes. Keep the recommended Compose image-based and README example identical. Source builds use docker-compose.build.yml. Follow CONTRIBUTING.md and SECURITY.md; use focused branches/PRs. Machine-specific context belongs in ignored AGENTS.override.md and .project-local/, never public Markdown.
