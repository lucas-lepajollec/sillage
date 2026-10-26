# Translation engine source study

Inspected 2026-10-26: [`gnehs/subtitle-translator-electron`](https://github.com/gnehs/subtitle-translator-electron), revision [`e8803bb3d003f995aeea4eed1ece8e537149f4c2`](https://github.com/gnehs/subtitle-translator-electron/tree/e8803bb3d003f995aeea4eed1ece8e537149f4c2). This is source-level study, not a claim that the application was installed or exercised. The observed package declares version 2.0.2 and an MIT license. Sillage's Python implementation is written independently; no upstream code or assets were copied.

## Observed Strict workflow

[`process-strict-translation-file.ts`](https://github.com/gnehs/subtitle-translator-electron/blob/e8803bb3d003f995aeea4eed1ece8e537149f4c2/electron/main/process-strict-translation-file.ts) divides pending cues into 20-cue chunks, supplies five surrounding cues on either side by default, uses configured concurrency, and persists checkpoint progress after completed chunks. Context goes to the model but only the current core is translated. Optional analysis at 40 or more non-empty cues produces scene information and a glossary. The checkpoint writer serializes writes through temporary files. Incompatible settings trigger checkpoint preservation; finished jobs remove the Strict checkpoint. This implementation also writes partial subtitle output during translation.

[`subtitle-chunks.ts`](https://github.com/gnehs/subtitle-translator-electron/blob/e8803bb3d003f995aeea4eed1ece8e537149f4c2/electron/main/utils/subtitle-chunks.ts) groups only contiguous pending regions; completed or blank cues break chunks. Pathological exact repeated short phrases are compacted before prompting. The pending-state distinction prevents paying to translate already completed cues again.

[`translate.ts`](https://github.com/gnehs/subtitle-translator-electron/blob/e8803bb3d003f995aeea4eed1ece8e537149f4c2/electron/main/utils/translate.ts) uses the AI SDK with an OpenAI-compatible adapter. Its Strict prompt requires an exact ordered array for the core and prohibits split/merge/renumbering. It requests JSON, checks the completion reason, validates the result and attempts structural repair. Streamed repetition detection can interrupt runaway model output. The optional analysis samples source text rather than sending an entire file.

[`translation-output.ts`](https://github.com/gnehs/subtitle-translator-electron/blob/e8803bb3d003f995aeea4eed1ece8e537149f4c2/electron/main/utils/translation-output.ts) accepts an array or an object containing `elements`, checks the exact core count and non-empty translations, and supplies a repair prompt. A valid model stop is required. These are structural checks, not semantic translation evaluation.

[`translation-checkpoint.ts`](https://github.com/gnehs/subtitle-translator-electron/blob/e8803bb3d003f995aeea4eed1ece8e537149f4c2/electron/main/utils/translation-checkpoint.ts) compares source name, format, size and modification time. A SHA-256 fingerprint represents translation-affecting settings. Changed settings invalidate derived analysis and preserve the old checkpoint while retaining completed translations; they do not prove completed text remains suitable for a changed target language.

## Sillage decisions

Sillage adopts strict cue mapping, bounded batches, surrounding text context, an explicit glossary, bounded retries and durable completion checkpoints. Stable IDs are included in every response so validation can reject unknown, duplicate and missing cues even when an array's count happens to match. Protected formatting tokens are validated before saving a completed batch; subtitle rendering restores the original structure and timings. The model receives text only.

Sillage's persistence and output ownership live in the worker and subtitle engine, while the provider layer accepts one pending batch. This makes checkpoint behavior testable without an API and prevents HTTP adapters from touching media files. A completed batch is the checkpoint unit. Provider configuration changes must not silently mix target languages in a resumed job; the worker owns the stored job identity.

Sillage deliberately publishes a final validated sidecar, rather than a partially translated output. An interrupted job retains its backend checkpoint and leaves the source and existing sidecars intact. Timing preservation is the default; alignment is a separate explicit operation. ASS/SSA drawing or unsupported complex events are surfaced for review by the subtitle layer.

Automatic scene/glossary analysis and upstream Adaptive resegmentation are not implemented here. Analysis adds calls and cost; users can provide glossary/context directly. Adaptive cue merging/splitting conflicts with the requested exact timing/structure preservation. The HTTP layer bounds output size and completion budget but does not implement the upstream streaming repetition guard. Quality, account-specific models and a real provider response remain live acceptance work; deterministic protocol tests do not establish translation quality.

See [provider setup and adapter choice](providers.md) for official protocol sources and the direct-adapter versus LiteLLM comparison.
