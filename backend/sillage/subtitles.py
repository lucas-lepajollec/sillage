"""Lossless subtitle patching; only validated text spans and explicit offsets change.

The bounded ASS lexer below is adapted from Sublarr backend/ass_lexer.py,
commit 87273dbaf22848b11172a67b7a2a6a8856166b2e, GPL-3.0.
Copyright Sublarr contributors. See docs/research-subtitles.md for provenance.
Sillage's document parser/placeholder restoration below is original code.
"""
from __future__ import annotations

# Bounded, lossless ASS lexer from Sublarr. Drawing-state parsing follows
# libass 0.17.3 argument boundaries; this is not a full ASS validator.


import re
from dataclasses import dataclass
from collections.abc import Mapping
from pathlib import Path
import warnings as python_warnings

import pysubs2
from charset_normalizer import from_bytes

MAX_EVENT = 131072
MAX_TAGS = 4096
MAX_TRANSFORMS = 32
INTEGER = re.compile(r"[ \t\r\n\v\f]*([+-]?)([0-9]+)")
LAYOUT = re.compile(r"\\[Nnh]")


class ASSNeedsReviewError(ValueError):
    """The event or model output cannot safely be rewritten."""


@dataclass(frozen=True)
class Token:
    start: int
    end: int
    raw: str
    kind: str
    drawing: bool
    group: int | None


def _positive(arg):
    # strtoll's ASCII whitespace/sign/digits; clamping cannot change positivity.
    match = INTEGER.match(arg)
    return bool(match and match[1] != "-" and any(c != "0" for c in match[2]))


def _state(block, current, budget, depth=0):
    if depth > MAX_TRANSFORMS:
        raise ASSNeedsReviewError("transform nesting limit")
    p = 0
    end = len(block)
    while p < end:
        slash = block.find("\\", p)
        if slash < 0:
            break
        budget[0] -= 1
        if budget[0] < 0:
            raise ASSNeedsReviewError("tag budget exceeded")
        p = slash + 1
        while p < end and block[p] in " \t":
            p += 1
        q = p
        while q < end and block[q] not in "(\\":
            q += 1
        if q == p:
            continue
        name = block[p:q]
        args = []
        has_backslash = False

        def push(a, b):
            part = block[a:b].rstrip(" \t")
            if part and len(args) < 8:
                args.append(part)

        if q < end and block[q] == "(":
            q += 1
            while True:
                while q < end and block[q] in " \t":
                    q += 1
                r = q
                while r < end and block[r] not in ",\\)":
                    r += 1
                if r < end and block[r] == ",":
                    push(q, r)
                    q = r + 1
                    continue
                if r < end and block[r] == "\\":
                    has_backslash = True
                    close = block.find(")", r)
                    r = end if close < 0 else close
                push(q, r)
                q = min(r + 1, end)
                break

        # Prefix precedence matters: pos and pbo are NOT drawing switches.
        if name.startswith("p") and not name.startswith(("pos", "pbo")):
            remainder = name[1:].rstrip(" \t")
            if remainder and len(args) < 8:
                args.append(remainder)
            current = _positive(args[0] if args else "")
        elif name.startswith("t") and has_backslash and 1 <= len(args) <= 4:
            # Drawing mode is set directly even inside timed transforms.
            current = _state(args[-1], current, budget, depth + 1)
        p = q
    return current


def lex(text: str) -> tuple[list[Token], set[int]]:
    if len(text) > MAX_EVENT:
        raise ASSNeedsReviewError("event size limit")
    if "\x00" in text or "\n" in text or "\r" in text:
        raise ASSNeedsReviewError("invalid physical event boundary")
    tokens = []
    drawing = False
    group = None
    next_group = 0
    closed = set()
    pos = 0
    budget = [MAX_TAGS]
    while pos < len(text):
        if text[pos] == "{":
            end = text.find("}", pos + 1)
            if end < 0:
                raise ASSNeedsReviewError("unclosed override block")
            raw = text[pos : end + 1]
            new_drawing = _state(raw[1:-1], drawing, budget)
            if new_drawing and not drawing:
                group = next_group
                next_group += 1
            elif drawing and not new_drawing:
                closed.add(group)
            tokens.append(Token(pos, end + 1, raw, "override", new_drawing, group))
            drawing = new_drawing
            if not drawing:
                group = None
            pos = end + 1
        else:
            end = text.find("{", pos)
            if end < 0:
                end = len(text)
            tokens.append(Token(pos, end, text[pos:end], "content", drawing, group))
            pos = end
    return tokens, closed


