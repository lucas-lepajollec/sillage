"""Lazy filesystem browsing and read-only media inspection. Never touches the MKV."""
from __future__ import annotations

import json
import os
import re
import shutil
import stat
import subprocess
import uuid
from pathlib import Path

TEXT_FORMATS = {"ass": "ass", "ssa": "ssa", "subrip": "srt", "srt": "srt"}
SUB_EXTENSIONS = {".ass", ".ssa", ".srt"}
FRENCH = {"fr", "fre", "fra", "french", "français"}
ENGLISH = {"en", "eng", "english"}


class MediaLibrary:
    def __init__(self, roots: list[Path]):
        self.roots = [p.expanduser().resolve() for p in roots]
        if not self.roots:
            raise ValueError("Au moins une racine média est nécessaire.")

    def resolve(self, value: str | Path | None, *, directory: bool = False) -> Path:
        raw = Path(value) if value else self.roots[0]
        if not raw.is_absolute() or ".." in raw.parts:
            raise ValueError("Chemin absolu requis, sans traversée de répertoire.")
        path = raw.resolve(strict=True)
        if not any(path.is_relative_to(root) for root in self.roots):
            raise ValueError("Ce chemin sort des racines média autorisées.")
        if directory and not path.is_dir():
            raise ValueError("Le chemin doit désigner un dossier.")
        if not directory and not (path.is_file() or path.is_dir()):
            raise ValueError("Type de fichier non pris en charge.")
        return path

    def browse(self, value: str | None = None) -> dict:
        path = self.resolve(value, directory=True)
        directories, files = [], []
        for child in sorted(path.iterdir(), key=lambda p: (not p.is_dir(), p.name.casefold())):
            if child.name.startswith("."):
                continue
            try:
                safe = self.resolve(child)
                # Hide links entirely: avoids directory loops and confusing alias selections.
                if child.is_symlink():
                    continue
                item = {"name": child.name, "path": str(safe)}
                if child.is_dir():
                    directories.append(item)
                elif child.suffix.lower() == ".mkv":
                    files.append(item)
            except (OSError, ValueError):
                continue
        return {"path": str(path), "parent": None if path in self.roots else str(path.parent),
                "roots": [str(p) for p in self.roots], "directories": directories, "files": files}

    def scan(self, value: str, recursive: bool = True) -> dict:
        folder = self.resolve(value, directory=True)
        episodes, errors = [], []
        def walk_error(error):
            errors.append({"path": str(error.filename or folder), "error": "Dossier illisible : vérifiez les permissions."})
        for current, dirs, files in os.walk(folder, followlinks=False, onerror=walk_error):
            dirs[:] = sorted(d for d in dirs if not d.startswith(".") and not Path(current, d).is_symlink())
            for name in sorted(files):
                if Path(name).suffix.lower() != ".mkv":
                    continue
                try:
                    path = self.resolve(Path(current, name))
                    if Path(current, name).is_symlink():
                        continue
                    episodes.append(self.inspect(path))
                except (OSError, ValueError, subprocess.SubprocessError):
                    errors.append({"path": str(Path(current, name)), "error": "Analyse impossible : fichier invalide, illisible ou délai dépassé."})
            if not recursive:
                break
        return {"episodes": episodes, "errors": errors}

    def inspect(self, value: str | Path) -> dict:
        path = self.resolve(value)
        if path.suffix.lower() != ".mkv":
            raise ValueError("Seuls les fichiers MKV sont acceptés.")
        raw = run(["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)], timeout=90)
        try:
            probe = json.loads(raw)
            duration = float(probe.get("format", {}).get("duration", 0))
            if not 0 < duration < 864000:
                raise ValueError("Durée vidéo invalide.")
        except (TypeError, json.JSONDecodeError):
            raise ValueError("Informations vidéo invalides.") from None
        tracks = []
        for stream in probe.get("streams", []):
            if stream.get("codec_type") != "subtitle":
                continue
            tags, disposition = stream.get("tags", {}), stream.get("disposition", {})
            codec = stream.get("codec_name", "unknown")
            tracks.append({"id": f"embedded:{stream['index']}", "index": stream["index"],
                           "language": tags.get("language", "und"), "format": TEXT_FORMATS.get(codec, codec),
                           "title": tags.get("title", ""), "default": bool(disposition.get("default")),
                           "forced": bool(disposition.get("forced")), "sdh": bool(disposition.get("hearing_impaired")),
                           "external": False, "supported": codec in TEXT_FORMATS})
        for sidecar in sorted(path.parent.iterdir()):
            if (sidecar.suffix.lower() not in SUB_EXTENSIONS or sidecar.is_symlink() or
                not (sidecar.stem == path.stem or sidecar.stem.startswith(path.stem + "."))):
                continue
            safe = self.resolve(sidecar)
            tokens = sidecar.stem[len(path.stem):].lower().strip(".").split(".")
            lang = next((t for t in tokens if t in FRENCH | ENGLISH), "und")
            tracks.append({"id": f"external:{safe.name}", "index": None, "language": lang,
                           "format": sidecar.suffix[1:].lower(), "title": sidecar.name, "default": False,
                           "forced": "forced" in tokens, "sdh": "sdh" in tokens, "external": True,
                           "path": str(safe), "supported": True})
        french_tracks = [t for t in tracks if t["language"].lower() in FRENCH]
        has_french = any(not t["forced"] and not re.search(r"signs?\s*(?:only|&|/|and)|(?:panneaux|signs)\s*(?:seuls|only)", t["title"], re.I) for t in french_tracks)
        ready = any(t["supported"] and t["language"].lower() in ENGLISH for t in tracks)
        return {"path": str(path), "name": path.name, "duration": duration, "tracks": tracks,
                "has_french": has_french, "has_french_partial": bool(french_tracks) and not has_french, "status": "existing" if has_french else "ready" if ready else "manual" if any(t["supported"] for t in tracks) else "unsupported"}

    def extract(self, value: str | Path, track_id: str, work: Path) -> tuple[Path, dict]:
        path = self.resolve(value)
        info = self.inspect(path)
        track = next((t for t in info["tracks"] if t["id"] == track_id), None)
        if not track or not track["supported"]:
            raise ValueError("Piste textuelle introuvable ou format graphique non traduisible.")
        output = work / ("source." + track["format"])
        if track["external"]:
            source = self.resolve(track["path"])
            if source.stat().st_size > 30_000_000:
                raise ValueError("Fichier de sous-titres trop volumineux (30 Mo maximum).")
            shutil.copyfile(source, output)
        else:
            run(["ffmpeg", "-nostdin", "-v", "error", "-i", str(path), "-map", f"0:{track['index']}",
                 "-c:s", "copy", "-y", str(output)], timeout=180)
        if not output.exists() or output.stat().st_size > 30_000_000:
            raise ValueError("Extraction vide ou trop volumineuse.")
        return output, info

    def publish(self, video: str | Path, suffix: str, content: str) -> Path:
        """Exclusive atomic sidecar publication, relative to a verified open directory.

        link() refuses an existing destination, including a symlink, without a racy exists()/replace().
        """
        source = self.resolve(video)
        if not re.fullmatch(r"\.[a-z]{2,3}\.(?:ass|ssa|srt)", suffix):
            raise ValueError("Extension de sortie interdite.")
        parent = self.resolve(source.parent, directory=True)
        # Open each canonical component without following symlinks (concurrent rename defense).
        fd = os.open("/", os.O_RDONLY | os.O_DIRECTORY)
        try:
            for part in parent.parts[1:]:
                next_fd = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
                os.close(fd)
                fd = next_fd
            if not stat.S_ISDIR(os.fstat(fd).st_mode):
                raise ValueError("Destination invalide.")
            name = source.stem + suffix
            temporary = ".sillage-" + uuid.uuid4().hex + ".tmp"
            tmp_fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o644, dir_fd=fd)
            try:
                with os.fdopen(tmp_fd, "wb") as output:
                    output.write(content.encode("utf-8"))
                    output.flush()
                    os.fsync(output.fileno())
                os.link(temporary, name, src_dir_fd=fd, dst_dir_fd=fd, follow_symlinks=False)
                os.fsync(fd)
            finally:
                os.unlink(temporary, dir_fd=fd)
            return parent / name
        finally:
            os.close(fd)


def run(args: list[str], timeout: int = 60) -> str:
    result = subprocess.run(args, capture_output=True, timeout=timeout, check=False)
    if result.returncode:
        # Tool stderr can contain media content; do not echo it to logs/API.
        raise ValueError(f"{Path(args[0]).name} a échoué. Vérifiez le fichier et ses permissions.")
    return result.stdout.decode("utf-8", errors="replace")
