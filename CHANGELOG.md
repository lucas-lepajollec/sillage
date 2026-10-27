# Changelog

## Unreleased

## 0.0.9 — 2026-10-27

- Remove routine formatting-token copying from model generation across all thirteen adapters. Send each formatted cue as an ordered array of visible text spans, validate every returned span and rebuild exact source markers locally. Preserve line breaks, styles, entities, source timings and checkpoint compatibility; never guess a missing internal boundary or publish incomplete output.
- Exercise the real two-span contract in the single-call connection test, so a model that flattens structured cues cannot pass a plain-text-only check. Explain string/array responses with a worked example and provide sanitized failure-specific repair instructions. Accept an unwrapped single span only when its reconstruction is unambiguous. Preserve independently validated siblings and retry only invalid cues.
- Distinguish malformed JSON, parsed-but-invalid cue data, changed span counts and formatting errors. Retain aggregate structural counters without source text, raw responses, credentials or thought contents, including across failed/resumed jobs.
- Reset pre-slot batch learning when resuming older jobs; retain translated checkpoints and regrow current-contract limits normally. No provider/profile/schema migration or NAS rollout.

## 0.0.8 — 2026-10-27

- Recognize ASS typography with repeated intra-word style changes as an unsupported glyph-level effect. Preserve these events exactly with a review warning instead of asking the model to keep dozens of letter-bound formatting tokens and repeatedly failing near the ending.
- Resume older checkpoints safely when these effects were previously considered translatable: retain their stored rows, exclude those translations from rendering and update eligible counts. Keep rejecting unknown IDs and unrelated protected-event translations. Preview/finalization use the same policy, with no need to restart already translated dialogue.
- Exclude non-rendered ASS comments from the video-end bound; keep their bytes/timestamps and preserve all visible-event, drawing, reversed/negative and explicit-offset guards. A late editor comment no longer blocks every translation before the first request.
- Report protected-formatting failures as formatting errors instead of incorrectly calling successfully parsed JSON invalid. Source media, existing exports, provider settings and reasoning controls remain protected.

## 0.0.7 — 2026-10-27

- Replace permanent profile-wide batch minima with per-job recovery and gradual growth after three successful full waves. Ignore historical size-1 learning; isolated difficult cues no longer slow every episode.
- Request compact explicit-ID JSON maps, normalize equivalent maps/arrays and retain individually validated cues from complete responses. Retry only invalid/missing cues and preserve completed concurrent siblings on failure; keep strict formatting/timing/export validation and bounded recovery calls.
- Snapshot translation settings and credentials encrypted per job. Apply current execution limits at the next wave without invalidating checkpoints; keep each job's model/languages/endpoint stable through profile edits and finalization.
- Add individual/scoped in-place parameter adoption from Traductions, with explicit keep-progress or restart choices. Recover already-edited legacy jobs without deleting entries or rediscovering files; protect active work, language changes and existing exports with atomic group validation.

## 0.0.6 — 2026-10-27

- Add a default folder view for translation history, grouped by exact source directory with counts, searchable/status-filtered cards and pagination. Keep a remembered List alternative.
- Add confirmed per-job and scoped bulk cleanup of inactive history, checkpoints and work files while preserving media, source subtitles, profiles and exported sidecars. Reject active/in-flight jobs, serialize synchronization decisions, avoid following work symlinks and report cleanup-permission failures.
- Reanalyze a job's source without a provider call and reopen its episode/track preview in the explorer. Retain the old job/checkpoints, warn when its track disappeared and require an explicit new translation action. Existing exports remain protected.
- Scope bulk error retries and history cleanup to the current folder/search/filter across pages. No configuration/schema migration or provider/timing policy change.

## 0.0.5 — 2026-10-27

- Make source-track selection explicit per episode, with a direct preview, automatic/manual choice labels and default/forced/SDH/stream metadata. Highlight forced/signs-only sources and show eligible versus preserved event counts without an AI call.
- Apply equivalent source tracks to selected episodes, one exact folder or all scanned episodes, with a per-file match review. Match semantic metadata rather than stream indices; skip missing/ambiguous tracks and support restoring automatic choices.
- Record source-track metadata in new jobs and show it in their cards/previews. Legacy previews distinguish current-container labels from recorded metadata; existing jobs/checkpoints keep their original source. No database migration, media change or provider-call policy change.

## 0.0.4 — 2026-10-26

- Paginate translations with 10 jobs per page by default and 5/10/25 choices, result ranges and previous/next controls above and below the list. Search/filter changes return to page one; live progress refreshes keep the selected page, and shrinking results clamp to a valid page. Global counts and bulk retry still cover the whole queue.
- Keep mobile/touch form text at least 16 px across searches, provider settings, selectors and preview drawers to avoid input focus zoom while retaining manual page zoom.
- Adopt the requested `0.0.X` numbering, beginning at 0.0.4. Historical release tags stay intact; the current GitHub release and Docker image are explicitly marked latest.

## 0.3.0 — 2026-10-26

- Prefer no reasoning across all provider adapters, using each API's controls and bounded capability discovery for Ollama, OpenRouter and LM Studio. Models requiring reasoning keep working with the lowest configurable effort and explicit time/token warnings.
- Add Groq, Mistral, xAI/Grok, native LM Studio, vLLM and llama.cpp profiles, live model discovery and optional authentication for local services. Use Responses for known OpenAI Pro models that require that endpoint.
- Detect provider-reported reasoning without retaining its text; expose warnings in model selection, connection tests and jobs, including failed batches and resumes with all cues already checkpointed. Unsupported off parameters are never silently removed after an HTTP error.
- Keep adaptive batch recovery, strict IDs/formatting, source timings, encrypted keys and existing checkpoints. Unknown compatible servers stay usable with a warning that disabling reasoning cannot be confirmed.

## 0.2.2 — 2026-10-26

- Start with conservative cloud/local batch ceilings and a UTF-8 byte limit. Reduce invalid batches progressively down to a single cue instead of requiring manual episode restarts; remember reduced ceilings for the same unchanged provider profile/configuration across waves, resumes and recent episodes.
- Bound all retry/split descendants to 64 HTTP calls per initial batch; never split network/auth/refusal errors or accept incomplete parent batches. Permit a complete JSON code fence without accepting surrounding prose or relaxing IDs/formatting validation.
- Preserve zero-duration ASS/SSA/SRT events without translating them, with a review warning. They were incorrectly rejected by the negative/reversed-duration diagnostic. Truly reversed source timings still fail before any model call, now with an event ID, line and timestamps.
- Existing validated checkpoints/settings remain compatible; no database migration. Actual model quality and the private episode's exact source defect still require operator acceptance.

## 0.2.1 — 2026-10-26

- Use port **2511** for the production container and its default host mapping, including the healthcheck.
- Use browser port **2499** for local development, with a separate loopback backend on 2500 only for Vite hot reload.
- Existing installations must change their Compose mapping from `5775:5775` to `2511:2511` when pulling this image. No configuration/database migration is required. Keep the old mapping when rolling back to 0.2.0.

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
