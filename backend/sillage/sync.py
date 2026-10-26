"""Conservative audio-only global-offset proposals; never writes a subtitle.

Reuses ffsubsync's MIT-licensed FFTAligner with explicit audio extraction and
WebRTC VAD. No subtitle stream, rescaling, splitting or model transcript can
become the reference. Callers must validate media paths against mounted roots
before calling this module, and obtain user acceptance before applying offsets.
"""
from __future__ import annotations

import math
from pathlib import Path
import shutil
import subprocess
import tempfile

from .subtitles import SubtitleDocument

SAMPLE_MS = 20
MAX_OFFSET_MS = 10_000
MAX_DURATION_SECONDS = 14_400


def _reject(reason: str):
    raise ValueError(f"Synchronisation automatique incertaine : {reason} Timings source conservés.")


def _audio_activity(video_path: Path, duration: float):
    import numpy as np
    import webrtcvad

    if not shutil.which("ffmpeg"):
        _reject("FFmpeg indisponible.")
    detector = webrtcvad.Vad(2)
    frame_bytes = 16_000 * SAMPLE_MS // 1000 * 2
    with tempfile.TemporaryDirectory(prefix="sillage-sync-") as work:
        raw_path = Path(work) / "audio.pcm"
        try:
            subprocess.run(
                ["ffmpeg", "-nostdin", "-v", "error", "-i", str(video_path),
                 "-map", "0:a:0", "-vn", "-sn", "-dn", "-t", str(duration),
                 "-ac", "1", "-ar", "16000", "-f", "s16le", "-y", str(raw_path)],
                check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                timeout=min(600, max(60, duration / 4)),
            )
        except (OSError, subprocess.SubprocessError):
            _reject("Extraction de la première piste audio impossible ou délai dépassé.")
        values = []
        with raw_path.open("rb") as audio:
            while chunk := audio.read(frame_bytes):
                if len(chunk) == frame_bytes:
                    values.append(detector.is_speech(chunk, 16_000))
        return np.asarray(values, dtype=np.float64)


def _subtitle_activity(document: SubtitleDocument, length: int):
    import numpy as np
    import re

    signal = np.zeros(length, dtype=np.float64)
    translatable = {segment["id"] for segment in document.segments}
    count = 0
    for cue in document.cues:
        if cue["id"] not in translatable or re.search(r"\\(?:pos|org|i?clip)\s*\(", cue["text"]):
            continue
        begin = max(0, math.floor(cue["start"] / SAMPLE_MS))
        end = min(length, math.ceil(cue["end"] / SAMPLE_MS))
        if begin < end:
            signal[begin:end] = 1.0
            count += 1
    return signal, count


def _correlation(reference, subtitles, offset: int) -> float:
    import numpy as np

    n = min(len(reference), len(subtitles))
    if abs(offset) >= n:
        return 0.0
    if offset >= 0:
        a, b = reference[offset:n], subtitles[:n-offset]
    else:
        a, b = reference[:n+offset], subtitles[-offset:n]
    a, b = a - a.mean(), b - b.mean()
    denominator = math.sqrt(float(np.sum(a * a) * np.sum(b * b)))
    return float(np.sum(a * b) / denominator) if denominator > 1e-10 else 0.0


