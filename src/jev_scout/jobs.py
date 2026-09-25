"""A persisted, cancellable queue with input-bound decision caching."""

from __future__ import annotations

import asyncio
import logging
from contextlib import suppress

from .config import Settings
from .schemas import ProfileInput
from .store import JobCancelledError, Store, digest, now

log = logging.getLogger(__name__)


def cache_key(paper: dict, profile: dict, mode: str, settings: Settings) -> str:
    from .engine import QUESTION_VERSION

    return digest(
        {
            "paper": paper["content_hash"],
            "profile_id": profile["id"],
            "profile_version": profile["version"],
            "profile": {key: profile[key] for key in ProfileInput.model_fields},
            "mode": mode,
            "model": settings.resolved_jev_model
            if mode == "jev"
            else settings.llm_model
            if mode == "llm"
            else "lexical-v1",
            "endpoint": settings.jev_endpoint
            if mode == "jev"
            else settings.llm_base_url
            if mode == "llm"
            else "local",
            "question_version": QUESTION_VERSION,
            "pricing": settings.input_price if mode == "jev" else settings.llm_input_price,
        }
    )


async def evaluate_one(
    store: Store,
    settings: Settings,
    paper: dict,
    profile: dict,
    mode: str,
    force: bool = False,
    *,
    job_id: str | None = None,
) -> dict:
    from .engine import evaluate

    key = cache_key(paper, profile, mode, settings)
    if job_id is not None:
        completed = store.completed_job_decision(job_id, key)
        if completed:
            activated = store.activate_cached_decision(completed["id"], job_id=job_id)
            if activated:
                return activated
    # Floating model aliases may resolve to a new model without the input changing.
    floating = mode == "jev" and any(alias in settings.resolved_jev_model for alias in ("latest", "preview"))
    if not force and not floating:
        cached = store.cached_decision(key)
        if cached:
            activated = store.activate_cached_decision(cached["id"], job_id=job_id)
            if activated:
                return activated
    kwargs = {"mode": mode, "timeout": settings.model_timeout}
    if mode == "jev":
        kwargs.update(
            api_key=settings.typesafe_key or settings.openrouter_key,
            model=settings.resolved_jev_model,
            endpoint=settings.jev_endpoint,
            price_per_million_input=settings.input_price,
        )
    elif mode == "llm":
        kwargs.update(
            api_key=settings.llm_key or None,
            model=settings.llm_model,
            base_url=settings.llm_base_url,
            price_per_million_input=settings.llm_input_price,
        )
    result = await evaluate(paper, profile, **kwargs)
    return store.save_decision(paper, profile, result, key, job_id=job_id)


async def seed_demo(store: Store, settings: Settings) -> dict:
    from .fixtures import load_papers, load_profiles

    profiles = []
    for fixture in load_profiles():
        key = fixture.get("fixture_key") or fixture.get("id") or fixture["name"]
        payload = ProfileInput.model_validate(
            {key: value for key, value in fixture.items() if key in ProfileInput.model_fields}
        ).model_dump()
        profiles.append(store.create_profile(payload, fixture_key=key))
    papers = [store.ingest_paper(paper) for paper in load_papers()]
    for profile in profiles:
        if profile["archived"]:
            continue
        for paper in papers:
            # Idempotent seeding does not supersede a live or user-selected model decision.
            existing = store.decision_history(paper["id"], profile["id"])
            if not any(not item["stale"] for item in existing):
                await evaluate_one(store, settings, paper, profile, "baseline")
    return {
        "papers": len(papers),
        "profiles": len(profiles),
        "message": "Loaded attributed public papers with a local keyword baseline. No Jev API calls were made.",
    }


