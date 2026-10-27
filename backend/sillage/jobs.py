"""Single low-concurrency worker with validated per-segment checkpoints."""
from __future__ import annotations

import asyncio
import hashlib
import os
import re
import shutil
import stat
import tempfile
import uuid
from pathlib import Path
from subprocess import TimeoutExpired

from . import providers
from .media import MediaLibrary
from .storage import Store, now, provider_fingerprint as fingerprint
from .subtitles import SubtitleDocument
from .sync import propose_sync

ACTIVE = {"queued", "extracting", "translating", "validating", "syncing", "writing"}
RUNTIME_FIELDS = ("batch_size", "concurrency", "timeout", "retries")
FINAL = {"completed", "review", "error", "cancelled", "interrupted"}


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
                   "source_track": {k: v for k, v in track.items() if k != "path"},
                   "provider_id": config["id"], "status": "queued", "progress": 0, "done": 0, "total": 0,
                   "error": None, "warnings": [], "output": None, "created_at": now(),
                   "sync_mode": data.get("sync_mode", "preserve"), "offset_ms": offset, "timing_status": "Non vérifiés",
                   "config_fingerprint": fingerprint(config), "provider_snapshot": self.store.seal_config(config),
                   "translation_profile": self.profile_label(config), "cancel_requested": False, "sync_pending": False}
            prepared.append(job)
        # All selection validation precedes insertion. No partial group on a bad item.
        for job in prepared:
            self.store.put_job(job)
        return prepared

    @staticmethod
    def profile_label(config: dict) -> dict:
        return {key: config.get(key) for key in ("name", "kind", "model", "source_language", "target_language")}

    def job_config(self, job: dict) -> dict:
        if job.get("provider_snapshot"):
            saved = self.store.open_config(job["provider_snapshot"])
            if not job.get("translation_profile"):
                self.store.patch(job["id"], translation_profile=self.profile_label(saved))
        else:
            saved = self.store.provider(job["provider_id"], secrets=True)
            if fingerprint(saved) != job["config_fingerprint"] and self.store.translations(job["id"]):
                raise ValueError("Les anciens paramètres ne sont pas enregistrés. Utilisez Adapter les paramètres dans Traductions pour reprendre sans réanalyser les fichiers.")
            self.store.patch(job["id"], provider_snapshot=self.store.seal_config(saved),
                             translation_profile=self.profile_label(saved), config_fingerprint=fingerprint(saved))
        # Freeze meaning (model/languages/glossary/temperature/endpoint), but allow
        # operational limits to change between waves without invalidating work.
        current = next((p for p in self.store.providers(secrets=True) if p["id"] == job["provider_id"]), None)
        if current:
            saved.update({key: current[key] for key in RUNTIME_FIELDS})
            if all(saved.get(key) == current.get(key) for key in ("kind", "base_url")):
                saved["api_key"] = current["api_key"]  # Same-endpoint key rotation.
        return providers.ProviderConfig.model_validate(saved).model_dump()

    def reconfigure(self, ids: list[str], provider_id: str, restart: bool = False) -> list[dict]:
        if not 1 <= len(ids) <= 500 or len(set(ids)) != len(ids):
            raise ValueError("Sélectionnez entre 1 et 500 traitements distincts.")
        if self.active in ids or any(jid in self.inflight for jid in ids):
            raise ValueError("Annulez le traitement et attendez la fin des requêtes en cours avant de l’adapter.")
        config = self.store.provider(provider_id, secrets=True)
        code = target_code(config)
        changes = {}
        for jid in ids:
            job = self.store.job(jid)
            known = self.store.open_config(job["provider_snapshot"]) if job.get("provider_snapshot") else None
            translated = self.store.translations(jid)
            if translated and not restart and known and (target_code(known) != code or known["source_language"].casefold() != config["source_language"].casefold()):
                raise ValueError("Les langues ont changé. Choisissez Recommencer la traduction pour éviter de mélanger les langues.")
            path = self.library.resolve(job["path"])
            if any(path.with_suffix(f".{code}.{ext}").exists() or path.with_suffix(f".{code}.{ext}").is_symlink() for ext in ("ass", "ssa", "srt")):
                raise ValueError("Un sous-titre cible existe déjà. Aucun export n’est remplacé.")
            warnings = list(job.get("warnings", []))
            if translated and not restart and (not known or fingerprint({k: v for k, v in known.items() if k not in RUNTIME_FIELDS}) != fingerprint({k: v for k, v in config.items() if k not in RUNTIME_FIELDS})):
                warning = "Reprise avec les paramètres actuels confirmée : les segments déjà validés ont été conservés ; vérifiez la cohérence de la traduction."
                if warning not in warnings:
                    warnings.append(warning)
            changes[jid] = {"provider_id": provider_id, "provider_snapshot": self.store.seal_config(config),
                            "translation_profile": self.profile_label(config), "config_fingerprint": fingerprint(config),
                            "status": "queued", "error": None, "cancel_requested": False, "sync_pending": False,
                            "sync_proposal": None, "write_hash": None, "batch_policy": {},
                            "adaptive_batch_size": providers.initial_batch_size(config), "warnings": [] if restart else warnings}
            if restart:
                changes[jid].update(done=0, progress=0, usage={})
        self.store.reconfigure_jobs(changes, restart)
        return [self.store.job(jid) for jid in ids]

    async def process(self, jid: str):
        job = self.store.job(jid)
        self.check_cancel(jid)
        config = self.job_config(job)
        work = self.store.folder / "work" / jid
        work.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.store.patch(jid, status="extracting", progress=max(2, job["progress"]), error=None)
        source, info = await asyncio.to_thread(self.library.extract, job["path"], job["track_id"], work)
        digest = hashlib.sha256(source.read_bytes()).hexdigest()
        if job.get("source_hash") and job["source_hash"] != digest:
            raise ValueError("La piste source a changé depuis le checkpoint. Créez un nouveau traitement.")
        doc = SubtitleDocument.load(source)
        self.validate_duration(doc, info["duration"])
        warnings = list(dict.fromkeys(doc.warnings + job.get("warnings", [])))
        track = next(t for t in info["tracks"] if t["id"] == job["track_id"])
        self.store.patch(jid, source_hash=digest, source_file=str(source), total=len(doc.segments), warnings=warnings,
                         source_track={k: v for k, v in track.items() if k != "path"})
        saved = self.store.translations(jid)
        translations = doc.resume_translations(saved)
        if len(saved) != len(translations):
            warnings.append(f"{len(saved)-len(translations)} ancienne(s) traduction(s) d’effets lettre par lettre écartée(s) de l’export ; source conservée, checkpoints archivés.")
        pending = [s for s in doc.segments if s["id"] not in translations]
        total = len(doc.segments)
        # Old per-profile minima are deliberately retired. A difficult cue is
        # evidence about that cue, not every episode/model request forever.
        initial = providers.initial_batch_size(config)
        state = job.get("batch_policy", {})
        limit = min(config["batch_size"], max(1, state.get("size", initial))) if state.get("version") == 2 else initial
        streak = 0
        self.store.patch(jid, adaptive_batch_size=limit, batch_policy={"version": 2, "size": limit})
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
            config = self.job_config(self.store.job(jid))
            limit = min(limit, config["batch_size"])
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
            failure = None
            reduced = None
            full_success = False
            try:
                for completed in asyncio.as_completed(tasks):
                    try:
                        result = await completed
                    except providers.ProviderError as error:
                        # A broken cue must not discard valid siblings/descendants.
                        partial = getattr(error, "translations", {})
                        candidate = translations | partial
                        doc.validate_translations(candidate, require_all=False)
                        self.store.checkpoint(jid, partial)
                        translations = candidate
                        record_usage(error.usage)
                        warnings.extend(w for w in error.warnings if w not in warnings)
                        failure = failure or error
                        self.store.patch(jid, done=len(translations), progress=5+int(80*len(translations)/max(total,1)), warnings=warnings)
                        continue
                    candidate = translations | result["translations"]
                    doc.validate_translations(candidate, require_all=False)
                    self.store.checkpoint(jid, result["translations"])
                    translations = candidate
                    if result.get("recovered"):
                        suggested = max(1, result["batch_size"])
                        reduced = min(reduced or limit, suggested)
                    else:
                        full_success = full_success or len(result["translations"]) >= limit
                    warnings.extend(w for w in result.get("warnings", []) if w not in warnings)
                    record_usage(result.get("usage", {}))
                    self.store.patch(jid, done=len(translations), progress=5+int(80*len(translations)/max(total,1)), warnings=warnings)
                    self.check_cancel(jid)
                if reduced is not None:
                    limit, streak = min(limit, reduced), 0
                elif full_success:
                    streak += 1
                    if streak >= 3:
                        limit = min(config["batch_size"], max(limit+1, (limit*3+1)//2))
                        streak = 0
                self.store.patch(jid, adaptive_batch_size=limit, batch_policy={"version": 2, "size": limit})
                if failure:
                    raise failure
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
        config = self.job_config(job)
        with tempfile.TemporaryDirectory(prefix="sillage-recheck-") as directory:
            current, info = await asyncio.to_thread(self.library.extract, job["path"], job["track_id"], Path(directory))
            if hashlib.sha256(current.read_bytes()).hexdigest() != job["source_hash"]:
                raise ValueError("La piste source a changé avant l’export. Aucun résultat publié.")
        self.validate_duration(doc, info["duration"], offset)
        translations = doc.resume_translations(self.store.translations(jid))
        doc.validate_translations(translations, require_all=True)
        content = doc.render(translations, offset_ms=offset)
        self.check_cancel(jid)
        self.store.patch(jid, status="writing", progress=96)
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
        warnings = list(dict.fromkeys(job["warnings"] + doc.warnings))
        self.store.patch(jid, status="review" if warnings else "completed", progress=100, output=str(path), error=None,
                         warnings=warnings, done=len(translations), total=len(doc.segments),
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

    async def delete(self, ids: list[str]) -> dict:
        if not 1 <= len(ids) <= 500 or len(set(ids)) != len(ids) or any(not re.fullmatch(r"[a-f0-9]{32}", jid) for jid in ids):
            raise ValueError("Sélectionnez entre 1 et 500 identifiants de traduction valides et distincts.")
        # Same event loop as the queue; no await between active-job checks and
        # the atomic SQLite deletion. Serialize with sync decisions as well.
        async with self.sync_lock:
            if self.active in ids or any(jid in self.inflight for jid in ids):
                raise ValueError("Le traitement termine son annulation. Réessayez dans un instant.")
            try:
                fd = os.open(self.store.folder / "work", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            except FileNotFoundError:
                fd = None
            try:
                self.store.delete_jobs(ids)
                if fd is None:
                    warnings = []
                else:
                    cleanup_fd, fd = fd, None
                    # The cleanup task owns its descriptor, including on HTTP
                    # cancellation; never close/reuse it beneath rmtree().
                    cleanup = asyncio.create_task(asyncio.to_thread(self._clean_work, ids, cleanup_fd))
                    warnings = await asyncio.shield(cleanup)
            finally:
                if fd is not None:
                    os.close(fd)
        return {"deleted": ids, "warnings": warnings}

    @staticmethod
    def _clean_work(ids: list[str], fd: int) -> list[str]:
        incomplete = False
        try:
            for jid in ids:
                try:
                    mode = os.stat(jid, dir_fd=fd, follow_symlinks=False).st_mode
                    if stat.S_ISDIR(mode):
                        shutil.rmtree(jid, dir_fd=fd)
                    else:
                        os.unlink(jid, dir_fd=fd)
                except FileNotFoundError:
                    pass
                except OSError:
                    incomplete = True
        finally:
            os.close(fd)
        return ["Historique supprimé, mais certains fichiers de travail restent présents. Vérifiez les permissions de /config/work."] if incomplete else []

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
        translations = doc.resume_translations(self.store.translations(jid))
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
        track = job.get("source_track")
        track_origin = "recorded" if track else "unavailable"
        if not track:
            # Legacy jobs keep the exact stream ID but have no metadata snapshot.
            # Current container labels are useful, but cannot certify past labels.
            try:
                info = self.library.inspect(job["path"])
                track = next((t for t in info["tracks"] if t["id"] == job["track_id"]), None)
                track = {k: v for k, v in track.items() if k != "path"} if track else None
                track_origin = "current" if track else "unavailable"
            except (ValueError, OSError, TimeoutExpired):
                pass
        return {"format": doc.format, "cues": cues, "warnings": list(dict.fromkeys(job["warnings"] + doc.warnings)), "timing_status": job["timing_status"],
                "source_track": track, "source_track_origin": track_origin,
                "stats": {"events": len(doc.cues), "translatable": len(doc.segments), "preserved": len(doc.cues) - len(doc.segments)},
                "sync_pending": job.get("sync_pending", False), "sync_proposal": job.get("sync_proposal")}
