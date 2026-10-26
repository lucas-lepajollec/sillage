# Third-party notices

Sillage is distributed under GPL-3.0-only; see [LICENSE](LICENSE). Dependencies retain their own licenses. These notices describe the parts reused in this source tree, not a relicensing of those projects.

## Sublarr — GPL-3.0

Copyright Sublarr contributors. The bounded ASS lexer (`Token`, limits, `_positive`, `_state`, `lex`, associated exception) in `backend/sillage/subtitles.py` and some drawing regression cases are adapted from [Abrechen2/sublarr](https://github.com/Abrechen2/sublarr/tree/87273dbaf22848b11172a67b7a2a6a8856166b2e), `backend/ass_lexer.py` and related tests. Imports/documentation were rearranged; document span parsing and placeholder reconstruction were added separately. The GPLv3 license text is retained in the root LICENSE. See [source audit](docs/research-subtitles.md).

## shadcn-admin — MIT

Copyright (c) 2024 Sat Naing. The Button/CVA/Slot implementation and TanStack table integration patterns are adapted from [satnaing/shadcn-admin](https://github.com/satnaing/shadcn-admin/tree/e16c87f213a5ba5e45964e9b67c792105ec74d26). Styling/variants and application behavior were adapted for Sillage. The complete permission notice is retained in [frontend/notices/shadcn-admin-LICENSE](frontend/notices/shadcn-admin-LICENSE).

## pysubs2 — MIT

Copyright Tomas Karabela. Used as an installed parser/validation dependency. The unmodified Aegisub attachment fixture from revision `ae3c520a8aa13130f36d84df02ce15a843bc9bdb` is retained with the full [MIT notice](tests/fixtures/LICENSE-pysubs2.txt) and [fixture provenance](tests/fixtures/README.md).

## Other installed dependencies

Python dependency wheels retain their distribution metadata/license files. These include FastAPI (MIT), Uvicorn (BSD-3-Clause), HTTPX (BSD-3-Clause), cryptography (Apache-2.0 OR BSD-3-Clause), charset-normalizer (MIT), ffsubsync (MIT, Stephen Macke), numpy (BSD-3-Clause), WebRTC VAD bindings and their upstream notices. Frontend packages retain their notices in node_modules; Inter is SIL OFL-1.1, Lucide is ISC, React/TanStack/Radix/Tailwind/CVA/clsx/tailwind-merge are MIT. Exact installed versions are locked in `uv.lock` and `frontend/package-lock.json`.

The runtime image includes Debian FFmpeg/MKVToolNix and supporting packages, with applicable distribution copyright notices under `/usr/share/doc`. Those tools are invoked as separate processes. Redistributors must preserve the applicable source/license obligations for their chosen binary builds; this document does not replace those licenses.

FileBrowser Quantum (Apache-2.0), Subtitle Translator (MIT) and alass (GPL-3.0) were studied without copying their code. [Research index](docs/research.md).
