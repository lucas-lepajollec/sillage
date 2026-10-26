import importlib.util
from pathlib import Path
import shutil
import subprocess

import pytest

from sillage import sync
from sillage.subtitles import SubtitleDocument

pytestmark = pytest.mark.skipif(importlib.util.find_spec("ffsubsync") is None, reason="optional sync extra unavailable")


def activity():
    import numpy as np
    rng = np.random.default_rng(786)
    source = np.zeros(180 * 50)
    cursor = 500
    while cursor < len(source) - 500:
        duration = int(rng.integers(30, 140))
        source[cursor:cursor + duration] = 1
        cursor += duration + int(rng.integers(25, 110))
    return source


def shifted(source, offset):
    import numpy as np
    output = np.zeros_like(source)
    if offset > 0:
        output[offset:] = source[:-offset]
    elif offset < 0:
        output[:offset] = source[-offset:]
    else:
        output[:] = source
    return output


@pytest.mark.parametrize("samples", [0, 75, -60])
def test_ffsubsync_engine_measures_signed_global_offset(samples):
    source = activity()
    offset, correlation = sync._estimate(shifted(source, samples), source)
    assert offset == samples * sync.SAMPLE_MS
    assert offset % 10 == 0  # exactly representable in ASS, without rounding
    assert correlation > 0.99


def test_noisy_but_consistent_activity_can_produce_reviewable_proposal():
    import numpy as np
    source = activity()
    audio = shifted(source, 75)
    rng = np.random.default_rng(919)
    # Different false positives/negatives, maintaining speech-envelope agreement.
    noise = rng.random(len(audio)) < 0.06
    audio[noise] = 1 - audio[noise]
    offset, correlation = sync._estimate(audio, source)
    assert abs(offset - 1500) <= 20
    assert 0.6 < correlation < 1


@pytest.mark.parametrize("kind", ["silence", "continuous", "random", "drift", "limit", "short"])
def test_uncertain_sync_never_becomes_a_correction(kind):
    import numpy as np
    source = activity()
    if kind == "silence":
        audio = np.zeros_like(source)
    elif kind == "continuous":
        audio = np.ones_like(source)
    elif kind == "random":
        audio = np.random.default_rng(3).random(len(source)) > 0.5
    elif kind == "drift":
        audio = np.concatenate([shifted(source[:3000], 75), shifted(source[3000:6000], -75), shifted(source[6000:], 120)])
    elif kind == "limit":
        audio = shifted(source, sync.MAX_OFFSET_MS // sync.SAMPLE_MS)
    else:
        audio, source = source[:2000], source[:2000]
    with pytest.raises(ValueError, match="Timings source conservés"):
        sync._estimate(audio, source)


def make_document(tmp_path: Path):
    source = activity()
    edges = []
    begin = None
    for index, value in enumerate(source):
        if value and begin is None:
            begin = index
        if not value and begin is not None:
            edges.append((begin * 20, index * 20))
            begin = None
    def stamp(ms):
        seconds, ms = divmod(ms, 1000)
        minutes, seconds = divmod(seconds, 60)
        return f"00:{minutes:02}:{seconds:02},{ms:03}"
    path = tmp_path / "dialogues anglais.srt"
    path.write_text("\n\n".join(f"{i}\n{stamp(a)} --> {stamp(b)}\nDialogue number {i}." for i, (a, b) in enumerate(edges, 1)) + "\n")
    video = tmp_path / "épisode ' spécial.mkv"
    video.touch()
    return path, video, source


def test_proposal_returns_comparison_and_leaves_source_files_untouched(tmp_path, monkeypatch):
    path, video, source = make_document(tmp_path)
    before = path.read_bytes()
    monkeypatch.setattr(sync, "_audio_activity", lambda p, d: shifted(source, 75))
    proposal = sync.propose_sync(video, path, 180)
    assert proposal["offset_ms"] == 1500
    assert proposal["confidence"] >= 0.9
    assert any("première piste audio" in warning for warning in proposal["warnings"])
    assert any("pas une probabilité" in warning for warning in proposal["warnings"])
    assert path.read_bytes() == before
    assert video.read_bytes() == b""
    doc = SubtitleDocument.load(path)
    preview = SubtitleDocument(doc.render({}, proposal["offset_ms"]), "srt")
    assert preview.cues[0]["start"] - doc.cues[0]["start"] == 1500


def test_guard_rejects_mismatched_audio_duration(tmp_path, monkeypatch):
    path, video, source = make_document(tmp_path)
    monkeypatch.setattr(sync, "_audio_activity", lambda p, d: source[:3000])
    with pytest.raises(ValueError, match="Durée audio différente"):
        sync.propose_sync(video, path, 180)


@pytest.mark.parametrize("duration", [0, 30, float("nan"), float("inf"), 14_401])
def test_bounded_duration_rejects_unreasonable_media(tmp_path, duration):
    path, video, _ = make_document(tmp_path)
    with pytest.raises(ValueError, match="Durée hors plage"):
        sync.propose_sync(video, path, duration)


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="requires FFmpeg")
def test_real_ffmpeg_and_vad_never_self_verify_embedded_subtitle_over_silence(tmp_path):
    path, video, _ = make_document(tmp_path)
    subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-f", "lavfi", "-i", "anullsrc=r=16000:cl=mono",
                    "-i", str(path), "-t", "180", "-map", "0:a", "-map", "1:s", "-c:a", "flac", "-c:s", "srt", "-y", str(video)],
                   check=True, capture_output=True, timeout=30)
    before = path.read_bytes()
    with pytest.raises(ValueError, match="Activité audio insuffisante"):
        sync.propose_sync(video, path, 180)
    assert path.read_bytes() == before


def test_audio_subprocess_uses_selected_audio_stream_and_no_shell(tmp_path, monkeypatch):
    video = tmp_path / "épisode;echo unintended.mkv"
    observed = []
    def run(args, **kwargs):
        observed.append((args, kwargs))
        Path(args[-1]).write_bytes(b"\x00" * 640 * 100)
    monkeypatch.setattr(sync.shutil, "which", lambda name: "/usr/bin/ffmpeg")
    monkeypatch.setattr(sync.subprocess, "run", run)
    audio = sync._audio_activity(video, 2)
    assert len(audio) == 100 and not audio.any()
    args, kwargs = observed[0]
    assert args[args.index("-map") + 1] == "0:a:0"
    assert "-sn" in args and "-vn" in args and "-dn" in args
    assert str(video) in args and not kwargs.get("shell")
    assert 0 < kwargs["timeout"] <= 600
    assert not Path(args[-1]).exists()  # PCM deleted on completion
