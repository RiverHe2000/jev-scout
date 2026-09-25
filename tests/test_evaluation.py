"""Contract/metric tests use synthetic records; these are not research labels."""

import asyncio
import copy
import json
import math

import pytest

from jev_scout.evaluation import (
    annotation_template,
    area_under_risk_coverage,
    benchmark,
    bm25_scores,
    brier_score,
    dcg_at_k,
    expected_calibration_error,
    group_split,
    keyword_score,
    load_annotations,
    ndcg_at_k,
    paper_group,
    precision_at_k,
    quality_for_rankings,
    recall_at_k,
    risk_coverage_curve,
    tfidf_scores,
    time_split,
)
from jev_scout.fixtures import load_papers, load_profiles


@pytest.fixture
def corpus():
    return [
        {
            "arxiv_id": "2001.00001",
            "version": 1,
            "title": "Memory systems",
            "abstract": "Memory retrieval across sessions.",
            "published": "2020-01-01",
            "source_url": "https://arxiv.org/abs/2001.00001v1",
        },
        {
            "arxiv_id": "2301.00002",
            "version": 2,
            "title": "Serving inference",
            "abstract": "Efficient neural inference and quantization.",
            "published": "2023-01-01",
            "source_url": "https://arxiv.org/abs/2301.00002v2",
        },
        {
            "arxiv_id": "2401.00003",
            "version": 1,
            "title": "A third topic",
            "abstract": "This concerns network topology.",
            "published": "2024-01-01",
            "source_url": "https://arxiv.org/abs/2401.00003v1",
        },
    ]


@pytest.fixture
def profiles():
    return [
        {
            "fixture_key": "memory",
            "question": "Which papers study memory retrieval?",
            "keywords": ["memory", "retrieval"],
        }
    ]


def test_dcg_and_ndcg_hand_worked_example():
    labels = {"strong": 2, "weak": 1, "none": 0}
    assert dcg_at_k([2, 1, 0], 3) == pytest.approx(3 + 1 / math.log2(3))
    assert ndcg_at_k(["strong", "weak", "none"], labels, 3) == 1
    assert ndcg_at_k(["none", "weak", "strong"], labels, 3) == pytest.approx(
        (1 / math.log2(3) + 3 / 2) / (3 + 1 / math.log2(3))
    )
    assert ndcg_at_k(["weak"], labels, 1) == pytest.approx(1 / 3)


def test_precision_and_recall_use_different_denominators():
    labels = {"a": 2, "b": 1, "c": 0}
    assert precision_at_k(["a"], labels, 5) == 0.2
    assert recall_at_k(["a"], labels, 5) == 0.5
    assert recall_at_k(["c"], {"c": 0}, 5) == 0
    assert ndcg_at_k(["c"], {"c": 0}, 5) == 0


@pytest.mark.parametrize(
    "ranking,labels,k",
    [
        (["a", "a"], {"a": 1}, 1),
        (["b"], {"a": 1}, 1),
        (["a"], {"a": float("nan")}, 1),
        (["a"], {"a": 3}, 1),
        (["a"], {"a": True}, 1),
        (["a"], {"a": 1}, 0),
        (["a"], {"a": 1}, True),
    ],
)
def test_ranking_metrics_reject_invalid_inputs(ranking, labels, k):
    with pytest.raises(ValueError):
        ndcg_at_k(ranking, labels, k)


def test_calibration_known_examples_and_bin_edge():
    assert brier_score([0, 1], [0, 1]) == 0
    assert brier_score([0, 1], [1, 0]) == 1
    assert brier_score([0, 1], [0.5, 0.5]) == 0.25
    assert expected_calibration_error([0, 1], [0.5, 0.5]) == 0
    assert expected_calibration_error([0, 1], [1, 0], bins=10) == 1


@pytest.mark.parametrize(
    "outcomes,probabilities",
    [([], []), ([0], []), ([2], [0.5]), ([True], [0.5]), ([1], [float("inf")]), ([0], [-0.1]), ([0], [1.1])],
)
def test_calibration_rejects_bad_data(outcomes, probabilities):
    with pytest.raises(ValueError):
        brier_score(outcomes, probabilities)


def test_risk_coverage_does_not_arbitrarily_break_ties():
    points = risk_coverage_curve([0, 1, 1], [0.9, 0.5, 0.5])
    assert points == [
        {"threshold": 0.9, "coverage": 1 / 3, "risk": 0, "accepted": 1},
        {"threshold": 0.5, "coverage": 1, "risk": 2 / 3, "accepted": 3},
    ]
    assert area_under_risk_coverage([0, 1, 1], [0.9, 0.5, 0.5]) == pytest.approx(4 / 9)
    assert risk_coverage_curve([1, 0, 1], [0.5, 0.9, 0.5]) == points


