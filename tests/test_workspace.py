"""State-transition and integration checks for the user-visible workspace."""

from __future__ import annotations

import asyncio
import json
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

from jev_scout.api import create_app
from jev_scout.config import Settings
from jev_scout.jobs import JobRunner, evaluate_one, seed_demo
from jev_scout.store import ConflictError, Store


@pytest.fixture
def settings(tmp_path):
    return Settings(data_dir=tmp_path, autoseed=False, worker_enabled=False)


@pytest.fixture
def store(settings):
    return Store(settings.database_path)


@pytest.fixture
def profile_data():
    return {
        "name": "Memory",
        "question": "Which studies evaluate agent memory failures?",
        "preferences": [],
        "exclusions": "",
        "keywords": ["memory", "agent"],
        "seed_papers": [],
        "daily_limit": 8,
        "confidence_threshold": 0.65,
    }


@pytest.fixture
def profile(store, profile_data):
    return store.create_profile(profile_data)


@pytest.fixture
def paper_data():
    return {
        "arxiv_id": "2401.12345",
        "version": 1,
        "title": "Memory for agents",
        "authors": ["Fixture Author"],
        "abstract": "We evaluate memory in language agents. A comparison finds failures in recall.",
        "categories": ["cs.AI"],
        "published": "2024-01-01T00:00:00+00:00",
        "updated": "2024-01-01T00:00:00+00:00",
        "source_url": "https://arxiv.org/abs/2401.12345v1",
        "pdf_url": "https://arxiv.org/pdf/2401.12345v1",
        "source": "test_fixture",
    }


@pytest.fixture
def paper(store, paper_data):
    return store.ingest_paper(paper_data)


def test_profile_edits_are_optimistic_and_keep_history(store, profile, profile_data):
    updated = store.update_profile(profile["id"], {**profile_data, "name": "Changed"}, expected_version=1)
    assert updated["version"] == 2
    with pytest.raises(ConflictError):
        store.update_profile(profile["id"], profile_data, expected_version=1)
    assert store.profile(profile["id"])["name"] == "Changed"
    with store.connect() as con:
        rows = con.execute("SELECT * FROM profile_versions ORDER BY version").fetchall()
    assert [json.loads(row["payload"])["name"] for row in rows] == ["Memory", "Changed"]


def test_paper_versions_preserve_old_input_and_do_not_roll_back(store, paper, paper_data):
    assert store.ingest_paper(paper_data)["id"] == paper["id"]
    assert len(store.paper_versions(paper["id"])) == 1
    second = store.ingest_paper(
        {
            **paper_data,
            "version": 2,
            "abstract": "New memory findings.",
            "updated": "2024-02-01T00:00:00+00:00",
        }
    )
    store.ingest_paper(paper_data)
    assert store.paper(paper["id"])["version"] == 2
    assert second["content_hash"] != paper["content_hash"]
    assert {item["abstract"] for item in store.paper_versions(paper["id"])} == {
        paper_data["abstract"],
        "New memory findings.",
    }


@pytest.mark.asyncio
async def test_cache_reuse_and_profile_revision_invalidation(store, settings, paper, profile, profile_data):
    first = await evaluate_one(store, settings, paper, profile, "baseline")
    second = await evaluate_one(store, settings, paper, profile, "baseline")
    assert first["id"] == second["id"] and second["cache_hit"]
    new_profile = store.update_profile(profile["id"], {**profile_data, "keywords": ["quantization"]}, 1)
    assert store.entries(profile["id"])[0]["decision"]["stale"]
    assert store.list_papers(profile["id"], route="review")["total"] == 1
    third = await evaluate_one(store, settings, paper, new_profile, "baseline")
    assert third["id"] != first["id"] and not third["stale"]
    assert third["rank_score"] < first["rank_score"]


@pytest.mark.asyncio
async def test_delayed_response_never_becomes_current_after_profile_edit(
    store, settings, paper, profile, profile_data, monkeypatch
):
    from jev_scout import engine

    original = engine.evaluate

    async def changing_input(*args, **kwargs):
        store.update_profile(profile["id"], {**profile_data, "name": "Edited while running"}, 1)
        return await original(*args, **kwargs)

    monkeypatch.setattr(engine, "evaluate", changing_input)
    result = await evaluate_one(store, settings, paper, profile, "baseline")
    assert result["stale"]
    assert store.list_papers(profile["id"], route="review")["counts"]["review"] == 1


