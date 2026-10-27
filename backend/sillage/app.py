from __future__ import annotations

import asyncio
import hmac
import ipaddress
import os
import shutil
import tempfile
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field

from . import __version__
from .jobs import Worker
from .media import MediaLibrary
from .models import discover_models
from .providers import ProviderConfig, test_connection
from .storage import Store
from .subtitles import SubtitleDocument


class ScanRequest(BaseModel):
    path: str = Field(max_length=4096)
    recursive: bool = True


class PreviewRequest(BaseModel):
    path: str = Field(max_length=4096)
    track_id: str = Field(max_length=4096)


class JobItem(PreviewRequest):
    pass


class JobRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    items: list[JobItem] = Field(min_length=1, max_length=500)
    provider_id: str = Field(max_length=100)
    sync_mode: str = "preserve"
    offset_ms: int = Field(default=0, ge=-600000, le=600000)


class DeleteJobsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ids: list[str] = Field(min_length=1, max_length=500)


class ReconfigureJobsRequest(DeleteJobsRequest):
    provider_id: str = Field(max_length=128)
    restart: bool = False


class ModelListRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    id: str | None = Field(default=None, max_length=128)
    kind: str = Field(max_length=30)
    base_url: str = Field(default="", max_length=2048)
    api_key: str = Field(default="", max_length=8192, repr=False)


