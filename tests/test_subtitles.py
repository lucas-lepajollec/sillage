# Drawing-state regression examples are adapted from Sublarr (GPL-3.0);
# see docs/research-subtitles.md for the audited commit and source paths.
from pathlib import Path

import pysubs2
import pytest

from sillage.subtitles import SubtitleDocument, lex, ASSNeedsReviewError

FIXTURES = Path(__file__).parent / "fixtures"


def rich():
    return SubtitleDocument.load(FIXTURES / "fansub-rich.ass")


def translate(document):
    # A deterministic fixture replacement, never exposed as a real provider.
    return {s["id"]: s["text"].replace("door", "porte").replace("The ", "La ").replace("Yes", "Oui")
            .replace("OBSERVATORY", "OBSERVATOIRE").replace("STAFF ONLY", "PERSONNEL UNIQUEMENT")
            .replace("I brought tea", "J’ai apporté du thé").replace("Is that right?", "C’est bien ça ?")
            for s in document.segments}


def test_realistic_ass_preserves_structure_and_source_timestamps():
    doc = rich()
    rendered = doc.render(translate(doc))
    before, after = pysubs2.SSAFile.from_string(doc.original, format_="ass"), pysubs2.SSAFile.from_string(rendered, format_="ass")
    assert len(before.events) == len(after.events) == 11
    assert before.styles == after.styles
    assert [(e.start, e.end, e.style, e.layer, e.name, e.effect, e.is_comment) for e in before] == [
        (e.start, e.end, e.style, e.layer, e.name, e.effect, e.is_comment) for e in after]
    assert doc.original.split("[Events]")[0] == rendered.split("[Events]")[0]
    assert doc.original.split("[Unknown Extension]")[1] == rendered.split("[Unknown Extension]")[1]
    for original, result in zip(before, after):
        assert [t.raw for t in lex(original.text)[0] if t.kind == "override"] == [
            t.raw for t in lex(result.text)[0] if t.kind == "override"]
    assert "OBSERVATOIRE" in rendered  # positioned signs translate rather than disappear
    assert r"\N" in rendered and r"\h" in rendered
    assert len(doc.segments) == 5
    assert len(doc.warnings) == 6  # comment + drawing + mixed drawing + karaoke + movement + effect


def test_noop_exactly_preserves_all_decoded_characters():
    for name in ("fansub-rich.ass", "upstream-aegisub-images.ass"):
        doc = SubtitleDocument.load(FIXTURES / name)
        assert doc.render({}) == (FIXTURES / name).read_bytes().decode("utf-8")
    doc = rich()
    assert doc.render({s["id"]: s["text"] for s in doc.segments}) == doc.original


def test_unsafe_events_are_retained_visible_and_excluded_from_translation():
    doc = rich()
    protected = {cue["id"] for cue in doc.cues if cue.get("warning")}
    assert {s["id"] for s in doc.segments}.isdisjoint(protected)
    assert any("Karaoké" in warning for warning in doc.warnings)
    assert any("Dessins" in warning for warning in doc.warnings)
    assert all(cue["text"] in doc.render(translate(doc)) for cue in doc.cues if cue.get("warning"))
    with pytest.raises(ValueError, match="protégé"):
        doc.render({"e000005": "Wrongly translated geometry"})


@pytest.mark.parametrize("mutation", [
    lambda s: s.replace("__SILLAGE_0000__", ""),
    lambda s: s + "__SILLAGE_0000__",
    lambda s: s.replace("__SILLAGE_0000__", "__SILLAGE_9999__"),
    lambda s: s + r"{\p1}",
    lambda s: s + r"\Nnew break",
    lambda s: s + "\ninjected event",
    lambda s: s + "<b>new tag</b>",
    lambda s: s + "\x1cphysical separator",
    lambda s: s + "\x85physical separator",
    lambda s: "intro " + s,
    lambda s: "",
    lambda s: None,
])
def test_model_output_cannot_change_structure_or_anchored_tags(mutation):
    doc = rich()
    segment = doc.segments[0]
    with pytest.raises(ValueError):
        doc.render({segment["id"]: mutation(segment["text"])})


def test_id_validation_and_partial_checkpoints():
    doc = rich()
    first = doc.segments[0]
    doc.validate_translations({first["id"]: first["text"]})
    with pytest.raises(ValueError, match="incomplète"):
        doc.validate_translations({first["id"]: first["text"]}, require_all=True)
    with pytest.raises(ValueError, match="identifiant"):
        doc.render({"unknown": "Bonjour"})
    doc.validate_translations(translate(doc), require_all=True)


def test_offset_changes_times_only_and_rejects_implicit_rounding():
    doc = rich()
    rendered = doc.render({}, offset_ms=120)
    shifted = SubtitleDocument(rendered, "ass")
    assert [(c["start"] + 120, c["end"] + 120, c["text"]) for c in doc.cues] == [
        (c["start"], c["end"], c["text"]) for c in shifted.cues]
    assert doc.original.split("[Events]")[0] == rendered.split("[Events]")[0]
    with pytest.raises(ValueError, match="multiple de 10"):
        doc.render({}, 1)
    with pytest.raises(ValueError, match="négatif"):
        doc.render({}, -1000)
    assert not doc.timing_warnings(21)
    assert doc.timing_warnings(10)