class JobRunner:
    def __init__(self, store: Store, settings: Settings):
        self.store = store
        self.settings = settings
        self.task: asyncio.Task | None = None
        self.active_task: asyncio.Task | None = None
        self.active_job_id: str | None = None
        self.wake = asyncio.Event()

    async def start(self):
        self.store.recover_jobs()
        self.task = asyncio.create_task(self.run(), name="scout-job-runner")

    async def stop(self):
        if self.task:
            self.task.cancel()
            with suppress(asyncio.CancelledError):
                await self.task

    async def run(self):
        while True:
            job = self.store.next_job()
            if job:
                self.active_job_id = job["id"]
                self.active_task = asyncio.create_task(self.process(job))
                try:
                    await self.active_task
                except asyncio.CancelledError:
                    if asyncio.current_task().cancelling() or not self.cancelled(job["id"]):
                        raise
                finally:
                    self.active_task = None
                    self.active_job_id = None
                continue
            self.wake.clear()
            with suppress(TimeoutError):
                await asyncio.wait_for(self.wake.wait(), timeout=0.75)

    def cancelled(self, job_id: str) -> bool:
        return self.store.job(job_id)["status"] == "cancelled"

    def interrupt_cancelled_job(self, job_id: str):
        """Called on the app event loop after durable cancellation is recorded."""
        if self.active_job_id == job_id and self.active_task:
            self.active_task.cancel()

    async def process(self, job: dict):
        from .arxiv import ArxivError, fetch_papers
        from .engine import EngineError

        job_id, payload = job["id"], job["payload"]
        try:
            profile = self.store.profile(job["profile_id"])
            if profile["archived"]:
                raise ValueError("Restore this research card before processing papers.")
            if job["mode"] not in self.settings.available_modes:
                raise ValueError("The selected model is not configured. Update .env and restart the server.")
            if job["kind"] == "ingest":
                if "_imported_paper_ids" in payload:
                    papers = self.store.papers(payload["_imported_paper_ids"])
                else:
                    self.store.job_update(job_id, message="Fetching public metadata from arXiv.")
                    imported = await fetch_papers(
                        query=payload.get("query"),
                        ids=payload.get("ids"),
                        max_results=payload.get("max_results", 30),
                    )
                    if self.cancelled(job_id):
                        return
                    papers = [self.store.ingest_paper(paper) for paper in imported]
                    papers = list({paper["id"]: paper for paper in papers}.values())
                    self.store.set_imported_papers(job_id, [paper["id"] for paper in papers])
            else:
                papers = self.store.papers(payload.get("paper_ids"))
            self.store.job_update(
                job_id, total=len(papers), completed=0, failed=0, message=f"Preparing {len(papers)} papers."
            )
            failed = completed = cached = 0
            errors = []
            for paper in papers:
                if self.cancelled(job_id):
                    return
                self.store.job_update(
                    job_id, message=f"Reading {completed + failed + 1}/{len(papers)}: {paper['title'][:120]}"
                )
                try:
                    result = await evaluate_one(
                        self.store,
                        self.settings,
                        paper,
                        profile,
                        job["mode"],
                        payload.get("force", False),
                        job_id=job_id,
                    )
                    completed += 1
                    cached += int(result.get("cache_hit", False))
                except (EngineError, ValueError) as exc:
                    failed += 1
                    errors.append(str(exc)[:500])
                self.store.job_update(job_id, completed=completed, failed=failed)
                await asyncio.sleep(0)
            message = f"Finished: {completed} evaluated, {cached} reused, {failed} failed."
            if not papers:
                message = "No matching papers were found. Try a broader query or import specific arXiv IDs."
            self.store.job_update(
                job_id,
                status="failed" if failed else "completed",
                message=message,
                error="; ".join(dict.fromkeys(errors))[:1800] or None,
                finished_at=now(),
            )
        except asyncio.CancelledError:
            # A process interruption leaves the persisted running job resumable on the next startup.
            raise
        except JobCancelledError:
            return
        except (ArxivError, EngineError, ValueError) as exc:
            self.store.job_update(
                job_id,
                status="failed",
                error=str(exc)[:1800],
                message="Processing stopped; completed results remain available.",
                finished_at=now(),
            )
        except Exception as exc:
            log.error("Job failed with %s", type(exc).__name__)
            self.store.job_update(
                job_id,
                status="failed",
                error="An internal processing error occurred. Check local logs and retry.",
                message="Processing stopped.",
                finished_at=now(),
            )