# Sillage document layer. We deliberately do not serialize through pysubs2:
# its serializer rebuilds headers/styles, rounds times, and discards unknown data.

PLACEHOLDER = re.compile(r"__SILLAGE_[0-9]{4}__")
ASS_TIME = re.compile(r"(?P<h>[0-9]):(?P<m>[0-5][0-9]):(?P<s>[0-5][0-9])\.(?P<f>[0-9]{2})")
SRT_TIME = r"[0-9]{2}:[0-5][0-9]:[0-5][0-9],[0-9]{3}"
SRT_TIMING = re.compile(rf"(?P<start>{SRT_TIME})[ \t]+-->[ \t]+(?P<end>{SRT_TIME})(?:[ \t]+[^\r\n]*)?")
LAYOUT_OR_MARKUP = re.compile(r"\{[^}\r\n]*\}|<[^>\r\n]+>|&(?:#[0-9]+|#x[0-9a-fA-F]+|[a-zA-Z]+);|\\[Nnh]|\r\n|\n|\r|\t")
ANIMATION = re.compile(r"\\(?:t\s*\(|move\s*\(|[kK](?:f|o|t)?\s*[0-9])")
# Four intra-word style boundaries indicate glyph-level typography rather than
# ordinary word/phrase emphasis. Copying those anchors cannot accommodate a
# translation with different letters; retain the source as an unsupported effect.
GLYPH_BOUNDARY = re.compile(r"(?<=[^\W\d_])(?:\{[^{}\r\n]*\})+(?=[^\W\d_])")
GLYPH_WARNING = "Mise en forme ASS lettre par lettre conservée sans traduction."
MAX_FILE = 30_000_000


@dataclass
class _Event:
    id: str
    start: int
    end: int
    text: str
    text_span: tuple[int, int]
    time_spans: tuple[tuple[int, int], tuple[int, int]]
    protected: str = ""
    originals: tuple[str, ...] = ()
    warning: str | None = None
    translatable: bool = False
    comment: bool = False
    glyph_styling: bool = False


def _milliseconds(value: str, format_: str) -> int:
    if format_ in {"ass", "ssa"}:
        match = ASS_TIME.fullmatch(value.strip())
        if not match:
            raise ValueError("Timestamp ASS invalide (H:MM:SS.cc requis).")
        h, m, s, f = (int(match[k]) for k in ("h", "m", "s", "f"))
        return ((h * 60 + m) * 60 + s) * 1000 + f * 10
    h, m, s, f = (int(part) for part in re.split(r"[:,]", value))
    return ((h * 60 + m) * 60 + s) * 1000 + f


def _timestamp(value: int, format_: str) -> str:
    h, value = divmod(value, 3_600_000)
    m, value = divmod(value, 60_000)
    s, ms = divmod(value, 1000)
    return f"{h}:{m:02}:{s:02}.{ms // 10:02}" if format_ in {"ass", "ssa"} else f"{h:02}:{m:02}:{s:02},{ms:03}"


def _physical_lines(text: str):
    position = 0
    for line in text.splitlines(keepends=True):
        yield position, line.rstrip("\r\n")
        position += len(line)


def _protect(text: str) -> tuple[str, tuple[str, ...]]:
    if "__SILLAGE_" in text:
        raise ValueError("Texte contenant un marqueur réservé : vérification requise.")
    originals = []
    def replace(match):
        if len(originals) >= 9999:
            raise ValueError("Trop de balises dans un événement.")
        originals.append(match[0])
        return f"__SILLAGE_{len(originals) - 1:04}__"
    return LAYOUT_OR_MARKUP.sub(replace, text), tuple(originals)