def _estimate(reference, subtitles) -> tuple[int, float]:
    """Measured correlation plus ffsubsync offset; guard every separate third."""
    import numpy as np
    from ffsubsync.aligners import FFTAligner

    length = min(len(reference), len(subtitles))
    reference, subtitles = reference[:length], subtitles[:length]
    if length < 120_000 // SAMPLE_MS:
        _reject("Au moins deux minutes d'audio sont nécessaires.")
    for values, name in ((reference, "audio"), (subtitles, "sous-titres")):
        ratio = float(np.mean(values))
        if not 0.03 <= ratio <= 0.90 or float(np.sum(values)) * SAMPLE_MS < 20_000:
            _reject(f"Activité {name} insuffisante ou presque continue.")
    max_shift = MAX_OFFSET_MS // SAMPLE_MS
    candidate = int(FFTAligner(max_offset_samples=max_shift).fit_transform(reference, subtitles))
    if abs(candidate) >= max_shift - 2:
        _reject("Meilleur décalage situé à la limite de recherche (±10 s).")
    score = _correlation(reference, subtitles, candidate)
    if score < 0.30:
        _reject("Corrélation audio/texte trop faible.")
    # Alternatives at 250 ms steps away from the candidate must be weaker.
    # Confidence is a correlation coefficient, never a probability of accuracy.
    alternatives = [_correlation(reference, subtitles, offset)
                    for offset in range(-max_shift, max_shift + 1, 12)
                    if abs(offset - candidate) >= 500 // SAMPLE_MS]
    if not alternatives or score - max(alternatives) < 0.025:
        _reject("Plusieurs décalages concurrents : pic ambigu.")
    if abs(candidate) * SAMPLE_MS > 200 and score - _correlation(reference, subtitles, 0) < 0.03:
        _reject("Amélioration trop faible par rapport aux timings source.")
    third = length // 3
    for index in range(3):
        start, end = index * third, (index + 1) * third if index < 2 else length
        a, b = reference[start:end], subtitles[start:end]
        if (np.sum(a) * SAMPLE_MS < 5000 or np.sum(b) * SAMPLE_MS < 5000
                or np.std(a) < 0.05 or np.std(b) < 0.05):
            _reject("Dialogue insuffisant dans une des trois fenêtres de contrôle.")
        local = int(FFTAligner(max_offset_samples=max_shift).fit_transform(a, b))
        if abs(local - candidate) * SAMPLE_MS > 300 or _correlation(a, b, candidate) < 0.20:
            _reject("Les fenêtres de contrôle divergent (dérive, montage ou mauvais audio possible).")
    return candidate * SAMPLE_MS, min(1.0, max(0.0, score))


def propose_sync(video_path: str | Path, subtitle_path: str | Path, duration: float) -> dict:
    """Return a reviewable global offset; uncertain results raise ValueError.

    Positive offset delays every source event. Resolution is 20 ms, including
    ASS (centisecond timestamps). A user must accept before render applies it.
    The first audio track is used; audio language/track selection remains manual
    outside V1, and this routine refuses uncertainty rather than guessing.
    """
    try:
        import ffsubsync.aligners  # noqa: F401
        import numpy  # noqa: F401
        import webrtcvad  # noqa: F401
    except ImportError:
        _reject("Module optionnel manquant ; installer Sillage avec l'extra sync.")
    if not isinstance(duration, (float, int)) or not math.isfinite(duration) or not 120 <= duration <= MAX_DURATION_SECONDS:
        _reject("Durée hors plage prise en charge (2 min à 4 h).")
    video_path, subtitle_path = Path(video_path), Path(subtitle_path)
    if not video_path.is_absolute() or not video_path.is_file() or not subtitle_path.is_file():
        _reject("Fichier audio ou sous-titre inaccessible.")
    document = SubtitleDocument.load(subtitle_path)
    if document.timing_warnings(duration):
        _reject("Les sous-titres source débordent de la durée vidéo.")
    audio = _audio_activity(video_path, float(duration))
    expected = duration * 1000 / SAMPLE_MS
    if not 0.95 <= len(audio) / expected <= 1.01:
        _reject("Durée audio différente de la durée vidéo.")
    subtitles, count = _subtitle_activity(document, len(audio))
    if count < 20:
        _reject("Au moins 20 répliques exploitables sont nécessaires.")
    offset_ms, correlation = _estimate(audio, subtitles)
    if document.timing_warnings(duration, offset_ms):
        _reject("Le décalage proposé produit un timing hors durée vidéo.")
    document.render({}, offset_ms=offset_ms)
    return {"offset_ms": offset_ms, "confidence": round(correlation, 4), "warnings": [
        "Proposition calculée contre la première piste audio, jamais contre une piste de sous-titres intégrée.",
        "Confiance = corrélation mesurée, pas une probabilité ; vérifier l'aperçu avant d'accepter.",
        "Décalage global uniquement, précision 20 ms ; aucune correction de vitesse ou de montage.",
    ]}
