# Verification status — 2026-10-26

Sillage 0.2.2 adds adaptive batches and zero-duration source-event preservation. It uses Docker port 2511 and development browser port 2499. Version 0.2.0 adds guided cloud/local provider setup and live model discovery, alongside structured translation reliability fixes. Screenshots use fictional dialogue encoded into real generated MKVs and test-only provider profiles, never private media or credentials. The production app has no simulated provider.

## Executed validation

| Check | Observed result |
| --- | --- |
| Backend suite | **245 passing tests**: generated real media, ASS/SSA/SRT invariants, filesystem confinement/atomic exports, seven provider/catalogue protocols, checkpoints/resume/cancellation, sync guards and API. Includes output-budget/recovery, catalogue bounds/pagination and saved-key isolation regressions. |
| Ruff | Backend, tests and maintenance scripts pass. |
| Frontend | TypeScript and Vite production build pass. |
| Browser | **6 Chromium workflows pass**: real API/worker/HTTP provider ASS/SRT processing; guided provider setup on desktop/mobile; saved-key reuse, multiple profiles, stale-catalogue isolation, manual fallback, model search, empty results and light/short-height layouts. Cloud catalogue responses in browser-only scenarios are isolated fixtures. |
| Local container | Build and full smoke pass on linux/amd64: compiled UI, media tools, non-root worker, real ASS/SRT HTTP pipeline, exports/downloads, preserved timings/MKV hashes and healthcheck. |
| Visual review | Rendered dark/light desktop, provider setup at 1440×1000 and 1280×640, and mobile at 390×844; subtitle tags are available through an explicit toggle. |
| Publication contract | Canonical Compose is image-only, README example is identical, source builds use a separate override. Native amd64/arm64 publication jobs smoke-test immutable registry candidates before promotion. Live publication status is shown by GitHub Actions and GHCR. |

One upstream Starlette/httpx test-client deprecation warning remains; it does not affect the production server. Provider protocol tests and the disposable HTTP integration fixture consume no credentials or cloud credits. A greedy placeholder-regex bug between adjacent ASS tags was discovered by the complete container test, corrected and covered by a regression.

DeepSeek requests now disable default thinking, following TraDoc's provider configuration and DeepSeek's documented control. Tests simulate reasoning exhausting the completion budget, valid-looking but truncated JSON, recursive recovery down to a single cue across seven protocols, complete-parent validation, a shared 64-call budget, adaptive wave/resume/episode feedback, profile/model isolation, JSON fences and timing diagnostics, cancellation and sanitized diagnostics. They do not establish translation quality or reproduce a private provider response. Output IDs, timing and formatting validation remain strict; existing job checkpoints need no migration.

Zero-duration ASS/SSA/SRT events now stay intact and untranslatable with review warnings; real generated MKV/external-ASS pipeline coverage verifies this. Reversed timings still fail before model calls. The exact private episode was not inspected, so this fixes a reproducible false rejection without claiming a confirmed diagnosis.

Catalogue tests verify seven native/compatible GET endpoints, native authentication headers, Gemini/Anthropic pagination, normalization/filtering, empty/malformed/oversized responses, bounded lists and same-endpoint saved-key reuse. The guided form is provider-agnostic; service availability, account permissions and model-specific translation quality still require the explicit live connection test.

## Acceptance still needed

- **Real provider:** no live cloud account or real LAN Ollama was contacted. Configure a profile, run the genuine connection test and inspect one episode's language quality.
- **Real library/player:** no production media library was mounted or changed. Verify host permissions, fonts, output discovery and playback in Jellyfin. Naming compatibility does not prove actual playback.
- **Speech synchronization:** synthetic offsets, silent-audio rejection, ambiguity/drift guards and real FFmpeg/WebRTC extraction are tested. Empirical thresholds are not calibrated against a representative anime corpus. Only the first audio track is used.
- **Complex ASS:** unsupported drawings/karaoke/animations/effects are preserved with review warnings. No universal fansub compatibility, translated-sign layout or pixel-rendered player validation is claimed.
- **Coverage limits:** automated browser tests cover the principal workflow; cancellation/resume and sync acceptance/refusal branches have backend coverage, with remaining click-level acceptance to do. Actual mobile devices and other browsers are unverified. Multi-architecture CI is the publication gate; do not infer native arm64 execution from a local amd64 build.

## Evidence and reproduction

[Explorer](screenshots/explorer-dark.png) · [Translated preview](screenshots/translation-preview-dark.png) · [Light theme](screenshots/translations-light.png) · [Mobile preview](screenshots/preview-mobile.png) · [Mobile settings](screenshots/settings-mobile.png).

[Guided provider setup](screenshots/providers-desktop.png) · [Mobile provider setup](screenshots/providers-mobile.png) · [Light provider form](screenshots/providers-light.png).

Run the checks in [CONTRIBUTING.md](../CONTRIBUTING.md). Container smoke uses the shipped Compose with isolated temporary media/config and an explicitly selected image. See [limits](limits.md), [Docker operations](docker.md), [provider protocols](providers.md) and [reuse audit](research.md).