class SubtitleDocument:
    """Validated original text plus exact spans that may be patched.

    segments carry masked, stable text IDs for a provider. cues show the original
    event text and millisecond times, including events retained for review.
    render({}) preserves the decoded document exactly; output encoding is UTF-8
    when published by the caller. Empty translations mean source text retained.
    """

    def __init__(self, text: str, format_: str, encoding: str = "utf-8"):
        self.original = text
        self.format = format_
        self.encoding = encoding
        self.warnings: list[str] = []
        self._events: list[_Event] = []
        if len(text) > MAX_FILE or "\x00" in text:
            raise ValueError("Fichier de sous-titres trop volumineux ou contenant des octets nuls.")
        # splitlines() recognizes additional Unicode separators; their presence
        # is not an unambiguous physical ASS/SRT boundary, so reject explicitly.
        if any(c in text for c in "\v\f\x1c\x1d\x1e\x85\u2028\u2029"):
            raise ValueError("Séparateur de ligne ambigu dans les sous-titres.")
        if format_ in {"ass", "ssa"}:
            self._parse_ass()
        elif format_ == "srt":
            self._parse_srt()
        else:
            raise ValueError("Seuls ASS, SSA et SRT sont pris en charge.")
        if not self._events:
            raise ValueError("Aucun événement de sous-titres valide.")
        self._validate_parser(text)
        for event in self._events:
            self._prepare(event)
        self.segments = [{"id": e.id, "text": e.protected} for e in self._events if e.translatable]
        self.cues = [{"id": e.id, "start": e.start, "end": e.end, "text": e.text,
                      **({"warning": e.warning} if e.warning else {})} for e in self._events]

    @classmethod
    def load(cls, path: str | Path, encoding: str | None = None) -> "SubtitleDocument":
        path = Path(path)
        if path.stat().st_size > MAX_FILE:
            raise ValueError("Fichier de sous-titres trop volumineux (30 Mo maximum).")
        raw = path.read_bytes()
        guessed = False
        if encoding is None:
            encoding = "utf-16" if raw.startswith((b"\xff\xfe", b"\xfe\xff")) else "utf-8"
            try:
                text = raw.decode(encoding, errors="strict")
            except UnicodeDecodeError:
                candidate = from_bytes(raw).best()
                if candidate is None or candidate.chaos > 0.1:
                    raise ValueError("Encodage non reconnu : convertir le fichier en UTF-8.") from None
                encoding = candidate.encoding
                text = str(candidate)
                guessed = True
        else:
            try:
                text = raw.decode(encoding, errors="strict")
            except (UnicodeDecodeError, LookupError):
                raise ValueError("Encodage de sous-titres invalide.") from None
        doc = cls(text, path.suffix.lower().lstrip("."), encoding)
        if guessed:
            doc.warnings.insert(0, f"Encodage {encoding} détecté automatiquement : vérifier les caractères ; export UTF-8.")
        elif encoding.lower().replace("_", "-") not in {"utf-8", "utf-8-sig"}:
            doc.warnings.insert(0, f"Source {encoding} ; export UTF-8 sans perte de caractères décodés.")
        return doc

    def _append(self, text: str, span, time_spans, start: str, end: str, warning=None, *, comment: bool = False):
        start_ms, end_ms = _milliseconds(start, self.format), _milliseconds(end, self.format)
        if not 0 <= start_ms <= end_ms:
            event_id = f"e{len(self._events) + 1:06}"
            line = self.original.count("\n", 0, span[0]) + 1
            raise ValueError(f"{event_id}, ligne {line} : durée de sous-titre invalide dans la piste source "
                             f"(début {start.strip()}, fin {end.strip()}). "
                             "Relancer le modèle ne corrigera pas ces timings ; choisissez une autre piste.")
        if start_ms == end_ms and not (warning or "").startswith("Commentaire"):
            warning = "Durée nulle : événement non affiché conservé sans traduction." + (" " + warning if warning else "")
        event = _Event(f"e{len(self._events) + 1:06}", start_ms, end_ms, text, span, time_spans, warning=warning, comment=comment)
        self._events.append(event)

    def _parse_ass(self):
        section = ""
        fields = None
        expected = ["layer" if self.format == "ass" else "marked", "start", "end", "style", "name", "marginl", "marginr", "marginv", "effect", "text"]
        for offset, line in _physical_lines(self.original):
            stripped = line.lstrip("\ufeff").strip()
            if stripped.startswith("[") and stripped.endswith("]"):
                section = stripped.casefold()
                fields = None
                continue
            if section != "[events]" or not stripped or stripped.startswith(";"):
                continue
            if stripped.startswith("Format:"):
                fields = [x.strip().casefold() for x in stripped[7:].split(",")]
                if fields != expected:
                    raise ValueError("Ordre de colonnes ASS/SSA non standard : vérification requise.")
                continue
            match = re.match(r"(?P<kind>Dialogue|Comment):[ \t]*(?P<data>.*)$", line)
            if not match:
                self.warnings.append("Entrée inconnue dans [Events] conservée sans traduction ; vérifier le fichier.")
                continue
            if fields is None:
                raise ValueError("ASS incomplet : Format manquant dans [Events].")
            data = match["data"]
            parts = data.split(",", len(fields) - 1)
            if len(parts) != len(fields):
                raise ValueError("Événement ASS incomplet : colonnes manquantes.")
            positions = []
            cursor = offset + match.start("data")
            for part in parts:
                positions.append((cursor, cursor + len(part)))
                cursor += len(part) + 1
            warning = "Commentaire conservé sans traduction." if match["kind"] == "Comment" else None
            if not warning and parts[8].strip():
                warning = "Effet animé ou personnalisé conservé sans traduction."
            # Timestamp whitespace is outside the replaceable numeric span.
            times = tuple((positions[i][0] + len(parts[i]) - len(parts[i].lstrip()),
                           positions[i][1] - (len(parts[i]) - len(parts[i].rstrip()))) for i in (1, 2))
            self._append(parts[-1], positions[-1], times, parts[1], parts[2], warning, comment=match["kind"] == "Comment")

    def _parse_srt(self):
        block = []
        for position, line in list(_physical_lines(self.original)) + [(len(self.original), "")]:
            if line.strip():
                block.append((position, line))
                continue
            if not block:
                continue
            if len(block) < 3 or not block[0][1].lstrip("\ufeff").strip().isdigit():
                raise ValueError("Bloc SRT incomplet : numéro, timings et texte requis.")
            match = SRT_TIMING.fullmatch(block[1][1])
            if not match:
                raise ValueError("Ligne de timing SRT invalide.")
            start = block[2][0]
            end = block[-1][0] + len(block[-1][1])
            times = tuple((block[1][0] + match.start(name), block[1][0] + match.end(name)) for name in ("start", "end"))
            self._append(self.original[start:end], (start, end), times, match["start"], match["end"])
            block = []

    def _prepare(self, event: _Event):
        if not event.warning:
            try:
                if len(event.text) > MAX_EVENT:
                    raise ValueError("Événement trop long.")
                if self.format in {"ass", "ssa"}:
                    tokens, _ = lex(event.text)
                    if any(t.kind == "content" and t.drawing for t in tokens):
                        raise ValueError("Dessins vectoriels ou dessin mêlé au dialogue conservés sans traduction.")
                    if ANIMATION.search(event.text):
                        raise ValueError("Karaoké ou animation conservé sans traduction.")
                    if sum(1 for _ in GLYPH_BOUNDARY.finditer(event.text)) >= 4:
                        event.glyph_styling = True
                        raise ValueError(GLYPH_WARNING)
                protected, originals = _protect(event.text)
                visible = PLACEHOLDER.sub("", protected)
                if any(char in visible for char in "{}<>\\") or any(ord(c) < 32 or 0x7f <= ord(c) < 0xa0 for c in visible):
                    raise ValueError("Syntaxe non prise en charge : événement conservé sans traduction.")
                event.protected, event.originals = protected, originals
                event.translatable = any(c.isalpha() for c in visible)
            except ValueError as error:
                event.warning = str(error)
        if event.warning:
            self.warnings.append(f"{event.id} : {event.warning}")

    def _validate_parser(self, text: str, offset_ms: int = 0):
        try:
            with python_warnings.catch_warnings():
                python_warnings.simplefilter("ignore")
                parsed = pysubs2.SSAFile.from_string(text, format_=self.format)
            if len(parsed.events) != len(self._events):
                raise ValueError("event count")
            for parsed_event, original in zip(parsed.events, self._events):
                if (parsed_event.start, parsed_event.end) != (original.start + offset_ms, original.end + offset_ms):
                    raise ValueError("timings")
        except Exception:
            raise ValueError("Sous-titres refusés : la validation pysubs2 détecte une structure ou des timings incohérents.") from None

    def validate_translations(self, translations: Mapping[str, str], require_all: bool = False) -> None:
        if not isinstance(translations, Mapping):
            raise ValueError("Traductions invalides : dictionnaire requis.")
        events = {event.id: event for event in self._events if event.translatable}
        if not set(translations).issubset(events):
            raise ValueError("Traduction contenant un identifiant inattendu ou un événement protégé.")
        if require_all and set(translations) != set(events):
            raise ValueError("Traduction incomplète : des identifiants manquent.")
        for id_, answer in translations.items():
            event = events[id_]
            if not isinstance(answer, str) or not answer.strip() or len(answer) > MAX_EVENT:
                raise ValueError(f"{id_} : traduction vide, invalide ou trop longue.")
            if PLACEHOLDER.findall(answer) != PLACEHOLDER.findall(event.protected):
                raise ValueError(f"{id_} : balises protégées manquantes, dupliquées ou déplacées.")
            prefix = re.match(r"^(?:__SILLAGE_[0-9]{4}__)*", event.protected)[0]
            suffix = re.search(r"(?:__SILLAGE_[0-9]{4}__)*$", event.protected)[0]
            if not answer.startswith(prefix) or not answer.endswith(suffix):
                raise ValueError(f"{id_} : une balise de début ou de fin a été déplacée.")
            visible = PLACEHOLDER.sub("", answer)
            if ("__SILLAGE_" in visible or any(c in visible for c in "{}\\<>\u2028\u2029")
                    or any(ord(c) < 32 or 0x7f <= ord(c) < 0xa0 for c in visible)):
                raise ValueError(f"{id_} : la traduction introduit une balise, une nouvelle ligne ou un caractère interdit.")
            if not any(c.isalpha() for c in visible):
                raise ValueError(f"{id_} : traduction sans texte visible.")

    def resume_translations(self, checkpoints: Mapping[str, str]) -> dict[str, str]:
        """Ignore only known, newly protected glyph effects from older jobs.

        Their old checkpoint rows remain stored. Never render those translations,
        infer replacements, or silently accept unknown/protected IDs of other kinds.
        """
        protected = {event.id for event in self._events if event.glyph_styling}
        active = {key: value for key, value in checkpoints.items() if key not in protected}
        self.validate_translations(active)
        return active

    def timing_warnings(self, duration: float | None = None, offset_ms: int = 0) -> list[str]:
        warnings = []
        for event in self._events:
            if event.start + offset_ms < 0 or event.end + offset_ms < event.start + offset_ms:
                warnings.append(f"{event.id} : timing négatif ou durée invalide.")
            if duration and not event.comment and event.start != event.end and event.end + offset_ms > duration * 1000:
                warnings.append(f"{event.id} : fin après la durée vidéo.")
        return warnings

    def render(self, translations: Mapping[str, str], offset_ms: int = 0) -> str:
        self.validate_translations(translations)
        if isinstance(offset_ms, bool) or not isinstance(offset_ms, int) or abs(offset_ms) > 3_600_000:
            raise ValueError("Décalage invalide : entier en millisecondes, limité à une heure.")
        if self.format in {"ass", "ssa"} and offset_ms % 10:
            raise ValueError("Les timestamps ASS/SSA exigent un décalage multiple de 10 ms ; aucun arrondi implicite.")
        changes = []
        limit = 36_000_000 if self.format in {"ass", "ssa"} else 360_000_000
        for event in self._events:
            if event.id in translations:
                translated = PLACEHOLDER.sub(lambda m: event.originals[int(m[0][10:14])], translations[event.id])
                changes.append((*event.text_span, translated))
            if offset_ms:
                if not 0 <= event.start + offset_ms <= event.end + offset_ms < limit:
                    raise ValueError("Le décalage produit un timestamp négatif ou non représentable.")
                for span, value in zip(event.time_spans, (event.start, event.end)):
                    changes.append((*span, _timestamp(value + offset_ms, self.format)))
        # Build once: repeated full-string copies are quadratic on long files.
        chunks, cursor = [], 0
        for start, end, value in sorted(changes):
            if start < cursor:
                raise ValueError("Chevauchement inattendu des zones de remplacement.")
            chunks.extend((self.original[cursor:start], value))
            cursor = end
        chunks.append(self.original[cursor:])
        rendered = "".join(chunks)
        self._validate_parser(rendered, offset_ms)
        return rendered