def create_app(config_dir: Path | None = None, roots: list[Path] | None = None, *, run_worker: bool = True) -> FastAPI:
    store = Store(config_dir or Path(os.environ.get("CONFIG_DIR", ".data")))
    library = MediaLibrary(roots or [Path(p) for p in os.environ.get("MEDIA_ROOTS", "/media").split(os.pathsep) if p])
    worker = Worker(store, library)
    access_key = os.environ.get("ACCESS_KEY", "")
    allowed_hosts = set(filter(None, os.environ.get("ALLOWED_HOSTS", "localhost,127.0.0.1,::1,testserver").split(",")))
    allowed_origins = set(filter(None, os.environ.get("ALLOWED_ORIGINS", "").split(",")))

    @asynccontextmanager
    async def lifespan(app):
        if run_worker:
            await worker.start()
        yield
        if run_worker:
            await worker.stop()

    app = FastAPI(title="Sillage", version=__version__, lifespan=lifespan, docs_url=None, redoc_url=None)
    app.state.store, app.state.library, app.state.worker = store, library, worker

    @app.middleware("http")
    async def boundaries(request: Request, call_next):
        host = request.url.hostname or ""
        host_allowed = host in allowed_hosts or "*" in allowed_hosts
        if not host_allowed:
            try:
                address = ipaddress.ip_address(host)
                host_allowed = address.is_private or address.is_loopback
            except ValueError:
                pass
        if not host_allowed:
            return JSONResponse({"detail": "Hôte non autorisé. Configurez ALLOWED_HOSTS pour votre nom local."}, status_code=400)
        origin = request.headers.get("origin")
        if origin and origin not in allowed_origins and urlsplit(origin).netloc != request.headers.get("host"):
            return JSONResponse({"detail": "Origine non autorisée."}, status_code=403)
        if request.url.path.startswith("/api/") and request.url.path not in {"/api/config", "/api/health"}:
            supplied = request.headers.get("x-access-key", "")
            if access_key and not hmac.compare_digest(supplied.encode(), access_key.encode()):
                return JSONResponse({"detail": "Clé d’accès requise ou incorrecte."}, status_code=401)
        try:
            response = await call_next(request)
        except (ValueError, FileNotFoundError, PermissionError) as exc:
            message = str(exc) if isinstance(exc, ValueError) else "Chemin inaccessible : vérifiez les montages et les permissions."
            return JSONResponse({"detail": message[:500]}, status_code=400)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "same-origin"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Content-Security-Policy"] = "default-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; font-src 'self'; connect-src 'self'; frame-ancestors 'none'"
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.exception_handler(RequestValidationError)
    async def invalid_request(request: Request, exc: RequestValidationError):
        # Default validation responses echo the input; a provider request can contain a secret.
        fields = list(dict.fromkeys(str(error["loc"][-1]) for error in exc.errors()))
        return JSONResponse({"detail": "Requête invalide. Vérifiez : " + ", ".join(fields)}, status_code=422)

    @app.get("/api/config")
    def public_config():
        return {"auth_required": bool(access_key)}

    @app.get("/api/health")
    def health():
        return {"status": "ok", "version": __version__, "tools": {tool: bool(shutil.which(tool)) for tool in ["ffmpeg", "ffprobe", "mkvextract", "ffsubsync"]}}

    @app.get("/api/browse")
    async def browse(path: str | None = None):
        return await asyncio.to_thread(library.browse, path)

    @app.post("/api/scan")
    async def scan(data: ScanRequest):
        return await asyncio.to_thread(library.scan, data.path, data.recursive)

    @app.post("/api/preview")
    async def preview(data: PreviewRequest):
        with tempfile.TemporaryDirectory(prefix="sillage-preview-") as directory:
            path, info = await asyncio.to_thread(library.extract, data.path, data.track_id, Path(directory))
            doc = SubtitleDocument.load(path)
            warnings = list(doc.warnings)
            try:
                worker.validate_duration(doc, info["duration"])
            except ValueError as exc:
                warnings.append(str(exc))
            track = next(t for t in info["tracks"] if t["id"] == data.track_id)
            return {"format": doc.format, "cues": doc.cues, "warnings": warnings,
                    "source_track": {k: v for k, v in track.items() if k != "path"}, "source_track_origin": "current",
                    "stats": {"events": len(doc.cues), "translatable": len(doc.segments), "preserved": len(doc.cues) - len(doc.segments)},
                    "timing_status": "Timings source — audio non vérifié"}

    @app.get("/api/providers")
    def list_providers():
        return store.providers()

    @app.post("/api/providers")
    async def save_provider(data: ProviderConfig):
        return store.save_provider(data.model_dump())

    @app.post("/api/providers/models")
    async def provider_models(data: ModelListRequest):
        # Reuse a saved secret only for its original provider and endpoint.
        # Catalogue lookup never saves a draft or returns a credential.
        config = ProviderConfig(kind=data.kind, base_url=data.base_url, api_key=data.api_key, model="model-discovery")
        if data.id and not config.api_key:
            saved = ProviderConfig.model_validate(store.provider(data.id, secrets=True))
            if saved.kind != config.kind or saved.base_url != config.base_url:
                raise ValueError("Ajoutez une clé pour ce nouveau fournisseur ou cette nouvelle URL.")
            config = config.model_copy(update={"api_key": saved.api_key})
        return await discover_models(config)

    @app.delete("/api/providers/{pid}")
    def delete_provider(pid: str):
        store.delete_provider(pid)
        return {"ok": True}

    @app.post("/api/providers/{pid}/test")
    async def check_provider(pid: str):
        message = await test_connection(store.provider(pid, secrets=True))
        return {"ok": True, "message": message}

    @app.get("/api/jobs")
    def list_jobs():
        # Checkpoint storage paths and hashes are backend implementation details.
        return [public_job(j) for j in store.jobs()]

    @app.post("/api/jobs")
    async def create_jobs(data: JobRequest):
        return [public_job(j) for j in await worker.create(data.model_dump())]

    @app.post("/api/jobs/delete")
    async def delete_jobs(data: DeleteJobsRequest):
        return await worker.delete(data.ids)

    @app.post("/api/jobs/reconfigure")
    async def reconfigure_jobs(data: ReconfigureJobsRequest):
        return [public_job(j) for j in worker.reconfigure(data.ids, data.provider_id, data.restart)]

    @app.post("/api/jobs/{jid}/reanalyze")
    async def reanalyze_job(jid: str):
        # Inspection only. Keep the existing job/checkpoints and never contact
        # a provider or silently queue another generation.
        job = store.job(jid)
        return await asyncio.to_thread(library.inspect, job["path"])

    @app.post("/api/jobs/{jid}/cancel")
    async def cancel_job(jid: str):
        return public_job(worker.cancel(jid))

    @app.post("/api/jobs/{jid}/resume")
    async def resume_job(jid: str):
        return public_job(worker.resume(jid))

    @app.get("/api/jobs/{jid}/preview")
    async def job_preview(jid: str):
        return await asyncio.to_thread(worker.preview, jid)

    @app.post("/api/jobs/{jid}/sync/accept")
    async def accept_sync(jid: str):
        return public_job(await worker.decide_sync(jid, True))

    @app.post("/api/jobs/{jid}/sync/reject")
    async def reject_sync(jid: str):
        return public_job(await worker.decide_sync(jid, False))

    @app.get("/api/jobs/{jid}/download")
    def download(jid: str):
        job = store.job(jid)
        if not job.get("output"):
            raise HTTPException(404, "Aucun fichier exporté pour ce traitement.")
        path = library.resolve(job["output"])
        if path.suffix not in {".ass", ".ssa", ".srt"}:
            raise HTTPException(400, "Type de sortie interdit.")
        return FileResponse(path, filename=path.name, media_type="application/octet-stream")

    dist = Path(os.environ.get("FRONTEND_DIST", str(Path(__file__).resolve().parents[2] / "frontend" / "dist")))
    if dist.is_dir():
        app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")
        @app.get("/{path:path}")
        def frontend(path: str):
            if path.startswith("api/"):
                raise HTTPException(404, "Route API introuvable.")
            candidate = (dist / path).resolve()
            if candidate.is_relative_to(dist.resolve()) and candidate.is_file():
                return FileResponse(candidate)
            return FileResponse(dist / "index.html")
    return app


def public_job(job: dict) -> dict:
    hidden = {"source_file", "source_hash", "config_fingerprint", "write_hash", "cancel_requested", "provider_snapshot", "batch_policy"}
    return {k: v for k,v in job.items() if k not in hidden}
