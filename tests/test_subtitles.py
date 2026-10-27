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


@pytest.mark.parametrize('format_', ['ass', 'ssa', 'srt'])
def test_zero_duration_is_preserved_exactly_and_never_sent_to_translation(format_):
    if format_ == 'srt':
        text = '1\n00:00:01,000 --> 00:00:01,000\nInvisible\n\n2\n00:00:02,000 --> 00:00:03,000\nHello\n'
    else:
        field = 'Layer' if format_ == 'ass' else 'Marked'
        text = ('[Events]\nFormat: '+field+', Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n'
                'Dialogue: 0,0:00:01.00,0:00:01.00,Default,,0,0,0,,Invisible\n'
                'Dialogue: 0,0:00:02.00,0:00:03.00,Default,,0,0,0,,Hello\n')
    doc = SubtitleDocument(text, format_)
    assert [cue['id'] for cue in doc.segments] == ['e000002']
    assert any('Durée nulle' in warning for warning in doc.warnings)
    assert doc.render({}) == text
    rendered = doc.render({'e000002': 'Bonjour'})
    assert rendered == text.replace('Hello', 'Bonjour')
    assert doc.timing_warnings(6) == []
    with pytest.raises(ValueError, match='protégé'):
        doc.validate_translations({'e000001': 'Changed invisible text'})


def test_reversed_source_timings_explain_why_model_retries_will_not_help():
    with pytest.raises(ValueError, match=r'e000001, ligne 3.*piste source.*00:00:03,000.*00:00:02,000.*Relancer'):
        SubtitleDocument('1\n00:00:03,000 --> 00:00:02,000\nHello\n', 'srt')


def test_letter_level_ass_typography_is_retained_without_a_translation_request():
    from conftest import ASS
    gradient = r'{\fad(120,120)\blur2}' + ''.join(r'{*\3c&H%06X&}' % (0x123400 + index) + char for index, char in enumerate('Observatory doors open'))
    line = 'Dialogue: 0,0:00:01.00,0:00:02.00,Default,,0,0,0,,' + gradient + '\n'
    doc = SubtitleDocument(ASS + line, 'ass')
    cue = doc.cues[-1]
    assert 'lettre par lettre' in cue['warning']
    assert cue['id'] not in {segment['id'] for segment in doc.segments}
    assert doc.render({}) == doc.original
    assert line in doc.render({segment['id']: segment['text'] for segment in doc.segments})
    with pytest.raises(ValueError, match='protégé'):
        doc.render({cue['id']: 'Do not rewrite this effect'})


def test_normal_phrase_emphasis_and_positioned_signs_remain_translatable():
    from conftest import ASS
    text = r'{\an7\pos(15,20)\fad(100,100)}Open {\i1}the northern{\i0} door.\NPlease.'
    doc = SubtitleDocument(ASS + 'Dialogue: 0,0:00:01.00,0:00:02.00,Default,,0,0,0,,' + text + '\n', 'ass')
    assert doc.cues[-1]['id'] in {segment['id'] for segment in doc.segments}
    assert not doc.cues[-1].get('warning')


def test_only_newly_protected_typography_checkpoints_are_filtered_without_deleting_them():
    from conftest import ASS
    gradient = ''.join(r'{\c&H%06X&}' % (0x123400 + index) + char for index, char in enumerate('Fictional lettering'))
    doc = SubtitleDocument(ASS + 'Dialogue: 0,0:00:01.00,0:00:02.00,Default,,0,0,0,,' + gradient + '\n', 'ass')
    source = {segment['id']: segment['text'] for segment in doc.segments}
    legacy = source | {doc.cues[-1]['id']: 'Old checkpoint remains archived'}
    assert doc.resume_translations(legacy) == source
    assert len(legacy) == len(source) + 1
    with pytest.raises(ValueError, match='identifiant'):
        doc.resume_translations(legacy | {'e999999': 'Unknown cue must still fail'})
    doc = rich()
    protected = next(cue for cue in doc.cues if 'Dessins' in cue.get('warning', ''))
    with pytest.raises(ValueError, match='protégé'):
        doc.resume_translations({protected['id']: 'Not an older typography checkpoint'})


def test_non_rendered_ass_comments_may_extend_past_video_but_visible_events_still_fail():
    from conftest import ASS
    comment = 'Comment: 0,0:00:05.00,0:00:08.00,Default,,0,0,0,,Fictional editor note\n'
    doc = SubtitleDocument(ASS + comment, 'ass')
    assert not doc.timing_warnings(6)
    assert comment in doc.render({})
    visible = SubtitleDocument(ASS + comment.replace('Comment:', 'Dialogue:'), 'ass')
    assert any('fin après la durée vidéo' in warning for warning in visible.timing_warnings(6))
    drawing = SubtitleDocument(ASS + comment.replace('Comment:', 'Dialogue:').replace('Fictional editor note', r'{\p1}m 0 0 l 1 1{\p0}'), 'ass')
    assert any('fin après la durée vidéo' in warning for warning in drawing.timing_warnings(6))
    assert doc.timing_warnings(6, offset_ms=-6000)  # Comment offsets still require valid timestamps.