@pytest.mark.asyncio
async def test_delayed_response_after_new_paper_version_is_stale(
    store, settings, paper, profile, paper_data, monkeypatch
):
    from jev_scout import engine

    original = engine.evaluate

    async def changing_input(*args, **kwargs):
        store.ingest_paper({**paper_data, "version": 2, "abstract": "A different result."})
        return await original(*args, **kwargs)

    monkeypatch.setattr(engine, "evaluate", changing_input)
    result = await evaluate_one(store, settings, paper, profile, "baseline")
    assert result["stale"]
    assert store.entries(profile["id"])[0]["version"] == 2


def test_reading_edits_do_not_overwrite_unmentioned_fields(store, paper, profile):
    store.update_reading(
        paper["id"], profile["id"], {"note": "Important finding", "saved": True, "feedback": "useful"}
    )
    updated = store.update_reading(paper["id"], profile["id"], {"status": "done", "feedback": None})
    assert updated == {"note": "Important finding", "saved": True, "feedback": None, "status": "done"}


def test_reading_is_isolated_between_research_profiles(store, paper, profile, profile_data):
    other = store.create_profile({**profile_data, "name": "Separate"})
    store.update_reading(paper["id"], profile["id"], {"saved": True, "note": "Private to this card"})
    assert store.entries(other["id"])[0]["reading"]["note"] == ""
    assert not store.entries(other["id"])[0]["reading"]["saved"]


def test_duplicate_active_jobs_coalesce_and_cancel_is_terminal(store, profile):
    payload = {"profile_id": profile["id"], "mode": "baseline", "force": False, "paper_ids": None}
    first = store.create_job("evaluate", payload)
    assert store.create_job("evaluate", payload)["id"] == first["id"]
    store.next_job()
    store.cancel_job(first["id"])
    store.job_update(first["id"], status="completed", message="late worker")
    assert store.job(first["id"])["status"] == "cancelled"
    assert store.create_job("evaluate", payload)["id"] != first["id"]


def test_running_jobs_recover_after_restart(store, profile):
    job = store.create_job("evaluate", {"profile_id": profile["id"], "mode": "baseline"})
    store.next_job()
    Store(store.path).recover_jobs()
    assert store.job(job["id"])["status"] == "queued"


@pytest.mark.asyncio
async def test_runner_persists_partial_failure_and_retry_reuses_success(
    store, settings, profile, paper, paper_data, monkeypatch
):
    from jev_scout import engine

    other = store.ingest_paper({**paper_data, "arxiv_id": "2401.99999", "title": "Another memory paper"})
    original = engine.evaluate

    async def partial(candidate, *args, **kwargs):
        if candidate["id"] == other["id"]:
            raise engine.EngineError("A temporary test failure.")
        return await original(candidate, *args, **kwargs)

    monkeypatch.setattr(engine, "evaluate", partial)
    job = store.create_job("evaluate", {"profile_id": profile["id"], "mode": "baseline"})
    runner = JobRunner(store, settings)
    await runner.process(store.next_job())
    result = store.job(job["id"])
    assert (result["status"], result["completed"], result["failed"]) == ("failed", 1, 1)
    assert len(store.decision_history(paper["id"], profile["id"])) == 1
    monkeypatch.setattr(engine, "evaluate", original)
    retry = store.create_job("evaluate", {"profile_id": profile["id"], "mode": "baseline"})
    await runner.process(store.next_job())
    assert store.job(retry["id"])["status"] == "completed"
    assert len(store.decision_history(paper["id"], profile["id"])) == 1


def test_api_configuration_never_exposes_credentials(settings):
    settings = replace(
        settings,
        typesafe_key="private-typesafe-sentinel",
        openrouter_key="private-router-sentinel",
        llm_key="private-llm-sentinel",
    )
    with TestClient(create_app(settings)) as client:
        response = client.get("/api/settings")
        assert response.json()["jev_configured"]
        assert "sentinel" not in response.text


