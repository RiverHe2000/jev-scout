"""Local application API and static frontend hosting."""

from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager
from typing import Literal
from urllib.parse import urlparse

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware

from . import __version__
from .config import PROJECT_ROOT, Settings
from .exports import export_entries
from .jobs import JobRunner, seed_demo
from .schemas import (
    AnnotationInput,
    ArchiveInput,
    EvaluateInput,
    IngestInput,
    ProfileInput,
    ProfileUpdate,
    ReadingInput,
)
from .store import ConflictError, MissingError, Store


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.load()
    store = Store(settings.database_path)
    runner = JobRunner(store, settings)
    seed_lock = asyncio.Lock()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if settings.autoseed and not store.profiles(include_archived=True):
            await seed_demo(store, settings)
        if settings.worker_enabled:
            await runner.start()
        yield
        await runner.stop()

    app = FastAPI(title="Jev Scout", version=__version__, lifespan=lifespan)
    app.state.store = store
    app.state.settings = settings
    app.state.runner = runner
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["localhost", "127.0.0.1", "[::1]", "testserver"])

    @app.middleware("http")
    async def local_request_boundary(request: Request, call_next):
        if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
            origin = request.headers.get("origin")
            if origin:
                try:
                    parsed = urlparse(origin)
                    valid_origin = (
                        parsed.scheme in {"http", "https"}
                        and parsed.hostname in {"localhost", "127.0.0.1", "::1", "testserver"}
                        and parsed.port in {settings.port, 5173, 5174, 4173}
                        and not any(
                            (
                                parsed.username,
                                parsed.password,
                                parsed.path,
                                parsed.params,
                                parsed.query,
                                parsed.fragment,
                            )
                        )
                    )
                except ValueError:
                    valid_origin = False
                if not valid_origin:
                    return JSONResponse(
                        {"detail": "This local workspace does not accept changes from other websites."},
                        status_code=403,
                    )
            if request.headers.get("sec-fetch-site") == "cross-site":
                return JSONResponse({"detail": "Cross-site changes are not allowed."}, status_code=403)
            size = request.headers.get("content-length")
            if size and (not size.isdigit() or int(size) > 262144):
                return JSONResponse({"detail": "Request body exceeds the workspace limit."}, status_code=413)
            # Content-Length can be absent (chunked transfer) or inaccurate.
            # Bound bytes before FastAPI's JSON parser allocates the input tree.
            body = bytearray()
            async for chunk in request.stream():
                body.extend(chunk)
                if len(body) > 262144:
                    return JSONResponse(
                        {"detail": "Request body exceeds the workspace limit."}, status_code=413
                    )
            request._body = bytes(body)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Frame-Options"] = "DENY"
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.exception_handler(MissingError)
    async def missing_handler(request: Request, exc: MissingError):
        return JSONResponse({"detail": str(exc)}, status_code=404)

    @app.exception_handler(ConflictError)
    async def conflict_handler(request: Request, exc: ConflictError):
        return JSONResponse({"detail": str(exc)}, status_code=409)

    def active_profile(profile_id: str) -> dict:
        profile = store.profile(profile_id)
        if profile["archived"]:
            raise HTTPException(409, "This research card is archived. Restore it before making changes.")
        return profile

    def ensure_mode(mode: str):
        if mode not in settings.available_modes:
            message = (
                "Configure TYPESAFE_API_KEY or OPENROUTER_API_KEY in .env and restart to use Jev."
                if mode == "jev"
                else "Configure JEV_SCOUT_LLM_BASE_URL and JEV_SCOUT_LLM_MODEL in .env and restart to use an LLM."
            )
            raise HTTPException(409, message)

    @app.get("/api/health")
    def health():
        return {"status": "ok", "version": __version__}

    @app.get("/api/settings")
    def public_settings():
        return settings.public()

    @app.get("/api/profiles")
    def profiles(include_archived: bool = False):
        return {"items": store.profiles(include_archived)}

    @app.post("/api/profiles", status_code=201)
    def create_profile(body: ProfileInput):
        return store.create_profile(body.model_dump())

    @app.put("/api/profiles/{profile_id}")
    def update_profile(profile_id: str, body: ProfileUpdate):
        active_profile(profile_id)
        return store.update_profile(
            profile_id, body.model_dump(exclude={"expected_version"}), body.expected_version
        )

    @app.post("/api/profiles/{profile_id}/archive")
    def archive_profile(profile_id: str, body: ArchiveInput | None = None):
        store.archive_profile(profile_id, body.archived if body else True)
        return {"ok": True}

    @app.get("/api/papers")
    def papers(
        profile_id: str,
        route: Literal["all", "read", "skim", "review", "later"] = "all",
        saved: bool = False,
        status: Literal["all", "unread", "reading", "done"] = "all",
        q: str = Query(default="", max_length=300),
        sort: Literal["priority", "newest"] = "priority",
        limit: int = Query(default=50, ge=1, le=200),
        offset: int = Query(default=0, ge=0),
    ):
        return store.list_papers(
            profile_id, route=route, saved=saved, status=status, q=q, sort=sort, limit=limit, offset=offset
        )

    @app.get("/api/papers/{paper_id}")
    def paper_detail(paper_id: str, profile_id: str):
        matches = [entry for entry in store.entries(profile_id) if entry["id"] == paper_id]
        if not matches:
            raise MissingError("Paper not found.")
        return {
            **matches[0],
            "versions": store.paper_versions(paper_id),
            "decisions": store.decision_history(paper_id, profile_id),
            "activity": store.activity(profile_id, paper_id, 30),
        }

    @app.patch("/api/papers/{paper_id}/reading")
    def reading(paper_id: str, body: ReadingInput):
        active_profile(body.profile_id)
        changes = body.model_dump(exclude={"profile_id"}, exclude_unset=True)
        try:
            return store.update_reading(paper_id, body.profile_id, changes)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from None

    @app.post("/api/ingest", status_code=202)
    def ingest(body: IngestInput):
        from .arxiv import ArxivError, normalize_arxiv_id

        active_profile(body.profile_id)
        ensure_mode(body.mode)
        payload = body.model_dump()
        if payload["ids"]:
            try:
                payload["ids"] = list(dict.fromkeys(normalize_arxiv_id(value) for value in payload["ids"]))
            except (ArxivError, ValueError) as exc:
                raise HTTPException(422, str(exc)) from None
        job = store.create_job("ingest", payload)
        runner.wake.set()
        return job

    @app.post("/api/evaluate", status_code=202)
    def evaluate(body: EvaluateInput):
        active_profile(body.profile_id)
        ensure_mode(body.mode)
        if body.paper_ids is not None:
            if not body.paper_ids:
                raise HTTPException(
                    422, "Select at least one paper or omit paper_ids to evaluate the collection."
                )
            found = {paper["id"] for paper in store.papers(body.paper_ids)}
            if found != set(body.paper_ids):
                raise HTTPException(404, "One or more selected papers no longer exist.")
        job = store.create_job("evaluate", body.model_dump())
        runner.wake.set()
        return job

    @app.get("/api/jobs")
    def jobs():
        return {"items": store.jobs()}

    @app.post("/api/jobs/{job_id}/cancel")
    async def cancel_job(job_id: str):
        result = store.cancel_job(job_id)
        if result["status"] == "cancelled":
            runner.interrupt_cancelled_job(job_id)
        return result

    @app.post("/api/jobs/{job_id}/retry", status_code=202)
    def retry_job(job_id: str):
        previous = store.job(job_id, internal=True)
        if previous["status"] not in {"failed", "cancelled"}:
            raise HTTPException(409, "Only failed or cancelled jobs can be retried.")
        active_profile(previous["profile_id"])
        ensure_mode(previous["mode"])
        job = store.create_job(previous["kind"], {**previous["payload"], "_retry_from": previous["id"]})
        runner.wake.set()
        return job

    @app.get("/api/stats")
    def stats(profile_id: str):
        return store.stats(profile_id)

    @app.get("/api/activity")
    def activity(profile_id: str | None = None):
        if profile_id:
            store.profile(profile_id)
        return {"items": store.activity(profile_id)}

    @app.get("/api/export")
    def export(
        profile_id: str,
        format: Literal["bibtex", "markdown", "json"] = "bibtex",
        scope: Literal["saved", "all"] = "saved",
    ):
        profile = store.profile(profile_id)
        entries = store.list_papers(profile_id, saved=scope == "saved", limit=100000)["items"]
        content, mime, filename = export_entries(entries, profile, format)
        return Response(
            content, media_type=mime, headers={"Content-Disposition": f'attachment; filename="{filename}"'}
        )

    @app.post("/api/demo/load")
    async def load_demo():
        async with seed_lock:
            return await seed_demo(store, settings)

    @app.get("/api/evaluation")
    def evaluation():
        path = PROJECT_ROOT / "artifacts" / "evaluation" / "report.json"
        if not path.exists():
            return {
                "available": False,
                "message": "No benchmark has been run in this installation. Run the evaluation command to create a measured report.",
            }
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            return {"available": False, "message": "The local benchmark report could not be read."}

    @app.get("/api/annotations")
    def annotations():
        return {"items": store.annotations()}

    @app.post("/api/annotations")
    def annotate(body: AnnotationInput):
        active_profile(body.profile_id)
        store.annotate(body.model_dump())
        return {"ok": True}

    dist = PROJECT_ROOT / "frontend" / "dist"
    if (dist / "assets").exists():
        app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def frontend(path: str):
        if path.startswith("api/"):
            raise HTTPException(404, "API endpoint not found.")
        candidate = (dist / path).resolve()
        if candidate.is_relative_to(dist.resolve()) and candidate.is_file():
            return FileResponse(candidate)
        if (dist / "index.html").exists():
            return FileResponse(dist / "index.html")
        return JSONResponse(
            {
                "message": "Jev Scout API is running. Build the frontend with pnpm --dir frontend build, then restart the server.",
                "docs": "/docs",
            },
            status_code=200,
        )

    return app