def test_srt_preserves_numbering_coordinates_markup_breaks_bom_and_crlf(tmp_path):
    text = "\ufeff42\r\n00:00:01,020 --> 00:00:02,500 X1:1 X2:2 Y1:3 Y2:4\r\n<i>Hello</i> &amp; welcome.\r\nSecond line.\r\n\r\n99\r\n00:00:02,100 --> 00:00:04,000\r\nOverlap is intentional.\r\n"
    path = tmp_path / "source.srt"
    path.write_bytes(text.encode())
    doc = SubtitleDocument.load(path)
    assert doc.render({}) == text
    translated = {s["id"]: s["text"].replace("Hello", "Bonjour").replace("Second line", "Deuxième ligne") for s in doc.segments}
    output = doc.render(translated)
    assert output == text.replace("Hello", "Bonjour").replace("Second line", "Deuxième ligne")
    shifted = doc.render({}, 17)
    assert "00:00:01,037 --> 00:00:02,517 X1:1" in shifted
    assert shifted.startswith("\ufeff42\r\n")


@pytest.mark.parametrize("encoding", ["utf-8", "utf-16", "cp1252"])
def test_unicode_and_explicit_encodings(tmp_path, encoding):
    text = "1\n00:00:01,000 --> 00:00:02,000\nÉloi prépare le café — bientôt.\n"
    path = tmp_path / "épisode.srt"
    path.write_bytes(text.encode(encoding))
    doc = SubtitleDocument.load(path, encoding=encoding)
    assert doc.render({}) == text
    assert doc.encoding == encoding


def test_utf16_bom_detected_and_legacy_guess_disclosed(tmp_path):
    text = "1\n00:00:01,000 --> 00:00:02,000\n東京へようこそ。\n"
    path = tmp_path / "source.srt"
    path.write_bytes(text.encode("utf-16"))
    assert SubtitleDocument.load(path).render({}) == text
    text = text.replace("東京へようこそ。", "Éloi prépare le café — bientôt.")
    path.write_bytes(text.encode("cp1252"))
    assert any("détecté automatiquement" in w for w in SubtitleDocument.load(path).warnings)


@pytest.mark.parametrize("text,format_", [
    ("[Script Info]\nScriptType: v4.00+\n[Events]\nDialogue: 0,0:00:01.00,0:00:02.00,Default,,0,0,0,,Hi", "ass"),
    ("1\n00:00:03,000 --> 00:00:02,000\nHi\n", "srt"),
    ("1\n-00:00:01,000 --> 00:00:02,000\nHi\n", "srt"),
    ("1\n00:00:01,000 --> 00:00:01,000\nHi\n", "srt"),
    ("1\n00:00:01,000 --> 00:00:02,000\n", "srt"),
    ("not a subtitle", "ass"),
    ("1\n00:00:01,000 --> 00:00:02,000\nHi\x00\n", "srt"),
])
def test_invalid_and_incomplete_files_fail_closed(text, format_):
    with pytest.raises(ValueError):
        SubtitleDocument(text, format_)


def test_malformed_override_is_preserved_with_review_warning():
    doc = rich()
    modified = SubtitleDocument(doc.original.replace("I brought tea, a map, and two cups.", "I brought tea{unclosed"), "ass")
    assert any("unclosed override" in w for w in modified.warnings)
    assert "e000009" not in {s["id"] for s in modified.segments}
    assert modified.render({}) == modified.original


def test_ssa_marked_field_is_preserved():
    text = "[Script Info]\nScriptType: v4.00\n[Events]\nFormat: Marked, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\nDialogue: Marked=0,0:00:01.20,0:00:03.00,Default,Éloi,10,20,30,,Hello.\n"
    doc = SubtitleDocument(text, "ssa")
    assert doc.render({"e000001": "Bonjour."}) == text.replace("Hello.", "Bonjour.")


@pytest.mark.parametrize("text", ["x" * 131073, "{unclosed", "a\x00b", "a\rb", "a\nb", "{" + r"\p1" * 4097 + "}"])
def test_bounded_lexer_rejects_ambiguous_or_excessive_events(text):
    with pytest.raises(ASSNeedsReviewError):
        lex(text)


@pytest.mark.parametrize("text,drawing", [
    (r"{\p1(0)}Good morning.{\p0}", False),
    (r"{\t(0,1000,2,3,\p1)}Good morning.{\p0}", False),
    (r"{\t(0,1000,2,\p1)}m 0 0{\p0}", True),
    (r"{\zzz(\p1)}Good morning.{\p0}", False),
    (r"{\p1}m 0 0{\p0}Good morning.", True),
    (r"{\pos(10,20)\pbo3}Good morning.", False),
])
def test_libass_drawing_argument_regressions(text, drawing):
    # Cases informed by Sublarr's independently renderer-checked regressions;
    # expectations are drawing-state only, not full fansub conformance.
    assert any(t.kind == "content" and t.drawing for t in lex(text)[0]) is drawing