def test_api_blocks_unconfigured_models_cross_site_writes_and_unknown_fields(settings, profile_data):
    with TestClient(create_app(settings)) as client:
        profile = client.post("/api/profiles", json=profile_data).json()
        assert (
            client.post("/api/evaluate", json={"profile_id": profile["id"], "mode": "jev"}).status_code == 409
        )
        assert (
            client.post(
                "/api/profiles", json=profile_data, headers={"Origin": "https://evil.example"}
            ).status_code
            == 403
        )
        assert client.post("/api/profiles", json={**profile_data, "api_key": "unwanted"}).status_code == 422
        assert (
            client.post("/api/profiles", json={**profile_data, "confidence_threshold": 1.5}).status_code
            == 422
        )
        assert client.get("/api/settings", headers={"Host": "evil.example"}).status_code == 400


def test_api_update_conflicts_and_archive_restore(settings, profile_data):
    with TestClient(create_app(settings)) as client:
        profile = client.post("/api/profiles", json=profile_data).json()
        url = "/api/profiles/" + profile["id"]
        assert (
            client.put(url, json={**profile_data, "name": "Version two", "expected_version": 1}).status_code
            == 200
        )
        assert client.put(url, json={**profile_data, "expected_version": 1}).status_code == 409
        assert client.post(url + "/archive").status_code == 200
        assert client.get("/api/profiles").json()["items"] == []
        assert client.post(url + "/archive", json={"archived": False}).status_code == 200
        assert len(client.get("/api/profiles").json()["items"]) == 1


def test_api_reading_export_and_filter_flow(settings, profile_data, paper_data):
    app = create_app(settings)
    with TestClient(app) as client:
        profile = client.post("/api/profiles", json=profile_data).json()
        paper = app.state.store.ingest_paper(paper_data)
        payload = {
            "profile_id": profile["id"],
            "saved": True,
            "note": "Keep this evidence",
            "status": "reading",
        }
        response = client.patch(f"/api/papers/{paper['id']}/reading", json=payload)
        assert response.status_code == 200
        query = {"profile_id": profile["id"], "saved": True, "q": "memory"}
        assert client.get("/api/papers", params=query).json()["total"] == 1
        exported = client.get("/api/export", params={"profile_id": profile["id"], "format": "bibtex"})
        assert "Memory for agents" in exported.text and "@misc{" in exported.text
        assert "attachment" in exported.headers["content-disposition"]
        detail = client.get(f"/api/papers/{paper['id']}", params={"profile_id": profile["id"]}).json()
        assert detail["reading"]["note"] == "Keep this evidence" and len(detail["versions"]) == 1
        assert (
            client.patch(
                f"/api/papers/{paper['id']}/reading", json={"profile_id": profile["id"], "note": None}
            ).status_code
            == 422
        )


@pytest.mark.asyncio
async def test_demo_load_is_idempotent_and_preserves_user_work(store, settings):
    first = await seed_demo(store, settings)
    profile = store.profiles()[0]
    paper = store.papers()[0]
    store.update_reading(paper["id"], profile["id"], {"saved": True, "note": "Preserve me"})
    first_count = store.stats(profile["id"])["decisions"]
    second = await seed_demo(store, settings)
    assert first == second
    assert store.entries(profile["id"])[0]["reading"]["note"] == "Preserve me"
    assert store.stats(profile["id"])["decisions"] == first_count


def test_backup_is_consistent_and_never_mutates_source(store, profile, tmp_path):
    destination = tmp_path / "backup.sqlite3"
    store.backup(destination)
    backup = Store(destination)
    assert backup.profile(profile["id"]) == store.profile(profile["id"])


def test_model_configuration_handles_openrouter_and_local(settings):
    configured = replace(settings, openrouter_key="sentinel", llm_base_url="http://127.0.0.1:8766/v1")
    assert configured.jev_endpoint == "https://openrouter.ai/api/alpha/decisions"
    assert configured.resolved_jev_model == "typesafe/jev-1.13"
    assert configured.public()["llm_provider"] == "local"
    assert configured.available_modes == ["baseline", "jev", "llm"]


