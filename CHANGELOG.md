# Changelog

## Unreleased

## 0.2.0 — 2026-10-26

- Simplify provider setup: choose a service, enter its key or local server URL, load its models and select one. Names are optional; languages, glossary and limits remain under advanced settings.
- Discover live model catalogues for OpenAI, Anthropic, Gemini, DeepSeek, OpenRouter, Ollama and compatible endpoints, with search and manual fallback. Keep multiple independent translation profiles.
- Reuse saved keys on the server without returning them to the browser. Bind key reuse to the original provider/endpoint and clear stale model lists when connection details change.
- Use Anthropic's native API-key header for model listing and translation.

- Disable DeepSeek's default thinking mode for structured subtitle translation, as in TraDoc, so reasoning cannot consume the answer's output budget.
- Account for cue IDs, JSON syntax and UTF-8 text in the completion budget, with a 2,048-token floor and an 8,192-token cap. Truncated generations retry with more output room.
- Recover persistent structural failures in two smaller, independently validated batches, with one bounded attempt per half. Never checkpoint partial results or relax ID/formatting validation.
- Distinguish output truncation, protected-formatting errors and malformed responses. Do not split authentication, transport, rate-limit failures or explicit refusals.

No database migration or provider setting change is required. Existing validated checkpoints remain resumable after updating the container.

## 0.1.0 — 2026-10-26

Initial public version for operator testing.

- Lazy file explorer, recursive MKV inspection, source track selection and subtitle preview.
- ASS/SSA/SRT translation with strict IDs, protected markup and source timestamp preservation.
- Seven configurable cloud/LAN provider protocols, connection tests and profile glossaries.
- SQLite jobs/checkpoints, bounded requests, cancellation and resume.
- Explicit manual offsets and conservative audio-only synchronization proposals requiring acceptance.
- Atomic sidecar exports without overwriting originals or existing results.
- French UI, dark/light themes and responsive layouts.
- Published Docker image, image-based Compose, source-build override and reproducible CI.

Complex karaoke, drawings and animations may remain untranslated with review warnings. Live provider quality, actual library playback and speech-sync calibration still require operator acceptance. See [verification](docs/STATUS.md) and [limits](docs/limits.md).