def test_group_split_is_order_independent_and_keeps_revisions(corpus):
    revision = {**corpus[0], "arxiv_id": corpus[0]["arxiv_id"] + "v2", "version": 2}
    train, heldout = group_split(corpus + [revision], seed="fixed")
    other_train, other_heldout = group_split(list(reversed(corpus + [revision])), seed="fixed")
    assert {paper_group(paper) for paper in train}.isdisjoint(paper_group(paper) for paper in heldout)
    assert {paper_group(paper) for paper in train} == {paper_group(paper) for paper in other_train}
    assert {paper_group(paper) for paper in heldout} == {paper_group(paper) for paper in other_heldout}
    assert len(train) + len(heldout) == 4


def test_time_split_uses_first_publication_and_preserves_groups(corpus):
    revision = {**corpus[0], "arxiv_id": corpus[0]["arxiv_id"] + "v2", "published": "2025-01-01"}
    train, heldout = time_split(corpus + [revision], cutoff="2023-01-01")
    assert len(train) == 2
    assert [paper["arxiv_id"] for paper in heldout] == ["2301.00002", "2401.00003"]
    with pytest.raises(ValueError):
        time_split(corpus, cutoff="2030-01-01")


def test_lexical_methods_rank_relevant_terms_and_handle_empty_query(corpus, profiles):
    profile = profiles[0]
    assert keyword_score(corpus[0], profile) == 2
    assert keyword_score(corpus[1], profile) == 0
    for scorer in (bm25_scores, tfidf_scores):
        scores = scorer(corpus, profile)
        assert scores["2001.00001"] > scores["2301.00002"] == 0
        assert all(value == 0 for value in scorer(corpus, {"keywords": []}).values())


def test_keyword_baseline_matches_phrases_with_boundaries():
    paper = {"title": "Memoryless", "abstract": "We study long term memory."}
    assert keyword_score(paper, {"keywords": ["memory", "long term", "MEMORY"]}) == 2
    assert keyword_score(paper, {"keywords": ["memo", "long-term"]}) == 0


def _label_file(tmp_path, corpus, profiles, *, grade=1):
    payload = annotation_template(corpus, profiles)
    payload["provenance"].update(label_source="author_reference", annotator="Test author")
    for annotation in payload["annotations"]:
        annotation["grade"] = grade
    path = tmp_path / "annotations.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path, payload


def test_annotation_loader_accepts_explicit_author_reference(tmp_path, corpus, profiles):
    path, _ = _label_file(tmp_path, corpus, profiles)
    loaded = load_annotations(path, corpus, profiles)
    assert loaded["labelled_pairs"] == 3
    assert loaded["provenance"]["independent_review"] is False


@pytest.mark.parametrize(
    "mutation",
    ["duplicate", "grade", "version", "question", "unknown", "unreviewed", "independent", "synthetic"],
)
def test_annotation_loader_rejects_invalid_or_misrepresented_labels(tmp_path, corpus, profiles, mutation):
    path, payload = _label_file(tmp_path, corpus, profiles)
    if mutation == "duplicate":
        payload["annotations"].append(copy.deepcopy(payload["annotations"][0]))
    elif mutation == "grade":
        payload["annotations"][0]["grade"] = True
    elif mutation == "version":
        payload["annotations"][0]["paper_version"] = 9
    elif mutation == "question":
        payload["profiles"][0]["question"] = "A different task"
    elif mutation == "unknown":
        payload["annotations"][0]["arxiv_id"] = "not-in-corpus"
    else:
        payload["provenance"]["label_source"] = {
            "unreviewed": "unreviewed",
            "independent": "independent_human",
            "synthetic": "synthetic_contract",
        }[mutation]
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError):
        load_annotations(path, corpus, profiles)


def test_partial_labels_do_not_generate_quality_or_calibration():
    quality = quality_for_rankings({"memory": ["a", "b"]}, {"labels": {"memory": {"a": 2}}})
    assert quality["evaluated"] is False
    assert quality["ndcg_at_5"] is None
    assert quality["brier"] is None


@pytest.mark.parametrize(
    "field,value",
    [
        ("profiles", None),
        ("profiles", [{"fixture_key": []}]),
        ("provenance", []),
        ("annotations", {}),
        ("annotations", [{"profile_key": [], "arxiv_id": "2001.00001"}]),
    ],
)
def test_annotation_schema_errors_are_actionable(tmp_path, corpus, profiles, field, value):
    path, payload = _label_file(tmp_path, corpus, profiles)
    payload[field] = value
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError):
        load_annotations(path, corpus, profiles)