@pytest.mark.asyncio
async def test_cancellation_fences_a_model_response_already_in_flight(
    store, settings, profile, paper, monkeypatch
):
    from jev_scout import engine

    started, release = asyncio.Event(), asyncio.Event()
    original = engine.evaluate

    async def delayed(*args, **kwargs):
        started.set()
        await release.wait()
        return await original(*args, **kwargs)

    monkeypatch.setattr(engine, "evaluate", delayed)
    job = store.create_job("evaluate", {"profile_id": profile["id"], "mode": "baseline"})
    task = asyncio.create_task(JobRunner(store, settings).process(store.next_job()))
    await asyncio.wait_for(started.wait(), 2)
    store.cancel_job(job["id"])
    release.set()
    await asyncio.wait_for(task, 2)
    assert store.job(job["id"])["status"] == "cancelled"
    assert store.decision_history(paper["id"], profile["id"]) == []


@pytest.mark.asyncio
async def test_active_cancellation_interrupts_provider_and_worker_accepts_next_job(
    store, settings, profile, paper, monkeypatch
):
    from jev_scout import engine

    started, interrupted, resumed = asyncio.Event(), asyncio.Event(), asyncio.Event()
    original = engine.evaluate
    calls = 0

    async def delayed(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                interrupted.set()
        result = await original(*args, **kwargs)
        resumed.set()
        return result

    monkeypatch.setattr(engine, "evaluate", delayed)
    first = store.create_job("evaluate", {"profile_id": profile["id"], "mode": "baseline"})
    runner = JobRunner(store, settings)
    await runner.start()
    try:
        await asyncio.wait_for(started.wait(), 2)
        store.cancel_job(first["id"])
        runner.interrupt_cancelled_job(first["id"])
        await asyncio.wait_for(interrupted.wait(), 2)
        second = store.create_job("evaluate", {"profile_id": profile["id"], "mode": "baseline"})
        runner.wake.set()
        await asyncio.wait_for(resumed.wait(), 2)
        await asyncio.sleep(0.05)
        assert store.job(second["id"])["status"] == "completed"
        assert len(store.decision_history(paper["id"], profile["id"])) == 1
    finally:
        await asyncio.wait_for(runner.stop(), 2)


@pytest.mark.asyncio
async def test_restart_of_forced_job_reuses_its_completed_work(
    store, settings, profile, paper, paper_data, monkeypatch
):
    from jev_scout import engine

    second = store.ingest_paper({**paper_data, "arxiv_id": "2401.99999"})
    original, calls = engine.evaluate, []

    async def counted(candidate, *args, **kwargs):
        calls.append(candidate["id"])
        return await original(candidate, *args, **kwargs)

    monkeypatch.setattr(engine, "evaluate", counted)
    job = store.create_job("evaluate", {"profile_id": profile["id"], "mode": "baseline", "force": True})
    store.next_job()
    await evaluate_one(store, settings, paper, profile, "baseline", force=True, job_id=job["id"])
    store.recover_jobs()
    await JobRunner(store, settings).process(store.next_job())
    assert calls == [paper["id"], second["id"]]
    assert store.job(job["id"])["completed"] == 2


@pytest.mark.asyncio
async def test_forced_partial_retry_does_not_repeat_successful_calls(
    store, settings, profile, paper, paper_data, monkeypatch
):
    from jev_scout import engine

    second = store.ingest_paper({**paper_data, "arxiv_id": "2401.99999"})
    original, calls = engine.evaluate, []

    async def partial(candidate, *args, **kwargs):
        calls.append(candidate["id"])
        if candidate["id"] == second["id"] and calls.count(second["id"]) == 1:
            raise engine.EngineError("Temporary provider failure.")
        return await original(candidate, *args, **kwargs)

    monkeypatch.setattr(engine, "evaluate", partial)
    first = store.create_job("evaluate", {"profile_id": profile["id"], "mode": "baseline", "force": True})
    runner = JobRunner(store, settings)
    await runner.process(store.next_job())
    previous = store.job(first["id"], internal=True)
    retry = store.create_job("evaluate", {**previous["payload"], "_retry_from": first["id"]})
    await runner.process(store.next_job())
    assert calls.count(paper["id"]) == 1 and calls.count(second["id"]) == 2
    assert store.job(retry["id"])["status"] == "completed"


def test_job_coalescing_is_bound_to_profile_and_paper_revisions(
    store, profile, profile_data, paper, paper_data
):
    payload = {"profile_id": profile["id"], "mode": "baseline", "paper_ids": [paper["id"]]}
    first = store.create_job("evaluate", payload)
    store.update_profile(profile["id"], {**profile_data, "keywords": ["different"]}, 1)
    second = store.create_job("evaluate", payload)
    assert second["id"] != first["id"]
    store.ingest_paper({**paper_data, "version": 2})
    third = store.create_job("evaluate", payload)
    assert third["id"] not in {first["id"], second["id"]}
    assert store.create_job("evaluate", payload)["id"] == third["id"]


@pytest.mark.asyncio
async def test_stale_cached_rows_cannot_be_reactivated(store, settings, profile, profile_data, paper):
    from jev_scout.jobs import cache_key

    first = await evaluate_one(store, settings, paper, profile, "baseline")
    key = cache_key(paper, profile, "baseline", settings)
    store.update_profile(profile["id"], {**profile_data, "name": "Revised"}, 1)
    assert store.cached_decision(key) is None
    assert store.activate_cached_decision(first["id"]) is None
    assert store.stats(profile["id"])["recent_runs"][0]["stale"]


@pytest.mark.asyncio
async def test_cached_method_switch_changes_inbox_without_double_counting_usage(
    store, settings, profile, paper
):
    baseline = await evaluate_one(store, settings, paper, profile, "baseline")
    other = store.save_decision(
        paper,
        profile,
        {**baseline, "mode": "llm", "model": "test-model", "input_tokens": 30, "cost_usd": 0.001},
        "different-method",
    )
    assert store.entries(profile["id"])[0]["decision"]["id"] == other["id"]
    reused = await evaluate_one(store, settings, paper, profile, "baseline")
    assert reused["cache_hit"] and reused["id"] == baseline["id"]
    assert store.entries(profile["id"])[0]["decision"]["id"] == baseline["id"]
    assert store.stats(profile["id"])["input_tokens"] == 30
    assert store.stats(profile["id"])["decisions"] == 2


def test_reimporting_an_old_same_version_snapshot_never_rolls_current_back(store, paper, paper_data):
    changed = store.ingest_paper(
        {**paper_data, "abstract": "Corrected abstract at the same version and timestamp."}
    )
    assert changed["_version_id"] != paper["_version_id"]
    store.ingest_paper(paper_data)
    assert store.paper(paper["id"])["_version_id"] == changed["_version_id"]
    assert len(store.paper_versions(paper["id"])) == 2


def test_bundled_metadata_cannot_replace_verified_same_version(store, paper_data):
    verified = store.ingest_paper({**paper_data, "source": "arxiv"})
    store.ingest_paper({**paper_data, "source": "bundled", "abstract": "Old fixture copy."})
    assert store.paper(verified["id"])["_version_id"] == verified["_version_id"]


def test_annotation_records_the_exact_input_versions_and_marks_changes_stale(
    store, profile, profile_data, paper, paper_data
):
    label = {
        "profile_id": profile["id"],
        "paper_id": paper["id"],
        "relevance": 2,
        "split": "test",
        "note": "Human judgment",
    }
    store.annotate(label)
    original = store.annotations()[0]
    assert original["profile_version"] == 1 and original["paper_version"] == 1 and not original["stale"]
    assert original["content_hash"] == paper["content_hash"]
    store.update_profile(
        profile["id"], {**profile_data, "question": "A different research question about memory?"}, 1
    )
    assert store.annotations()[0]["stale"]
    store.annotate(label)
    assert not store.annotations()[0]["stale"]
    store.ingest_paper({**paper_data, "version": 2})
    assert store.annotations()[0]["stale"]


def test_api_rejects_malformed_origin_and_chunked_oversized_bodies(settings, profile_data):
    with TestClient(create_app(settings)) as client:
        for origin in (
            "http://127.0.0.1:invalid",
            "http://[::1",
            "http://user@localhost:8765",
            "http://localhost:8765/path",
        ):
            assert (
                client.post("/api/profiles", json=profile_data, headers={"Origin": origin}).status_code == 403
            )

        def chunks():
            yield b'{"data":"'
            yield b"a" * 262145
            yield b'"}'

        response = client.post(
            "/api/profiles", content=chunks(), headers={"Content-Type": "application/json"}
        )
        assert response.status_code == 413
        assert (
            client.post(
                "/api/profiles", json=profile_data, headers={"Origin": "http://127.0.0.1:8765"}
            ).status_code
            == 201
        )


def test_ingest_rejects_invalid_queries_before_creating_jobs(settings, profile_data):
    with TestClient(create_app(settings)) as client:
        profile = client.post("/api/profiles", json=profile_data).json()
        for query in ("x" * 1001, "all:memory\nOR all:inference"):
            assert (
                client.post("/api/ingest", json={"profile_id": profile["id"], "query": query}).status_code
                == 422
            )
        assert client.get("/api/jobs").json()["items"] == []
        assert (
            client.post(
                "/api/ingest", json={"profile_id": profile["id"], "query": "", "ids": ["2303.08774"]}
            ).status_code
            == 202
        )


def test_exports_escape_fields_and_rebuild_official_source_links(profile_data, paper_data):
    from jev_scout.exports import export_entries

    entry = {
        **paper_data,
        "title": "Unsafe } % \\write18{command}",
        "categories": ["cs.AI} , injected={bad"],
        "source_url": "javascript:alert(1)",
        "reading": {"note": "# Injected heading\n<img src=x>\n[link](javascript:alert(1))"},
    }
    bibtex, _, _ = export_entries([entry], profile_data, "bibtex")
    assert r"\write18" not in bibtex and r"\textbackslash{}write18" in bibtex
    assert r"primaryClass = {cs.AI\}" in bibtex
    markdown, _, _ = export_entries([entry], profile_data, "markdown")
    assert "[arXiv source](https://arxiv.org/abs/2401.12345v1)" in markdown
    assert "\n# Injected" not in markdown and "<img" not in markdown.replace(r"\<img", "")


def test_settings_reject_invalid_provider_urls_ports_and_timeouts(monkeypatch, tmp_path):
    import jev_scout.config as config

    monkeypatch.setattr(config, "PROJECT_ROOT", tmp_path)
    for name in ("JEV_SCOUT_LLM_BASE_URL", "JEV_SCOUT_PORT", "JEV_SCOUT_MODEL_TIMEOUT"):
        monkeypatch.delenv(name, raising=False)
    for name, value in (
        ("JEV_SCOUT_LLM_BASE_URL", "https://provider.example/v1?key=secret"),
        ("JEV_SCOUT_LLM_BASE_URL", "https://provider.example:bad/v1"),
        ("JEV_SCOUT_PORT", "0"),
        ("JEV_SCOUT_MODEL_TIMEOUT", "nan"),
    ):
        monkeypatch.setenv(name, value)
        with pytest.raises(ValueError):
            Settings.load()
        monkeypatch.delenv(name)


@pytest.mark.asyncio
async def test_ingest_retry_keeps_original_import_set_when_upstream_changes(
    store, settings, profile, paper_data, monkeypatch
):
    from jev_scout import arxiv, engine

    fetches = 0

    async def fetch(**kwargs):
        nonlocal fetches
        fetches += 1
        return [paper_data]

    async def failing(*args, **kwargs):
        raise engine.EngineError("Temporary model failure.")

    original = engine.evaluate
    monkeypatch.setattr(arxiv, "fetch_papers", fetch)
    monkeypatch.setattr(engine, "evaluate", failing)
    first = store.create_job(
        "ingest", {"profile_id": profile["id"], "mode": "baseline", "query": "all:memory"}
    )
    runner = JobRunner(store, settings)
    await runner.process(store.next_job())
    previous = store.job(first["id"], internal=True)
    assert previous["payload"]["_imported_paper_ids"]
    monkeypatch.setattr(engine, "evaluate", original)
    retry = store.create_job("ingest", {**previous["payload"], "_retry_from": first["id"]})
    await runner.process(store.next_job())
    assert fetches == 1
    assert store.job(retry["id"])["status"] == "completed"


def test_ingest_dedup_survives_persisted_import_progress(store, profile, paper):
    payload = {"profile_id": profile["id"], "mode": "baseline", "query": "all:memory"}
    first = store.create_job("ingest", payload)
    store.next_job()
    store.set_imported_papers(first["id"], [paper["id"]])
    assert store.create_job("ingest", payload)["id"] == first["id"]


def test_backup_cannot_target_active_database(store):
    with pytest.raises(ValueError, match="destination"):
        store.backup(store.path)
