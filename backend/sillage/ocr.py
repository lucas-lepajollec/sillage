"""Explicit local burned-in English OCR. No provider calls or source-media writes."""
from __future__ import annotations

import asyncio
import base64
import csv
import hashlib
import html
import io
import math
import os
import re
import shutil
import uuid
from difflib import SequenceMatcher
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .media import MediaLibrary
from .storage import Store, now
from .subtitles import SubtitleDocument

WARNING = "OCR local : erreurs de lecture possibles, timings estimés à partir des images. Relisez avant traduction."
TERMINAL = {"review", "published", "cancelled", "error", "interrupted", "paused"}


class OcrOptions(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    top: float = Field(default=70, ge=0, le=95)
    bottom: float = Field(default=100, ge=5, le=100)
    left: float = Field(default=5, ge=0, le=90)
    right: float = Field(default=95, ge=10, le=100)
    fps: Literal[2, 4] = 4
    mode: Literal["white", "gray"] = "white"
    threshold: int = Field(default=200, ge=120, le=245)
    confidence: int = Field(default=65, ge=30, le=95)

    @model_validator(mode="after")
    def rectangle(self):
        if self.bottom - self.top < 5 or self.right - self.left < 10:
            raise ValueError("La zone OCR doit couvrir au moins 5 % de hauteur et 10 % de largeur.")
        return self


def fingerprint(path: Path) -> list[int]:
    stat = path.stat()
    return [stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns]


def geometry(info: dict, options: OcrOptions) -> tuple[str, int, int]:
    iw, ih = info.get("video_width", 0), info.get("video_height", 0)
    if not (isinstance(iw, int) and isinstance(ih, int) and 32 <= iw <= 8192 and 32 <= ih <= 8192):
        raise ValueError("Dimensions vidéo non prises en charge pour l’OCR (32 à 8192 pixels).")
    x, y = int(iw * options.left / 100), int(ih * options.top / 100)
    w, h = int(iw * (options.right-options.left) / 100), int(ih * (options.bottom-options.top) / 100)
    scale = min(1280 / w, 720 / h, 2)
    width, height = max(2, int(w*scale)), max(2, int(h*scale))
    return f"crop={w}:{h}:{x}:{y},scale={width}:{height},format=gray", width, height


def parse_tsv(raw: bytes, minimum: int) -> tuple[str, float]:
    lines: dict[tuple[str, ...], list[str]] = {}
    scores, weights = [], []
    for row in csv.DictReader(io.StringIO(raw.decode("utf-8", errors="replace")), delimiter="\t"):
        if row.get("level") != "5":
            continue
        word = re.sub(r"\s+", " ", row.get("text") or "").strip()
        if not word or len(word) > 100:
            continue
        try:
            score = float(row["conf"])
        except (ValueError, TypeError, KeyError):
            continue
        if not math.isfinite(score) or not 0 <= score <= 100:
            continue
        key = tuple(row.get(k, "") for k in ("page_num", "block_num", "par_num", "line_num"))
        lines.setdefault(key, []).append(word)
        scores.append(score*len(word))
        weights.append(len(word))
    text = "\n".join(" ".join(words) for words in lines.values())
    score = sum(scores)/max(1, sum(weights))
    if score < minimum or not 3 <= sum(c.isalpha() for c in text) or len(text) > 600 or len(lines) > 4:
        return "", score
    # OCR output is literal text, never trusted subtitle markup or event syntax.
    text = "".join(c for c in text if c == "\n" or (ord(c) >= 32 and c not in "\u2028\u2029"))
    return text, score


def normalized(text: str) -> str:
    return re.sub(r"\s+", " ", text).casefold().strip()


def observe(state: dict, text: str, score: float, start: int, end: int):
    active = state.get("active")
    if active and text and SequenceMatcher(None, normalized(active['text']), normalized(text), autojunk=False).ratio() >= .9:
        active["end"], active["samples"] = end, active["samples"]+1
        if score > active["confidence"]:
            active["text"], active["confidence"] = text, score
        return
    if active and active["samples"] >= 2:
        state["cues"].append(active)
        if len(state["cues"]) > 10000:
            raise ValueError("Extraction limitée à 10 000 répliques. Réduisez la zone OCR.")
    state["active"] = {"text": text, "start": start, "end": end, "samples": 1, "confidence": score} if text else None


def srt_text(cues: list[dict]) -> str:
    def stamp(ms):
        seconds, milliseconds = divmod(int(ms), 1000)
        minutes, seconds = divmod(seconds, 60)
        hours, minutes = divmod(minutes, 60)
        return f"{hours:02}:{minutes:02}:{seconds:02},{milliseconds:03}"
    return "\n\n".join(f"{i}\n{stamp(c['start'])} --> {stamp(c['end'])}\n{html.escape(c['text'], quote=False)}"
                       for i, c in enumerate(cues, 1)) + "\n"


async def terminate(process):
    if process.returncode is None:
        try:
            process.kill()
        except ProcessLookupError:
            pass
    # Drain a killed decoder's pipe; a paused asyncio transport can otherwise
    # leave wait() blocked even after the operating system reaps the process.
    async def drain():
        if process.stdout:
            while await process.stdout.read(65536):
                pass
    await asyncio.wait_for(asyncio.gather(drain(), process.wait()), 10)


async def command(args: list[str], data: bytes | None = None, *, limit: int = 2_000_000, timeout: int = 30) -> bytes:
    process = await asyncio.create_subprocess_exec(*args, stdin=asyncio.subprocess.PIPE if data is not None else asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL, env=os.environ | {"OMP_THREAD_LIMIT": "1"})
    async def exchange():
        async def write():
            if data is not None:
                process.stdin.write(data)
                try:
                    await process.stdin.drain()
                except (BrokenPipeError, ConnectionResetError):
                    pass
                process.stdin.close()
        writer = asyncio.create_task(write())
        try:
            result = await process.stdout.read(limit+1)
            # StreamReader.read may return a short chunk before EOF.
            chunks = [result]
            size = len(result)
            while chunks[-1] and size <= limit:
                chunk = await process.stdout.read(min(65536, limit+1-size))
                chunks.append(chunk)
                size += len(chunk)
            if size > limit:
                raise ValueError("Réponse OCR trop volumineuse. Réduisez la zone.")
            await writer
            await process.wait()
            if process.returncode:
                raise ValueError("L’outil OCR ou vidéo a échoué. Vérifiez le fichier et l’installation de Tesseract anglais.")
            return b"".join(chunks)
        finally:
            if not writer.done():
                writer.cancel()
            await asyncio.gather(writer, return_exceptions=True)
    try:
        return await asyncio.wait_for(exchange(), timeout)
    except TimeoutError:
        raise ValueError("Délai OCR dépassé pour une image. Réduisez la zone et réessayez.") from None
    finally:
        await terminate(process)


class OcrService:
    def __init__(self, store: Store, library: MediaLibrary):
        self.store, self.library = store, library
        self.lock = asyncio.Lock()
        self.engine = asyncio.Semaphore(1)
        self.active: str | None = None
        self.task: asyncio.Task | None = None

    def recover(self):
        for task in self.store.ocr_tasks():
            if task["status"] == "running":
                self.store.ocr_patch(task["id"], status="interrupted", pause_requested=False,
                    error="OCR interrompu au redémarrage ; reprenez les images restantes.")

    def pending(self):
        return next((t for t in reversed(self.store.ocr_tasks()) if t['status'] == 'queued'), None)

    def check_source(self, task):
        path = self.library.resolve(task["path"])
        if fingerprint(path) != task["fingerprint"]:
            raise ValueError("La vidéo a changé depuis le début de l’OCR. Créez une nouvelle extraction.")
        return path

    async def prepare(self, paths: list[str], options: OcrOptions) -> list[dict]:
        if not shutil.which("tesseract"):
            raise ValueError("Tesseract anglais est nécessaire. Mettez à jour l’image Docker ou installez tesseract-ocr-eng.")
        async with self.lock:
            existing = self.store.ocr_tasks()
            if not 1 <= len(paths) <= 50 or len(existing)+len(paths) > 200:
                raise ValueError("Limite : 50 épisodes par ajout, 200 extractions conservées. Retirez les anciennes entrées OCR.")
            busy = {t['path'] for t in existing if t['status'] not in {'published', 'cancelled', 'error'}}
            tasks = []
            for value in paths:
                info = await asyncio.to_thread(self.library.inspect, value)
                path = self.library.resolve(value)
                geometry(info, options)
                if not 0 < info['duration'] <= 14400:
                    raise ValueError("L’OCR accepte des vidéos jusqu’à 4 heures.")
                if str(path) in busy:
                    raise ValueError("Un épisode possède déjà une extraction OCR à terminer ou retirer.")
                busy.add(str(path))
                tasks.append({"id": uuid.uuid4().hex, "path": str(path), "name": path.name, "duration": info['duration'],
                    "options": options.model_dump(), "fingerprint": fingerprint(path), "created_at": now(),
                    "status": "queued", "index": 0, "total": math.ceil(info['duration']*options.fps), "progress": 0,
                    "cues": [], "active": None, "rejected": 0, "error": None, "pause_requested": False, "output": None})
            self.store.ocr_put_many(tasks)
            return [self.public(t) for t in tasks]

    async def snapshot(self, value: str, options: OcrOptions, at: float) -> dict:
        async with self.engine:
            if not shutil.which("tesseract"):
                raise ValueError("Installez Tesseract anglais ou utilisez la dernière image Docker.")
            info = await asyncio.to_thread(self.library.inspect, value)
            if not 0 <= at < min(info['duration'], 14400):
                raise ValueError("Choisissez une image à l’intérieur de la vidéo (4 heures maximum).")
            filters, width, height = geometry(info, options)
            path = str(self.library.resolve(value))
            prefix = ["ffmpeg", "-nostdin", "-v", "error", "-threads", "1", "-ss", str(at), "-i", path,
                "-map", "0:V:0", "-frames:v", "1", "-filter_threads", "1"]
            image = await command(prefix + ["-vf", "scale=960:540:force_original_aspect_ratio=decrease", "-c:v", "png", "-f", "image2pipe", "pipe:1"])
            frame = await command(prefix + ["-vf", filters, "-pix_fmt", "gray", "-f", "rawvideo", "pipe:1"])
            if len(frame) != width*height:
                raise ValueError("Image OCR incomplète.")
            text, confidence = await self.recognize(frame, width, height, options)
            return {"image": "data:image/png;base64," + base64.b64encode(image).decode(), "text": text,
                    "confidence": round(confidence, 1), "warning": WARNING}

    async def recognize(self, frame: bytes, width: int, height: int, options: OcrOptions):
        if options.mode == "white":
            frame = frame.translate(bytes(0 if n >= options.threshold else 255 for n in range(256)))
        data = f"P5\n{width} {height}\n255\n".encode() + frame
        raw = await command(["tesseract", "stdin", "stdout", "-l", "eng", "--oem", "1", "--psm", "6", "tsv"], data)
        return parse_tsv(raw, options.confidence)

    async def run(self, tid: str):
        self.active = tid
        self.task = asyncio.create_task(self.process(tid))
        try:
            await self.task
        except asyncio.CancelledError:
            task = self.store.ocr_task(tid)
            if task['status'] != 'cancelled':
                self.store.ocr_patch(tid, status='interrupted', error='Service arrêté ; les images validées restent disponibles.')
            if asyncio.current_task().cancelling():
                raise
        except Exception as exc:
            safe = str(exc) if isinstance(exc, ValueError) else "OCR impossible. Vérifiez les outils, permissions et l’espace disponible."
            self.store.ocr_patch(tid, status='error', error=safe[:500])
        finally:
            self.task, self.active = None, None

    async def process(self, tid: str):
        task = self.store.ocr_task(tid)
        if task['status'] != 'queued':
            return
        self.store.ocr_patch(tid, status='running', error=None)
        path = self.check_source(task)
        info = await asyncio.to_thread(self.library.inspect, path)
        options = OcrOptions(**task['options'])
        filters, width, height = geometry(info, options)
        step = 1000/options.fps
        start_index = task['index']
        args = ["ffmpeg", "-nostdin", "-v", "error", "-threads", "1", "-ss", str(start_index/options.fps), "-i", str(path),
            "-map", "0:V:0", "-an", "-sn", "-filter_threads", "1", "-vf", f"tpad=stop_mode=clone:stop_duration=0.5,fps={options.fps}:start_time=0:round=up,{filters}",
            "-frames:v", str(task['total']-start_index),
            "-pix_fmt", "gray", "-f", "rawvideo", "pipe:1"]
        process = await asyncio.create_subprocess_exec(*args, stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
        previous_frame, previous_result = None, None
        def save_progress():
            self.store.ocr_patch(tid, index=task['index'], progress=task['progress'], cues=task['cues'],
                active=task['active'], rejected=task['rejected'])
        try:
            for index in range(start_index, task['total']):
                _, pause_requested = self.store.ocr_control(tid)
                if pause_requested:
                    self.store.ocr_patch(tid, status='paused', pause_requested=False)
                    return
                self.check_source(task)
                try:
                    frame = await asyncio.wait_for(process.stdout.readexactly(width*height), 60)
                except (asyncio.IncompleteReadError, TimeoutError):
                    raise ValueError("Décodage vidéo interrompu avant la fin. L’OCR n’a pas été publié ; reprenez ou vérifiez le fichier.") from None
                comparison = frame.translate(bytes(0 if n >= options.threshold else 255 for n in range(256))) if options.mode == 'white' else frame
                digest = hashlib.sha256(comparison).digest()
                if digest == previous_frame:
                    text, confidence = previous_result
                else:
                    async with self.engine:
                        text, confidence = await self.recognize(frame, width, height, options)
                    previous_frame, previous_result = digest, (text, confidence)
                begin, end = round(index*step), min(round((index+1)*step), round(info['duration']*1000))
                observe(task, text, confidence, begin, end)
                if not text and confidence > 0:
                    task['rejected'] += 1
                # Persist the active cue as well as completed cues, so pause and
                # restart never join text across an unobserved gap.
                task.update(index=index+1, progress=int(100*(index+1)/task['total']))
                if (index+1) % 8 == 0:
                    save_progress()
            await asyncio.wait_for(process.wait(), 60)
            if process.returncode:
                raise ValueError("Le décodage vidéo a échoué ; aucun sous-titre n’a été publié.")
            observe(task, '', 0, round(info['duration']*1000), round(info['duration']*1000))
            if not task['cues']:
                raise ValueError("Aucun texte stable détecté. Testez une image avec dialogue et ajustez la zone ou le contraste.")
            if len(srt_text(task['cues']).encode('utf-8')) > 2_000_000:
                raise ValueError("Le SRT dépasse 2 Mo. Réduisez la zone OCR et créez une nouvelle extraction.")
            self.store.ocr_patch(tid, status='review', cues=task['cues'], active=None, progress=100)
        finally:
            try:
                save_progress()
            finally:
                await terminate(process)

    async def action(self, tid: str, action: str):
        async with self.lock:
            task = self.store.ocr_task(tid)
            if action == 'pause' and task['status'] in {'queued', 'running'}:
                task = self.store.ocr_patch(tid, **({'pause_requested': True} if task['status'] == 'running' else {'status': 'paused'}))
            elif action == 'resume' and task['status'] in {'paused', 'interrupted', 'error'}:
                self.check_source(task)
                if task['index'] >= task['total']:
                    raise ValueError("Cette tentative est terminée sans résultat utilisable. Retirez-la et ajustez une nouvelle extraction.")
                if any(t['id'] != tid and t['path'] == task['path'] and t['status'] not in {'published', 'cancelled', 'error'} for t in self.store.ocr_tasks()):
                    raise ValueError("Une autre extraction OCR réserve déjà cet épisode.")
                task = self.store.ocr_patch(tid, status='queued', pause_requested=False, error=None)
            elif action == 'cancel' and task['status'] != 'published':
                task = self.store.ocr_patch(tid, status='cancelled', pause_requested=False)
                if self.active == tid and self.task:
                    self.task.cancel()
            elif action == 'delete' and task['status'] in TERMINAL and self.active != tid:
                self.store.ocr_delete(tid)
                return {'deleted': tid}
            else:
                raise ValueError("Cette action n’est pas disponible pendant cette étape OCR.")
            return self.public(task)

    async def publish(self, tid: str, content: str) -> dict:
        async with self.lock:
            task = self.store.ocr_task(tid)
            if task['status'] != 'review':
                raise ValueError("Terminez et relisez l’OCR avant de publier sa source anglaise.")
            path = self.check_source(task)
            if not content or len(content.encode('utf-8')) > 2_000_000:
                raise ValueError("Source OCR vide ou trop volumineuse (2 Mo maximum).")
            doc = SubtitleDocument(content, 'srt')
            if not doc.segments or len(doc.cues) > 10000 or doc.timing_warnings(task['duration']):
                raise ValueError("Corrigez le SRT : répliques textuelles et timings dans la durée vidéo requis.")
            digest = hashlib.sha256(content.encode('utf-8')).hexdigest()
            output = path.with_suffix('.en.ocr.srt')
            recovered = False
            if task.get('write_hash') == digest and not output.is_symlink() and output.is_file():
                with output.open('rb') as existing:
                    recovered = hashlib.sha256(existing.read(2_000_001)).hexdigest() == digest
            if not recovered:
                if output.exists() or output.is_symlink():
                    raise ValueError("Le fichier .en.ocr.srt existe déjà. Il est conservé ; retirez-le manuellement avant de le remplacer.")
                self.store.ocr_patch(tid, write_hash=digest)
                try:
                    output = self.library.publish(path, '.en.ocr.srt', content)
                except FileExistsError:
                    raise ValueError("Un fichier .en.ocr.srt existe déjà ; il est conservé.") from None
            self.store.ocr_patch(tid, status='published', output=str(output))
            info = self.library.inspect(path)
            return {'episode': info, 'track_id': 'external:' + output.name}

    @staticmethod
    def public(task: dict, *, result: bool = False):
        public = {k: v for k, v in task.items() if k not in {'cues', 'active', 'fingerprint', 'write_hash'}}
        public['cue_count'] = len(task['cues']) if 'cues' in task else task.get('cue_count', 0)
        public['warning'] = WARNING
        if result:
            public['srt'] = srt_text(task['cues']) if task['status'] == 'review' else ''
        return public
