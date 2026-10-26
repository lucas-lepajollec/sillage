import hashlib
import json
import os
from unittest.mock import patch

import pytest
from sillage.media import MediaLibrary


def test_real_srt_and_ass_inspection_and_extraction(media_factory, tmp_path):
    for ass in [False, True]:
        video = media_factory(ass=ass)
        library = MediaLibrary([video.parent])
        before = hashlib.sha256(video.read_bytes()).hexdigest()
        info = library.inspect(video)
        assert info["status"] == "ready"
        assert info["duration"] == 6
        assert info["tracks"][0]["format"] == ("ass" if ass else "srt")
        work = tmp_path / str(ass)
        work.mkdir()
        source, _ = library.extract(video, info["tracks"][0]["id"], work)
        assert "Hello" in source.read_text()
        assert hashlib.sha256(video.read_bytes()).hexdigest() == before


def test_multiple_english_and_sdh(media_factory):
    video = media_factory(multiple=True)
    info = MediaLibrary([video.parent]).inspect(video)
    assert len(info["tracks"]) == 2
    assert info["tracks"][1]["sdh"] is True
    assert len({t["id"] for t in info["tracks"]}) == 2


def test_no_english_and_graphic_tracks_are_not_selectable(video):
    probe = {"format": {"duration": "6"}, "streams": [
        {"index": 2, "codec_type": "subtitle", "codec_name": "hdmv_pgs_subtitle", "tags": {"language": "eng"}},
        {"index": 3, "codec_type": "subtitle", "codec_name": "dvd_subtitle", "tags": {"language": "jpn"}}]}
    with patch("sillage.media.run", return_value=json.dumps(probe)):
        info = MediaLibrary([video.parent]).inspect(video)
    assert info["status"] == "unsupported"
    assert not any(t["supported"] for t in info["tracks"])


def test_external_sources_and_french_detection(video):
    french = video.with_suffix(".fr.ass")
    french.write_text("test")
    english = video.with_suffix(".en.srt")
    english.write_text("1\n00:00:00,000 --> 00:00:01,000\nHello\n")
    info = MediaLibrary([video.parent]).inspect(video)
    assert info["has_french"]
    assert info["status"] == "existing"
    assert any(t["external"] and t["language"] == "en" for t in info["tracks"])


def test_recursive_scan_and_unicode(media_factory, tmp_path):
    video = media_factory("Épisode 星 ; '$.mkv")
    root = tmp_path / "media"
    season = root / "Saison 01"
    season.mkdir(parents=True)
    import shutil
    target = season / video.name
    shutil.copyfile(video, target)
    library = MediaLibrary([root])
    assert library.scan(str(root), False)["episodes"] == []
    assert library.scan(str(root), True)["episodes"][0]["name"] == video.name
    assert library.browse(str(root))["directories"][0]["name"] == "Saison 01"
    assert library.browse(str(root))["parent"] is None


def test_browse_traversal_and_symlink_escape(video, tmp_path):
    library = MediaLibrary([video.parent])
    outside = tmp_path / "private"
    outside.mkdir()
    (video.parent / "escape").symlink_to(outside, target_is_directory=True)
    for path in ["../", str(video.parent / ".."), str(outside), str(video.parent / "escape")]:
        with pytest.raises((ValueError, FileNotFoundError)):
            library.resolve(path)
    assert not library.browse(str(video.parent))["directories"]


def test_atomic_export_does_not_replace_any_file(video):
    library = MediaLibrary([video.parent])
    output = library.publish(video, ".fr.srt", "Bonjour")
    assert output.read_text() == "Bonjour"
    with pytest.raises(FileExistsError):
        library.publish(video, ".fr.srt", "Écrasement")
    assert output.read_text() == "Bonjour"
    assert not list(video.parent.glob(".sillage-*.tmp"))


def test_atomic_export_refuses_symlink(video, tmp_path):
    victim = tmp_path / "victim"
    victim.write_text("preserved")
    video.with_suffix(".fr.srt").symlink_to(victim)
    with pytest.raises(FileExistsError):
        MediaLibrary([video.parent]).publish(video, ".fr.srt", "bad")
    assert victim.read_text() == "preserved"


def test_export_permissions(video):
    if os.getuid() == 0:
        pytest.skip("Permission semantics require non-root process")
    folder = video.parent
    folder.chmod(0o555)
    try:
        with pytest.raises(PermissionError):
            MediaLibrary([folder]).publish(video, ".fr.srt", "Bonjour")
    finally:
        folder.chmod(0o755)


def test_no_shell_interpolation(video, tmp_path):
    library = MediaLibrary([video.parent])
    with patch("sillage.media.subprocess.run") as runner:
        runner.return_value.returncode = 0
        runner.return_value.stdout = b'{"format":{"duration":"6"},"streams":[]}'
        library.inspect(video)
        args, kwargs = runner.call_args
        assert isinstance(args[0], list)
        assert not kwargs.get("shell", False)


def test_invalid_media_reported_without_stderr_leak(tmp_path):
    (tmp_path / "bad.mkv").write_text("not a video")
    result = MediaLibrary([tmp_path]).scan(str(tmp_path))
    assert result["episodes"] == []
    assert len(result["errors"]) == 1


def test_missing_root_yields_clear_failure(tmp_path):
    with pytest.raises(FileNotFoundError):
        MediaLibrary([tmp_path / "missing"]).browse()


def test_french_forced_or_signs_only_does_not_hide_full_dialogue(video):
    for title, forced in [("French signs only", False), ("French", True)]:
        probe = {"format": {"duration": "6"}, "streams": [
            {"index": 2, "codec_type": "subtitle", "codec_name": "subrip", "tags": {"language": "eng"}},
            {"index": 3, "codec_type": "subtitle", "codec_name": "ass", "tags": {"language": "fra", "title": title}, "disposition": {"forced": forced}}]}
        with patch("sillage.media.run", return_value=json.dumps(probe)):
            info = MediaLibrary([video.parent]).inspect(video)
        assert not info["has_french"]
        assert info["has_french_partial"]
        assert info["status"] == "ready"


def test_actual_mkv_without_subtitles(media_factory):
    video = media_factory(no_subs=True)
    result = MediaLibrary([video.parent]).inspect(video)
    assert result["tracks"] == []
    assert result["status"] == "unsupported"
