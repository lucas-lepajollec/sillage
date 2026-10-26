# Verification status — 2026-10-26

Sillage 0.1.1 fixes structured translation reliability in the initial public series. Screenshots use fictional dialogue encoded into real generated MKVs, never a private media collection. The production app has no simulated provider.

## Executed validation

| Check | Observed result |
| --- | --- |
| Backend suite | **192 passing tests**: generated real media, ASS/SSA/SRT invariants, filesystem confinement/atomic exports, seven provider protocols, checkpoints/resume/cancellation, sync guards and API. Includes 19 output-budget/recovery regressions. |
| Ruff | Backend, tests and maintenance scripts pass. |
| Frontend | TypeScript and Vite production build pass. |
| Browser | **2 Chromium workflows pass** against the real API/worker and a test-only HTTP endpoint: browse/recursive scan, selection/source preview, provider configuration/test, persisted selection, ASS/SRT translation, progress/downloads, light theme, filters/empty states and mobile. |
| Local container | Build and full smoke pass on linux/amd64: compiled UI, media tools, non-root worker, real ASS/SRT HTTP pipeline, exports/downloads, preserved timings/MKV hashes and healthcheck. |
| Visual review | Rendered dark/light desktop at 1440×1000 and mobile at 390×844; subtitle tags are available through an explicit toggle. |
| Publication contract | Canonical Compose is image-only, README example is identical, source builds use a separate override. Native amd64/arm64 publication jobs smoke-test immutable registry candidates before promotion. Live publication status is shown by GitHub Actions and GHCR. |

One upstream Starlette/httpx test-client deprecation warning remains; it does not affect the production server. Provider protocol tests and the disposable HTTP integration fixture consume no credentials or cloud credits. A greedy placeholder-regex bug between adjacent ASS tags was discovered by the complete container test, corrected and covered by a regression.

DeepSeek requests now disable default thinking, following TraDoc's provider configuration and DeepSeek's documented control. Tests simulate reasoning exhausting the completion budget, valid-looking but truncated JSON, persistent structural failures recovered in two validated halves, failure of the second half, bounded retry counts, cancellation and sanitized diagnostics. They do not establish translation quality or reproduce a private provider response. Output IDs, timing and formatting validation remain strict; existing job checkpoints need no migration.

## Acceptance still needed

- **Real provider:** no live cloud account or real LAN Ollama was contacted. Configure a profile, run the genuine connection test and inspect one episode's language quality.
- **Real library/player:** no production media library was mounted or changed. Verify host permissions, fonts, output discovery and playback in Jellyfin. Naming compatibility does not prove actual playback.
- **Speech synchronization:** synthetic offsets, silent-audio rejection, ambiguity/drift guards and real FFmpeg/WebRTC extraction are tested. Empirical thresholds are not calibrated against a representative anime corpus. Only the first audio track is used.
- **Complex ASS:** unsupported drawings/karaoke/animations/effects are preserved with review warnings. No universal fansub compatibility, translated-sign layout or pixel-rendered player validation is claimed.
- **Coverage limits:** automated browser tests cover the principal workflow; cancellation/resume and sync acceptance/refusal branches have backend coverage, with remaining click-level acceptance to do. Actual mobile devices and other browsers are unverified. Multi-architecture CI is the publication gate; do not infer native arm64 execution from a local amd64 build.

## Evidence and reproduction

[Explorer](screenshots/explorer-dark.png) · [Translated preview](screenshots/translation-preview-dark.png) · [Light theme](screenshots/translations-light.png) · [Mobile preview](screenshots/preview-mobile.png) · [Mobile settings](screenshots/settings-mobile.png).

Run the checks in [CONTRIBUTING.md](../CONTRIBUTING.md). Container smoke uses the shipped Compose with isolated temporary media/config and an explicitly selected image. See [limits](limits.md), [Docker operations](docker.md), [provider protocols](providers.md) and [reuse audit](research.md).
