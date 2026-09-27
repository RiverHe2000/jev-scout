"""Integrity checks on retrospective analysis; never calls a provider."""

import copy
import json
from pathlib import Path

import pytest

from jev_scout.evaluation import load_annotations
from jev_scout.fixtures import load_papers, load_profiles
from jev_scout.reference_review import canonical_hash, main, rescore_reports

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def evidence():
    paths = [
        ROOT / "artifacts/evaluation/qwen-report.json",
        ROOT / "artifacts/evaluation/jev-report.json",
        ROOT / "data/annotations.ai-reference-v1.json",
    ]
    qwen, jev, reference = [json.loads(path.read_text(encoding="utf-8")) for path in paths]
    papers, profiles = load_papers(), load_profiles()
    annotations = load_annotations(paths[2], papers, profiles)
    return qwen, jev, reference, annotations, papers, profiles


def score(evidence):
    qwen, jev, reference, annotations, papers, profiles = evidence
    return rescore_reports(qwen, jev, reference, annotations, papers=papers, profiles=profiles)


def test_preserves_failed_profile_and_original_execution(evidence):
    original = copy.deepcopy(evidence)
    result = score(evidence)
    assert evidence == original
    assert result["measurement"] == "agreement_with_ai_reference"
    assert result["new_provider_calls"] == 0
    assert result["excluded_from_common_comparison"] == ["agent-memory"]
    method = next(m for m in result["methods"] if m["id"] == "jev")
    saved = next(m for m in evidence[1]["methods"] if m["id"] == "jev")
    assert method["status"] == "partial"
    assert method["reference_agreement"]["evaluated_profiles"] == 2
    assert "failed request" in method["reference_agreement"]["excluded_profiles"][0]["reason"]
    assert method["runtime"] == saved["runtime"]
    assert method["errors"] == saved["errors"]
    assert method["quality"] == saved["quality"]
    assert method["quality"]["evaluated"] is False


@pytest.mark.parametrize(
    "corruption",
    ["corpus", "ranking", "hidden_failure", "duplicate_decision", "status", "label", "grade", "score"],
)
def test_rejects_corrupted_evidence(evidence, corruption):
    qwen, jev, reference, annotations, _, _ = evidence
    live = next(m for m in jev["methods"] if m["id"] == "jev")
    baseline = qwen["methods"][0]
    if corruption == "corpus":
        qwen["dataset"]["sha256"] = "changed"
    elif corruption == "ranking":
        baseline["rankings"]["agent-memory"].pop()
    elif corruption == "hidden_failure":
        live["rankings"]["agent-memory"] = list(live["scores"]["agent-memory"])
    elif corruption == "duplicate_decision":
        live["decisions"].append(copy.deepcopy(live["decisions"][0]))
    elif corruption == "status":
        live["status"] = "completed"
    elif corruption == "label":
        annotations["labels"]["agent-memory"].popitem()
    elif corruption == "grade":
        reference["annotations"][0]["plausible_grades"] = [True]
    elif corruption == "score":
        paper = next(iter(baseline["scores"]["agent-memory"]))
        baseline["scores"]["agent-memory"][paper] += 0.001
    with pytest.raises(ValueError):
        score(evidence)


def test_ai_reference_cannot_claim_independent_human_review(evidence, tmp_path):
    reference, papers, profiles = evidence[2], evidence[4], evidence[5]
    reference["provenance"]["independent_review"] = True
    path = tmp_path / "labels.json"
    path.write_text(json.dumps(reference), encoding="utf-8")
    with pytest.raises(ValueError):
        load_annotations(path, papers, profiles)


def test_content_identity_ignores_json_formatting():
    first = {"a": 1, "b": [2, 3]}
    assert canonical_hash(first) == canonical_hash(json.loads('{ "b": [2,3], "a": 1 }'))
    assert canonical_hash(first) != canonical_hash({"a": 2, "b": [2, 3]})


def test_sidecar_cannot_overwrite_evidence(tmp_path):
    source = tmp_path / "evidence.md"
    source.write_text("preserve me", encoding="utf-8")
    with pytest.raises(SystemExit):
        main(["--qwen", str(source), "--output", str(source.with_suffix(".json"))])
    assert source.read_text(encoding="utf-8") == "preserve me"
