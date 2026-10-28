import subprocess
import pytest

SRT = "1\n00:00:00,500 --> 00:00:02,000\nHello world!\n\n2\n00:00:02,500 --> 00:00:04,500\nGoodbye.\n\n"
ASS = r"""[Script Info]
Title: Sillage synthetic end-to-end fixture
ScriptType: v4.00+
PlayResX: 1280
PlayResY: 720
[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Arial,40,&H00FFFFFF,&H000000FF,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,2,0,2,10,10,10,1
Style: Sign,Arial,30,&H00FFFFFF,&H000000FF,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,1,0,7,0,0,0,1
[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
Dialogue: 0,0:00:00.50,0:00:02.00,Default,,0,0,0,,{\i1}Hello{\i0} world!\NGoodbye.
Dialogue: 1,0:00:02.50,0:00:04.50,Sign,,0,0,0,,{\pos(100,120)\an7}Station
"""

@pytest.fixture(scope="session")
def media_factory(tmp_path_factory):
    base = tmp_path_factory.mktemp("generated-media")
    def create(name="Episode 01.mkv", *, ass=False, actor_alias=False, multiple=False, no_subs=False):
        folder = base / str(len(list(base.iterdir())))
        folder.mkdir()
        srt = folder / "source.en.srt"
        srt.write_text(SRT, encoding="utf-8")
        ass_file = folder / "source.en.ass"
        ass_file.write_text(ASS.replace("Style, Name, MarginL", "Style, Actor, MarginL") if actor_alias else ASS, encoding="utf-8")
        output = folder / name
        args = ["ffmpeg", "-nostdin", "-v", "error", "-f", "lavfi", "-i", "color=size=64x36:rate=2:duration=6",
                "-f", "lavfi", "-i", "anullsrc=r=16000:cl=mono"]
        if not no_subs:
            args += ["-i", str(ass_file if ass else srt)]
            if multiple:
                args += ["-i", str(srt)]
        args += ["-map", "0:v", "-map", "1:a"]
        if not no_subs:
            args += ["-map", "2:0"]
            if multiple:
                args += ["-map", "3:0"]
        args += ["-t", "6", "-c:v", "ffv1", "-c:a", "pcm_s16le", "-c:s", "copy"]
        if not no_subs:
            args += ["-metadata:s:s:0", "language=eng", "-metadata:s:s:0", "title=English full dialogue"]
            if multiple:
                args += ["-metadata:s:s:1", "language=eng", "-metadata:s:s:1", "title=English SDH", "-disposition:s:1", "hearing_impaired"]
        args += [str(output)]
        subprocess.run(args, check=True, capture_output=True)
        srt.unlink()
        ass_file.unlink()
        return output
    return create

@pytest.fixture
def video(media_factory):
    return media_factory()
