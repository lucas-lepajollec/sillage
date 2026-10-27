# Verification status — 2026-10-27

Sillage 0.0.6 adds folder-based translation history, confirmed inactive-history cleanup preserving exports, and free per-job source reanalysis back into the explorer. Version 0.0.5’s individual/group source-track selection, metadata snapshots and event counts remain. Version 0.0.4's paginated translations and readable mobile controls remain. Release numbering increments only the final component (`0.0.X`); historical tags remain intact. The common reasoning preference, thirteen providers, adaptive batches and zero-duration preservation remain. Docker uses2511 and development uses2499. Screenshots use fictional dialogue encoded into generated MKVs and test-only provider profiles, never private media or credentials. The production app has no simulated provider.

## Executed validation

| Check | Observed result |
| --- | --- |
| Backend suite | **347 passing tests**: generated real media, ASS/SSA/SRT invariants, filesystem confinement/atomic exports, thirteen provider/catalogue protocols, checkpoints/resume/cancellation, sync guards and API. Includes atomic history deletion, active/sync guards, work symlink confinement, cleanup warnings and descriptor ownership through request cancellation; plus source snapshots, legacy fallbacks and provider/recovery isolation. |
| Ruff | Backend, tests and maintenance scripts pass. |
| Frontend | TypeScript and Vite production build pass. |
| Browser | **16 Chromium checks pass**: real API/worker/HTTP provider ASS/SRT processing; guided provider setup on desktop/mobile; saved-key reuse, multiple profiles, stale-catalogue isolation, manual fallback, model search, empty results and light/short-height layouts. Includes selecting/saving mandatory-reasoning models, local optional keys and review warnings with real exports. Pagination tests cover desktop/mobile page sizes, boundaries, search/status resets, actual polling stability and shrinking results. Mobile computed font sizes are checked across search, preview and advanced provider fields, with manual zoom still permitted. Source-track checks cover reordered streams, missing/ambiguous matches, explicit scopes and free previews. History checks cover folder pagination/counts, persisted List mode, scoped cleanup/retry and mobile source reanalysis. The real API/worker workflow reanalyzes and deletes a completed entry while keeping its export. Cloud catalogue responses and synthetic job histories in browser-only scenarios are isolated fixtures. |
| Local container | Build and full smoke pass on linux/amd64: compiled UI, media tools, non-root worker, real ASS/SRT HTTP pipeline, exports/downloads, read-only reanalysis, actual history cleanup retaining exports, preserved timings/MKV hashes and healthcheck. |
| Visual review | Rendered dark/light desktop, provider setup at 1440×1000 and 1280×640, and mobile at 390×844; subtitle tags are available through an explicit toggle. |
| Publication contract | Canonical Compose is image-only, README example is identical, source builds use a separate override. Native amd64/arm64 publication jobs smoke-test immutable registry candidates before promotion. Live publication status is shown by GitHub Actions and GHCR. |

One upstream Starlette/httpx test-client deprecation warning remains; it does not affect the production server. Provider protocol tests and the disposable HTTP integration fixture consume no credentials or cloud credits. A greedy placeholder-regex bug between adjacent ASS tags was discovered by the complete container test, corrected and covered by a regression.

DeepSeek requests now disable default thinking, following TraDoc's provider configuration and DeepSeek's documented control. Tests simulate reasoning exhausting the completion budget, valid-looking but truncated JSON, recursive recovery down to a single cue across thirteen protocols, complete-parent validation, a shared 64-call budget, adaptive wave/resume/episode feedback, profile/model isolation, JSON fences and timing diagnostics, cancellation and sanitized diagnostics. They do not establish translation quality or reproduce a private provider response. Output IDs, timing and formatting validation remain strict; existing job checkpoints need no migration.

The common reasoning policy is tested on real wire payloads, not only local model-name decisions: required reasoning still translates, reported reasoning warns without leaking thought text, failed probes remain bounded, unsupported off flags are not silently removed, cache bindings remain isolated and warnings persist across finalization resumes. Native LM Studio/Responses output limits and thinking/text separation are covered. No real cloud or LAN model was contacted.

Zero-duration ASS/SSA/SRT events now stay intact and untranslatable with review warnings; real generated MKV/external-ASS pipeline coverage verifies this. Reversed timings still fail before model calls. The exact private episode was not inspected, so this fixes a reproducible false rejection without claiming a confirmed diagnosis.

Catalogue tests verify thirteen native/compatible GET endpoints, native authentication headers, Gemini/Anthropic pagination, normalization/filtering, empty/malformed/oversized responses, bounded lists and same-endpoint saved-key reuse. The guided form is provider-agnostic; service availability, account permissions and model-specific translation quality still require the explicit live connection test.

## Acceptance still needed

- **Real provider:** no live cloud account or real LAN Ollama was contacted. Configure a profile, run the genuine connection test and inspect one episode's language quality.
- **Real library/player:** no production media library was mounted or changed. Verify host permissions, fonts, output discovery and playback in Jellyfin. Naming compatibility does not prove actual playback.
- **Speech synchronization:** synthetic offsets, silent-audio rejection, ambiguity/drift guards and real FFmpeg/WebRTC extraction are tested. Empirical thresholds are not calibrated against a representative anime corpus. Only the first audio track is used.
- **Complex ASS:** unsupported drawings/karaoke/animations/effects are preserved with review warnings. No universal fansub compatibility, translated-sign layout or pixel-rendered player validation is claimed.
- **Mobile focus zoom:** the 16 px minimum and layout/zoom permissions are verified in Chromium emulation. Actual iPhone/iPad Safari focus/keyboard behavior remains a real-device acceptance check.
- **Coverage limits:** automated browser tests cover the principal workflow; cancellation/resume and sync acceptance/refusal branches have backend coverage, with remaining click-level acceptance to do. Actual mobile devices and other browsers are unverified. Multi-architecture CI is the publication gate; do not infer native arm64 execution from a local amd64 build.

## Evidence and reproduction

[Explorer](screenshots/explorer-dark.png) · [Translated preview](screenshots/translation-preview-dark.png) · [Light theme](screenshots/translations-light.png) · [Mobile preview](screenshots/preview-mobile.png) · [Mobile settings](screenshots/settings-mobile.png).

[Translation folders](screenshots/history-folders-desktop.png) · [Mobile folders](screenshots/history-folders-mobile.png).

[Source-track matching](screenshots/source-track-matching-desktop.png) · [Mobile source tracks](screenshots/source-track-matching-mobile.png).

[Paginated translations](screenshots/translations-pagination-desktop.png) · [Mobile pagination](screenshots/translations-pagination-mobile.png).

[Guided provider setup](screenshots/providers-desktop.png) · [Mobile provider setup](screenshots/providers-mobile.png) · [Light provider form](screenshots/providers-light.png).

Run the checks in [CONTRIBUTING.md](../CONTRIBUTING.md). Container smoke uses the shipped Compose with isolated temporary media/config and an explicitly selected image. See [limits](limits.md), [Docker operations](docker.md), [provider protocols](providers.md) and [reuse audit](research.md).