def test_offline_evaluation_score_matches_deployed_engine():
    from jev_scout.engine import evaluate

    paper, profile = load_papers()[0], load_profiles()[0]
    result = asyncio.run(evaluate(paper, profile, mode="baseline"))
    assert result["relevance"] == keyword_score(paper, profile)
    assert result["mode"] == "baseline"


def test_benchmark_is_measured_but_unlabelled(corpus, profiles):
    report = asyncio.run(benchmark(papers=corpus, profiles=profiles))
    assert report["available"] is True
    assert report["quality_evaluated"] is False
    assert report["dataset"]["pairs"] == 3
    assert len(report["methods"]) == 3
    for method in report["methods"]:
        assert method["runtime"]["elapsed_ms"] >= 0
        assert method["runtime"]["cost_usd"] == 0
        assert method["quality"]["ndcg_at_5"] is None


def test_benchmark_with_reviewed_labels_and_holdout(tmp_path, corpus, profiles):
    path, _ = _label_file(tmp_path, corpus, profiles)
    annotations = load_annotations(path, corpus, profiles)
    report = asyncio.run(
        benchmark(
            papers=corpus, profiles=profiles, annotations=annotations, split="time", cutoff="2023-01-01"
        )
    )
    assert report["quality_evaluated"] is True
    assert report["dataset"]["papers"] == 2
    assert report["protocol"]["training_papers"] == 1
    assert report["methods"][0]["quality"]["precision_at_5"] == 0.4
    assert report["methods"][0]["quality"]["brier"] is None


def test_live_failures_cannot_masquerade_as_complete_rankings(tmp_path, corpus, profiles, monkeypatch):
    from jev_scout import engine

    path, _ = _label_file(tmp_path, corpus, profiles)
    annotations = load_annotations(path, corpus, profiles)

    async def fake_evaluate(paper, profile, **options):
        if paper["arxiv_id"] == "2301.00002":
            raise RuntimeError("provider leaked fake-secret-in-test")
        return {
            "rank_score": 20,
            "relevance": 1,
            "mode": "llm",
            "model": "synthetic-contract",
            "input_tokens": 10,
            "output_tokens": 5,
            "cost_usd": None,
            "trace": {"relevance_known": True},
        }

    monkeypatch.setattr(engine, "evaluate", fake_evaluate)
    report = asyncio.run(
        benchmark(
            papers=corpus,
            profiles=profiles,
            annotations=annotations,
            live_mode="llm",
            live_options={
                "api_key": "fake-secret-in-test",
                "model": "synthetic-contract",
                "base_url": "http://127.0.0.1:1234/v1",
            },
        )
    )
    live = report["methods"][-1]
    assert live["status"] == "partial"
    assert live["runtime"]["evaluated_pairs"] == 2
    assert live["runtime"]["cost_usd"] is None
    assert live["quality"]["evaluated"] is False
    assert live["rankings"]["memory"] == []
    assert "fake-secret-in-test" not in json.dumps(report)


def test_live_unknowns_preserve_explicit_abstention(corpus, profiles, monkeypatch):
    from jev_scout import engine

    async def fake_evaluate(paper, profile, **options):
        return {
            "rank_score": 0,
            "relevance": 0,
            "route": "review",
            "mode": "llm",
            "model": "synthetic-contract",
            "trace": {"relevance_known": False},
        }

    monkeypatch.setattr(engine, "evaluate", fake_evaluate)
    live = asyncio.run(benchmark(papers=corpus, profiles=profiles, live_mode="llm"))["methods"][-1]
    assert live["status"] == "completed"
    assert live["runtime"]["abstained_pairs"] == 3
    assert all(decision["relevance"] is None for decision in live["decisions"])
    assert all(decision["route"] == "review" for decision in live["decisions"])


def test_real_fixtures_are_attributed_and_load_independently_of_cwd(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    papers, profiles = load_papers(), load_profiles()
    assert 15 <= len(papers) <= 30
    assert len(profiles) == 3
    assert len({profile["fixture_key"] for profile in profiles}) == 3
    assert all(paper["provenance"]["metadata_license"] == "CC0-1.0" for paper in papers)
    assert all(paper["provenance"]["license_url"] for paper in papers)
    assert all(paper["source_url"].endswith(f"v{paper['version']}") for paper in papers)
    # Fresh dicts ensure UI/profile edits cannot mutate module-global fixtures.
    papers[0]["title"] = "Changed"
    assert load_papers()[0]["title"] != "Changed"
