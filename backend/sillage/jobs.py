"""Single low-concurrency worker with validated per-segment checkpoints."""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import tempfile
import uuid
from pathlib import Path

from . import providers
from .media import MediaLibrary
from .storage import Store, now
from .subtitles import SubtitleDocument
from .sync import propose_sync

ACTIVE = {"queued", "extracting", "translating", "validating", "syncing", "writing"}
FINAL = {"completed", "review", "error", "cancelled", "interrupted"}


def fingerprint(config: dict) -> str:
    data = {k: v for k, v in config.items() if k not in {"api_key", "has_key", "id", "name"}}
    return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()


def target_code(config: dict) -> str:
    lang = config.get("target_language", "fr").strip().lower()
    aliases = {"french": "fr", "français": "fr", "francais": "fr", "english": "en", "anglais": "en",
               "german": "de", "allemand": "de", "spanish": "es", "espagnol": "es", "italian": "it", "italien": "it"}
    code = aliases.get(lang, lang)
    if not code.isascii() or not code.isalpha() or len(code) not in {2, 3}:
        raise ValueError("Utilisez un code de langue cible ISO de 2 ou 3 lettres (fr, en, de…).")
    return code


class Worker:
    def __init__(self, store: Store, library: MediaLibrary):
        self.store, self.library = store, library
        self.task: asyncio.Task | None = None
        self.active: str | None = None
        self.stopping = False
        self.create_lock = asyncio.Lock()
        self.sync_lock = asyncio.Lock()
        self.inflight: dict[str, list[asyncio.Task]] = {}

    async def start(self):
        for job in self.store.jobs():
            if job["status"] in ACTIVE:
                self.store.patch(job["id"], status="interrupted", error="Traitement interrompu au redémarrage. Reprenez-le pour continuer les batches validés.")
        self.task = asyncio.create_task(self.loop())

    async def stop(self):
        self.stopping = True
        if self.task:
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass
        if self.active:
            self.store.patch(self.active, status="interrupted", error="Service arrêté. Les batches validés sont conservés.")

    async def loop(self):
        while not self.stopping:
            pending = [j for j in reversed(self.store.jobs()) if j["status"] == "queued"]
            if not pending:
                await asyncio.sleep(0.35)
                continue
            job = pending[0]
            self.active = job["id"]
            try:
                await self.process(job["id"])
            except asyncio.CancelledError:
                raise
            except (ValueError, OSError) as exc:
                # All provider errors are sanitized by the adapter. Never return arbitrary traceback/tool output.
                safe = str(exc) if isinstance(exc, ValueError) else "Accès au fichier impossible : vérifiez les permissions et l’espace disque."
                self.store.patch(job["id"], status="cancelled" if self.cancelled(job["id"]) else "error", error=safe[:500])
            except Exception:
                self.store.patch(job["id"], status="error", error="Le traitement a échoué. Les batches validés sont conservés ; vous pouvez réessayer.")
            finally:
                self.active = None

    def cancelled(self, jid: str) -> bool:
        return bool(self.store.job(jid).get("cancel_requested"))

    def check_cancel(self, jid: str):
        if self.cancelled(jid):
            raise ValueError("Traitement annulé. Les batches validés sont conservés.")

    async def create(self, data: dict) -> list[dict]:
        async with self.create_lock:
            return await self._create(data)

    async def _create(self, data: dict) -> list[dict]:
        config = self.store.provider(data["provider_id"], secrets=True)
        target_code(config)
        items = data["items"]
        if not 1 <= len(items) <= 500:
            raise ValueError("Sélectionnez entre 1 et 500 épisodes.")
        if data.get("sync_mode", "preserve") not in {"preserve", "offset", "auto"}:
            raise ValueError("Mode de synchronisation inconnu.")
        offset = data.get("offset_ms", 0)
        if not isinstance(offset, int) or abs(offset) > 600_000:
            raise ValueError("Le décalage manuel est limité à ±10 minutes.")
        prepared, seen = [], set()
        busy = {j["path"] for j in self.store.jobs() if j["status"] in ACTIVE or j.get("sync_pending")}
        for item in items:
            path = self.library.resolve(item["path"])
            if str(path) in busy or str(path) in seen:
                raise ValueError("Un épisode sélectionné possède déjà un traitement actif.")
            seen.add(str(path))
            info = await asyncio.to_thread(self.library.inspect, path)
            track = next((t for t in info["tracks"] if t["id"] == item["track_id"] and t["supported"]), None)
            if not track:
                raise ValueError("Sélectionnez une piste textuelle valide pour chaque épisode.")
            output = path.with_suffix(f".{target_code(config)}.{track['format']}")
            if output.exists() or output.is_symlink():
                raise ValueError(f"{output.name} existe déjà. Sillage ne remplace jamais un résultat existant.")
            if not os.access(path.parent, os.W_OK):
                raise ValueError("Le dossier média n’est pas accessible en écriture.")
            job = {"id": uuid.uuid4().hex, "path": str(path), "name": path.name, "track_id": item["track_id"],
                   "provider_id": config["id"], "status": "queued", "progress": 0, "done": 0, "total": 0,
                   "error": None, "warnings": [], "output": None, "created_at": now(),
                   "sync_mode": data.get("sync_mode", "preserve"), "offset_ms": offset, "timing_status": "Non vérifiés",
                   "config_fingerprint": fingerprint(config), "cancel_requested": False, "sync_pending": False}
            prepared.append(job)
        # All selection validation precedes insertion. No partial group on a bad item.
        for job in prepared:
            self.store.put_job(job)
        return prepared

    async def process(self, jid: str):
        job = self.store.job(jid)
        self.check_cancel(jid)
        config = self.store.provider(job["provider_id"], secrets=True)
        if fingerprint(config) != job["config_fingerprint"]:
            raise ValueError("La configuration du provider a changé. Créez un nouveau traitement pour éviter de mélanger les traductions.")
        work = self.store.folder / "work" / jid
        work.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.store.patch(jid, status="extracting", progress=max(2, job["progress"]), error=None)
        source, info = await asyncio.to_thread(self.library.extract, job["path"], job["track_id"], work)
        digest = hashlib.sha256(source.read_bytes()).hexdigest()
        if job.get("source_hash") and job["source_hash"] != digest:
            raise ValueError("La piste source a changé depuis le checkpoint. Créez un nouveau traitement.")
        doc = SubtitleDocument.load(source)
        self.validate_duration(doc, info["duration"])
        warnings = list(doc.warnings)
        self.store.patch(jid, source_hash=digest, source_file=str(source), total=len(doc.segments), warnings=warnings)
        translations = self.store.translations(jid)
        doc.validate_translations(translations, require_all=False)
        pending = [s for s in doc.segments if s["id"] not in translations]
        total = len(doc.segments)
        # Reuse only empirical ceilings from this exact profile/configuration.
        # Operational feedback stays in job metadata, never in provider secrets.
        limit = providers.initial_batch_size(config)
        history = [entry for entry in self.store.jobs()
                   if entry["provider_id"] == job["provider_id"]
                   and entry["config_fingerprint"] == job["config_fingerprint"]][:20]
        for entry in history:
            learned = entry.get("adaptive_batch_size")
            if isinstance(learned, int) and 1 <= learned <= 100:
                limit = min(limit, learned)
        self.store.patch(jid, adaptive_batch_size=limit)
        positions = {segment["id"]: index for index, segment in enumerate(doc.segments)}

        async def translate_batch(batch):
            first, last = positions[batch[0]["id"]], positions[batch[-1]["id"]]
            context = doc.segments[max(0, first-3):first] + doc.segments[last+1:last+4]
            context = [cue | ({"translated": translations[cue["id"]]} if cue["id"] in translations else {}) for cue in context]
            return await providers.translate(config, batch, context, config.get("glossary", ""))

        def record_usage(result):
            usage = dict(self.store.job(jid).get("usage", {}))
            for key, value in result.items():
                if isinstance(value, (int, float)):
                    usage[key] = usage.get(key, 0) + value
            self.store.patch(jid, usage=usage)

        # Build each wave after feedback from the preceding wave. A precomputed
        # episode-wide batch list would ignore the model's recovered smaller size.
        while pending:
            self.check_cancel(jid)
            self.store.patch(jid, status="translating", progress=5 + int(80 * len(translations) / max(total, 1)), done=len(translations))
            group = []
            for _ in range(config["concurrency"]):
                if not pending:
                    break
                batch = providers.take_batch(pending, limit, providers.batch_byte_limit(config))
                group.append(batch)
                pending = pending[len(batch):]
            tasks = [asyncio.create_task(translate_batch(batch)) for batch in group]
            self.inflight[jid] = tasks
            try:
                for completed in asyncio.as_completed(tasks):
                    try:
                        result = await completed
                    except providers.StructuredOutputError as error:
                        limit = min(limit, error.batch_size)
                        record_usage(error.usage)
                        self.store.patch(jid, adaptive_batch_size=limit)
                        raise
                    candidate = translations | result["translations"]
                    doc.validate_translations(candidate, require_all=False)
                    self.store.checkpoint(jid, result["translations"])
                    translations = candidate
                    if result.get("recovered"):
                        limit = min(limit, result["batch_size"])
                    warnings.extend(w for w in result.get("warnings", []) if w not in warnings)
                    record_usage(result.get("usage", {}))
                    self.store.patch(jid, done=len(translations), progress=5+int(80*len(translations)/max(total,1)),
                                     adaptive_batch_size=limit, warnings=warnings)
                    self.check_cancel(jid)
            except asyncio.CancelledError:
                self.check_cancel(jid)  # User cancellation must not stop the queue loop.
                raise
            finally:
                self.inflight.pop(jid, None)
                for task in tasks:
                    if not task.done():
                        task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)
        self.check_cancel(jid)
        self.store.patch(jid, status="validating", progress=88)
        doc.validate_translations(translations, require_all=True)
        self.store.patch(jid, warnings=warnings)
        if job["sync_mode"] == "auto":
            self.store.patch(jid, status="syncing", progress=90)
            try:
                proposal = await asyncio.to_thread(propose_sync, job["path"], source, info["duration"])
            except ValueError as exc:
                self.store.patch(jid, status="review", progress=90, sync_pending=True, sync_proposal=None,
                                 warnings=warnings + [str(exc)], timing_status="Correction automatique refusée ; timings source disponibles")
                return
            self.store.patch(jid, status="review", progress=90, sync_pending=True, sync_proposal=proposal,
                             warnings=warnings+proposal.get("warnings", []), timing_status="Correction proposée — validation requise")
            return
        await self.finalize(jid, job["offset_ms"] if job["sync_mode"] == "offset" else 0)

    @staticmethod
    def validate_duration(doc, duration: float, offset: int = 0):
        warnings = doc.timing_warnings(duration, offset_ms=offset)
        if warnings:
            raise ValueError("Timings invalides ou hors durée vidéo ; export refusé. " + warnings[0])

    async def finalize(self, jid: str, offset: int):
        self.check_cancel(jid)
        job = self.store.job(jid)
        source = Path(job["source_file"])
        if hashlib.sha256(source.read_bytes()).hexdigest() != job["source_hash"]:
            raise ValueError("Checkpoint source modifié. Export refusé.")
        doc = SubtitleDocument.load(source)
        config = self.store.provider(job["provider_id"], secrets=True)
        if fingerprint(config) != job["config_fingerprint"]:
            raise ValueError("La configuration du provider a changé avant l’export. Créez un nouveau traitement.")
        with tempfile.TemporaryDirectory(prefix="sillage-recheck-") as directory:
            current, info = await asyncio.to_thread(self.library.extract, job["path"], job["track_id"], Path(directory))
            if hashlib.sha256(current.read_bytes()).hexdigest() != job["source_hash"]:
                raise ValueError("La piste source a changé avant l’export. Aucun résultat publié.")
        self.validate_duration(doc, info["duration"], offset)
        translations = self.store.translations(jid)
        doc.validate_translations(translations, require_all=True)
        content = doc.render(translations, offset_ms=offset)
        self.check_cancel(jid)
        self.store.patch(jid, status="writing", progress=96)
        config = self.store.provider(job["provider_id"], secrets=True)
        suffix = f".{target_code(config)}.{doc.format}"
        expected_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
        path = self.library.resolve(job["path"]).with_suffix(suffix)
        # Recover a crash after successful publication but before SQLite completion only for our exact write intent.
        recovered = False
        if job.get("write_hash") == expected_hash and path.is_file() and not path.is_symlink():
            recovered = hashlib.sha256(path.read_bytes()).hexdigest() == expected_hash
        if not recovered:
            self.store.patch(jid, write_hash=expected_hash)
            path = await asyncio.to_thread(self.library.publish, job["path"], suffix, content)
        self.store.patch(jid, status="review" if job["warnings"] else "completed", progress=100, output=str(path), error=None,
                         sync_pending=False, applied_offset_ms=offset,
                         timing_status=f"Décalage explicite : {offset:+d} ms (audio non vérifié)" if job["sync_mode"] == "offset" else
                         f"Décalage audio accepté : {offset:+d} ms (première piste audio)" if job["sync_mode"] == "auto" and offset else
                         "Timings source préservés — audio non vérifié")

    def cancel(self, jid: str) -> dict:
        job = self.store.job(jid)
        if job["status"] in {"completed", "review"} and not job.get("sync_pending"):
            raise ValueError("Ce traitement est déjà terminé.")
        result = self.store.patch(jid, cancel_requested=True, sync_pending=False, status="cancelled")
        # API handlers run in FastAPI's thread pool; cancel on the owning loop.
        for task in self.inflight.get(jid, []):
            task.get_loop().call_soon_threadsafe(task.cancel)
        return result

    def resume(self, jid: str) -> dict:
        job = self.store.job(jid)
        if self.active == jid or job["status"] not in {"error", "interrupted", "cancelled"}:
            raise ValueError("Ce traitement ne peut pas être repris pour le moment.")
        if any(j["id"] != jid and j["path"] == job["path"] and (j["status"] in ACTIVE or j.get("sync_pending")) for j in self.store.jobs()):
            raise ValueError("Un autre traitement est déjà actif pour cet épisode.")
        return self.store.patch(jid, status="queued", error=None, cancel_requested=False, sync_pending=False)

    async def decide_sync(self, jid: str, accept: bool) -> dict:
        async with self.sync_lock:
            return await self._decide_sync(jid, accept)

    async def _decide_sync(self, jid: str, accept: bool) -> dict:
        job = self.store.job(jid)
        if not job.get("sync_pending"):
            raise ValueError("Aucune correction n’attend de validation.")
        proposal = job.get("sync_proposal")
        if accept and not proposal:
            raise ValueError("Correction incertaine : acceptez uniquement les timings source.")
        await self.finalize(jid, proposal["offset_ms"] if accept else 0)
        return self.store.job(jid)

    def preview(self, jid: str) -> dict:
        job = self.store.job(jid)
        if not job.get("source_file"):
            raise ValueError("L’extraction n’a pas encore commencé.")
        doc = SubtitleDocument.load(Path(job["source_file"]))
        translations = self.store.translations(jid)
        # Render+parse uses the same safe reconstruction as final output, rather than exposing placeholders.
        rendered = doc.render(translations)
        work = self.store.folder / "work" / jid
        preview_file = work / ("preview." + doc.format)
        preview_file.write_text(rendered, encoding="utf-8", newline="")
        translated_doc = SubtitleDocument.load(preview_file)
        by_id = {c["id"]: c["text"] for c in translated_doc.cues}
        offset = (job.get("sync_proposal") or {}).get("offset_ms", job.get("applied_offset_ms", 0))
        cues = []
        for cue in doc.cues:
            item = dict(cue)
            if cue["id"] in translations:
                item["translated"] = by_id.get(cue["id"], translations[cue["id"]])
            if offset:
                item |= {"proposed_start": cue["start"]+offset, "proposed_end": cue["end"]+offset}
            cues.append(item)
        return {"format": doc.format, "cues": cues, "warnings": job["warnings"], "timing_status": job["timing_status"], "sync_pending": job.get("sync_pending", False), "sync_proposal": job.get("sync_proposal")}
