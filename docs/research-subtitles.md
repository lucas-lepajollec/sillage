# ASS preservation and synchronization audit

Audit: 2026-10-26. Public upstream repositories were opened through the GitHub
connector, then shallow-cloned for a targeted source/test inspection. Clones are
research inputs in `/tmp`, not runtime dependencies or hidden vendored packages.

## Sources and reuse

| Upstream snapshot | Inspected implementation and evidence | Decision |
| --- | --- | --- |
| [Sublarr `87273dba`](https://github.com/Abrechen2/sublarr/tree/87273dbaf22848b11172a67b7a2a6a8856166b2e) | `backend/ass_lexer.py`, `ass_utils.py`, `ass_drawing.py`, `ass_probe.py`; `translator/ass_flow.py`, `output_guard.py`, `quality.py`; lossless-parser/drawing/karaoke/output-guard tests and renderer-reference fixture documentation | Adapt the bounded lexer only. Preserve its argument parsing and resource limits. Avoid importing its scheduler, configuration, database, selection rules or proportional tag placement. |
| [pysubs2 `ae3c520a`](https://github.com/tkarabela/pysubs2/tree/ae3c520a8aa13130f36d84df02ce15a843bc9bdb) | `formats/substation.py`, `subrip.py`; SubStation tests for timestamp underflow/overflow, centisecond rounding, malformed styles and nonstandard format lines; Aegisub attachment fixtures | Use installed pysubs2 as an independent structure/count/timing check. Patch original spans rather than use its serializer, which rebuilds headers/styles and can clamp/round times. Copy one small MIT Aegisub fixture to test opaque attachments. |
| [ffsubsync `de310ac6`](https://github.com/smacke/ffsubsync/tree/de310ac6944b8260431a48ee741e7063cec49b0f) | `ffsubsync.py` reference selection, alignment result and quality gates; `speech_transformers.py` subtitle fallback, WebRTC/auditok VAD and FFmpeg extraction; `aligners.py` FFT search | Reuse installed MIT `FFTAligner`. Extract audio with a bounded argument-list FFmpeg process and classify PCM with WebRTC VAD. Never provide a subtitle reference. Tested installed optional dependency: ffsubsync0.5.1 (FFTAligner contract revalidated in0.0.12). |
| [alass `874f02d9`](https://github.com/kaegi/alass/tree/874f02d9577182752a0f969b6d6b98fd65bdf1fc) | README usage, `alass-cli/src/lib.rs`, binary FFmpeg decoder and `alass-core/src/alass.rs`; global/no-splits and piecewise alignment design | Deferred: another Rust/native binary adds installation surface without solving the V1 confidence problem. Its split/framerate correction is outside our deliberately global-offset mode. |

Sublarr's utility layer classifies positioned/sign styles and can restore tags by
proportional character placement. Sillage instead translates safe static panels
and exposes formatting as ordered placeholders. Repositioning a tag by a guessed
character ratio is unnecessary here. Sublarr's output guard and quality code also
show why matching line counts alone cannot prove a genuine translation; provider
validation and human preview remain separate from structural correctness.

A GitHub issue search found no matching public Sublarr drawing issue in the
returned results; the actual repository's regression tests provide the evidence.
No absence-of-bugs claim follows from a search without results.

## License provenance

Sublarr's root [LICENSE](https://github.com/Abrechen2/sublarr/blob/87273dbaf22848b11172a67b7a2a6a8856166b2e/LICENSE)
and README identify GPL-3.0. The lexer portion in `backend/sillage/subtitles.py`
(`Token`, limits, `_positive`, `_state`, `lex` and its exception) is adapted from
that snapshot, copyright Sublarr contributors. Imports/docstrings were moved;
the bounded drawing-state algorithm is preserved. The new document parser,
placeholder enforcement and original rich fixture are Sillage code. Drawing
regression examples in the tests are adapted from Sublarr's tests as well.
Sillage therefore uses **GPL-3.0-only**, retaining the GPL license and provenance;
this is not an MIT relicense of Sublarr code. No libass C code is copied.

pysubs2 is MIT, copyright Tomas Karabela; the unmodified upstream Aegisub fixture
and its full MIT notice live under `tests/fixtures/`. No upstream fonts are copied.
ffsubsync is MIT, copyright Stephen Macke, and is installed as an optional
third-party dependency, not copied. WebRTC VAD comes through that extra. alass is
GPL-3.0 and was researched, not bundled or invoked. Runtime distributions must
retain applicable dependency notices; the research does not change their licenses.

## Implemented subtitle guarantees

`SubtitleDocument.load(path)` accepts ASS, SSA and SRT, exposes stable event IDs,
original preview cues, translatable segments and explicit per-event warnings.
`validate_translations(mapping, require_all=True)` detects incomplete final sets;
partial sets are allowed for checkpoints/previews. `render(mapping, offset_ms=0)`
validates and patches original text spans. It does not save a file itself.

- Source event order, comments, styles, layers, margins, effects, unknown sections,
  opaque attachments, timestamps and line endings retain their exact decoded
  spelling by default. Empty rendering is an exact decoded-text round trip.
- All ASS override blocks, layout escapes, SRT markup/entities and physical SRT
  breaks become `__SILLAGE_0000__` placeholders. Output must contain the identical
  ordered sequence; prefix/suffix tags stay anchored. A model cannot introduce
  formatting, physical lines or extra event syntax. Midphrase tags remain at
  model-chosen translated phrase boundaries while preserving their sequence.
- Safe static positioned signs/panels are translated, including `pos`, alignment,
  rotation and clipping. This preserves syntax, not an assurance that a longer
  translation fits the original rectangle. Preview and real player checks matter.
- Drawing-only and mixed drawing/text events, karaoke, timed transforms, moving
  text and nonempty animation/custom Effect fields are preserved with warnings.
  They never reach the language model. This conservative V1 does not translate
  every kind of fansub, infer splits around mixed geometry or rasterize panels.
- Overlaps remain intentional data. We do not merge, split or normalize cues.
  Invalid dialogue intervals and inconsistent parser results fail closed.
  Zero-duration editor comments are preserved as comments.
- ASS/SSA supports canonical event-column order and `H:MM:SS.cc` timestamps.
  Nonstandard formats require review. Files over 30 MB and ambiguous physical
  boundaries are refused; events/tags have bounded lexer budgets.
- UTF-8 and BOM-marked UTF-16 are decoded strictly. Other encodings use
  charset-normalizer with an explicit verification warning, or an explicit
  library `encoding=` override. Short legacy samples can remain ambiguous.
  Sidecars are published as UTF-8; byte encoding changes are deliberate while
  decoded Unicode and untouched syntax are preserved.

Manual offset rendering changes only timestamp spans. Positive offsets delay
cues. Negative/unrepresentable results are refused, never clamped. ASS/SSA
requires a multiple of 10 ms, SRT supports 1 ms; no implicit precision loss.
`timing_warnings(duration, offset_ms)` checks video-duration boundaries. Preserved
timings mean **source timing preserved**, never **audio alignment verified**.

## Implemented automatic proposals

[ffsubsync issue #238](https://github.com/smacke/ffsubsync/issues/238) documents
forced-only embedded subtitle stubs attracting incorrect large offsets with the
default `subs_then_webrtc` detector. Source inspection confirms the fallback path.
`--vad webrtc --reference-stream a:0` is the relevant CLI choice when using that
CLI against audio. auditok uses energy-style activity and does not resolve the
same confidence/track-selection problem by itself.

Sillage's `propose_sync(video, subtitle, duration)` avoids that ambiguity entirely:
FFmpeg explicitly maps `0:a:0`, disables subtitle/video/data output, and writes
16 kHz mono PCM to a temporary file. A subprocess timeout bounds extraction;
PCM is read in 20 ms frames and removed afterwards. WebRTC VAD supplies the
activity vector; installed ffsubsync supplies the global FFT offset search.
No ASR, external service, subtitle reference, speed change or split is involved.

A candidate requires all of these conservative, currently empirical checks:

- Video duration 2 minutes–4 hours, at least 20 usable dialogue cues, audio
  duration consistent with the media, source timestamps within media bounds.
- Search limited to ±10 s; a peak at the search boundary is refused.
- Activity on both sides must be sufficient and neither nearly silent nor
  continuous; each third must have at least 5 s of measurable activity.
- Pearson correlation at least 0.30, a 0.025 margin against competing peaks
  at least 500 ms away, and meaningful improvement over zero when shifting.
- Independent early/middle/late estimates agree within 300 ms and each has
  correlation at least 0.20. Divergence rejects likely drift or montage changes.
- Reapplying the offset passes subtitle/parser/timing checks; cues cannot cross
  the media boundary or become negative.

Resolution is 20 ms, directly representable in ASS. `confidence` is the measured
correlation coefficient, **not a calibrated probability**. These thresholds favor
refusal, have not been validated against a representative anime corpus, and can
reject a useful correction. The first audio track can be the wrong language or
commentary: that choice is disclosed, not certified. Dialogue-free openings,
songs, noisy mixes, mismatched cuts and framerate drift may require manual work.

The function returns an offset/correlation/warnings proposal and modifies no
file. The job layer must keep it in review, show before/after times, and wait for
explicit acceptance. Rejecting the proposal publishes with source timings. An
uncertain result raises a clear refusal and retains source timings.

## Verification and limits

Executed locally: `uv run --extra sync pytest tests/test_subtitles.py
tests/test_sync.py -q` — **62 passed**; scoped Ruff check passed. Tests cover
multiple/midphrase tags, breaks, vector/mixed drawing, karaoke, positioned signs,
overlap, comments, Unicode, BOM/legacy encodings, incomplete files, malformed
syntax, adversarial model output, immutable metadata/timings, signed offsets,
independent-window drift, silent/continuous/random activity and safe subprocess
arguments. An actual FFmpeg/WebRTC test embeds the very same dense subtitle
track over silent audio: automatic sync refuses it rather than self-verifying.
A genuine Aegisub-generated upstream attachment fixture round-trips unchanged.

This is not a libass pixel-rendering acceptance test for translated fansubs, a
Jellyfin playback test, a real episode/audio synchronization calibration, or a
cloud translation-quality evaluation. Those remain explicit acceptance work.
