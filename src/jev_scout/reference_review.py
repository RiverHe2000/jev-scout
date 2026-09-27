"""Rescore frozen historical rankings against an explicitly attributed reference.

This module never calls a model, changes a ranking, or fills a missing prediction.
Run ``python -m jev_scout.reference_review --help`` for the offline command.
"""

from __future__ import annotations

import argparse
import asyncio
import copy
import hashlib
import json
import math
from datetime import UTC, datetime
from pathlib import Path

from .evaluation import benchmark, load_annotations, quality_for_rankings
from .fixtures import load_papers, load_profiles


def canonical_hash(value: object) -> str:
    """JSON content identity is independent of checkout line-ending conversion."""
    encoded = json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False).encode()
    return hashlib.sha256(encoded).hexdigest()


def _validate_method(method: dict, paper_ids: set[str], profile_keys: set[str]) -> None:
    rankings, scores = method.get("rankings", {}), method.get("scores", {})
    if set(rankings) != profile_keys or set(scores) != profile_keys:
        raise ValueError("Every frozen profile must be present, including failures")
    error_pairs = set()
    for row in method.get("errors", []):
        pair = (row.get("profile_key"), row.get("arxiv_id"))
        if pair[0] not in profile_keys or pair[1] not in paper_ids or pair in error_pairs:
            raise ValueError("Unknown or duplicate failed prediction")
        error_pairs.add(pair)
    for key in sorted(profile_keys):
        score_map, ranking = scores[key], rankings[key]
        if not isinstance(score_map, dict) or not isinstance(ranking, list):
            raise ValueError("Malformed scores or rankings")
        if not set(score_map) <= paper_ids:
            raise ValueError("Unknown scored paper")
        if any(
            isinstance(score, bool)
            or not isinstance(score, int | float)
            or not math.isfinite(score)
            or score < 0
            for score in score_map.values()
        ):
            raise ValueError("Scores must be finite nonnegative numbers")
        missing = paper_ids - set(score_map)
        if missing:
            if ranking or {(key, paper) for paper in missing} != {
                pair for pair in error_pairs if pair[0] == key
            }:
                raise ValueError("Incomplete profiles need an empty ranking and retained failures")
        elif ranking != sorted(score_map, key=lambda paper: (-score_map[paper], paper)):
            raise ValueError("Ranking must contain every candidate in the recorded score order")
        elif any(pair[0] == key for pair in error_pairs):
            raise ValueError("Successful candidates cannot also be failed")
    if method.get("mode") in {"jev", "llm"}:
        decisions = method.get("decisions", [])
        pairs = [(row.get("profile_key"), row.get("arxiv_id")) for row in decisions]
        expected = {(key, paper) for key, score_map in scores.items() for paper in score_map}
        if len(pairs) != len(set(pairs)) or set(pairs) != expected:
            raise ValueError("Live decision records must match successful candidates exactly")
        for row in decisions:
            if row.get("rank_score") != scores[row["profile_key"]][row["arxiv_id"]]:
                raise ValueError("Decision score does not match its ranking score")
    if method.get("runtime", {}).get("evaluated_pairs") != sum(len(v) for v in scores.values()):
        raise ValueError("Recorded evaluated-pair count is inconsistent")
    successful = sum(len(values) for values in scores.values())
    expected_status = (
        "completed"
        if successful == len(paper_ids) * len(profile_keys)
        else "partial"
        if successful
        else "failed"
    )
    if method.get("status") != expected_status:
        raise ValueError("Method status does not match retained candidate coverage")


def rescore_reports(
    qwen: dict, jev: dict, reference: dict, annotations: dict, *, papers: list[dict], profiles: list[dict]
) -> dict:
    """Validate immutable predictions, then compute reference agreement and sensitivity."""
    current = asyncio.run(benchmark(papers=papers, profiles=profiles))
    paper_ids = {paper["arxiv_id"] for paper in papers}
    profile_keys = {profile["fixture_key"] for profile in profiles}
    for saved in (qwen, jev):
        if saved.get("schema_version") != current["schema_version"]:
            raise ValueError("Unsupported saved report version")
        for key in ("papers", "all_papers", "profiles", "pairs", "sha256"):
            if saved.get("dataset", {}).get(key) != current["dataset"][key]:
                raise ValueError(f"Saved corpus mismatch: {key}")
        if saved.get("protocol") != current["protocol"]:
            raise ValueError("Saved ranking protocol differs from the frozen full-corpus protocol")
        methods = saved.get("methods", [])
        if len({method["id"] for method in methods}) != len(methods):
            raise ValueError("Duplicate method identity")
        for method in methods:
            _validate_method(method, paper_ids, profile_keys)
        by_id = {method["id"]: method for method in methods}
        for baseline in current["methods"]:
            recorded = by_id.get(baseline["id"], {})
            # BM25 sums an unordered token set; equivalent summation orders may
            # differ by a few float64 ULPs. Rankings must still match exactly.
            same_scores = all(
                math.isclose(
                    recorded.get("scores", {}).get(key, {}).get(paper, math.nan),
                    score,
                    rel_tol=1e-12,
                    abs_tol=1e-14,
                )
                for key, values in baseline["scores"].items()
                for paper, score in values.items()
            )
            if recorded.get("rankings") != baseline["rankings"] or not same_scores:
                raise ValueError("Saved lexical result differs from unchanged profiles/corpus")
    qwen_methods = {method["id"]: method for method in qwen["methods"]}
    jev_methods = {method["id"]: method for method in jev["methods"]}
    if "llm" not in qwen_methods or "jev" not in jev_methods:
        raise ValueError("Both original provider reports are required")
    if any(set(annotations["labels"].get(key, {})) != paper_ids for key in profile_keys):
        raise ValueError("This review requires all frozen profile-paper references")
    methods = [copy.deepcopy(qwen_methods[key]) for key in ("keyword-coverage", "tfidf", "bm25", "llm")]
    methods.append(copy.deepcopy(jev_methods["jev"]))
    common = sorted(key for key in profile_keys if all(method["rankings"][key] for method in methods))
    alternatives = []
    for row in reference["annotations"]:
        candidates = row.get("plausible_grades", [row["grade"]])
        if (
            not isinstance(candidates, list)
            or any(type(grade) is not int or grade not in (0, 1, 2) for grade in candidates)
            or len(set(candidates)) != len(candidates)
            or row["grade"] not in candidates
        ):
            raise ValueError("Invalid predeclared alternative grades")
        for grade in candidates:
            if grade != row["grade"]:
                alternatives.append((row, grade))
    sensitivity = []
    for method in methods:
        method["historical_generated_at"] = (
            jev["generated_at"] if method["id"] == "jev" else qwen["generated_at"]
        )
        method["reference_agreement"] = quality_for_rankings(method["rankings"], annotations)
        for excluded in method["reference_agreement"]["excluded_profiles"]:
            if not method["rankings"][excluded["profile_key"]]:
                excluded["reason"] = "Incomplete historical model predictions; retained failed request."
        method["common_profile_agreement"] = quality_for_rankings(
            {key: method["rankings"][key] for key in common}, annotations
        )
        # The untouched historical quality block and failure status remain available.
    for row, grade in alternatives:
        changed = copy.deepcopy(annotations)
        changed["labels"][row["profile_key"]][row["arxiv_id"]] = grade
        values = {}
        for method in methods:
            result = quality_for_rankings({key: method["rankings"][key] for key in common}, changed)
            values[method["id"]] = {
                key: result[key] for key in ("ndcg_at_5", "precision_at_5", "recall_at_5")
            }
        sensitivity.append(
            {
                "profile_key": row["profile_key"],
                "arxiv_id": row["arxiv_id"],
                "original_grade": row["grade"],
                "alternative_grade": grade,
                "common_profile_metrics": values,
            }
        )
    return {
        "schema_version": "reference-review-1.0",
        "analysis_generated_at": datetime.now(UTC).isoformat(),
        "measurement": "agreement_with_ai_reference"
        if annotations["provenance"]["label_source"] == "ai_reference"
        else "agreement_with_declared_reference",
        "new_provider_calls": 0,
        "reference_provenance": annotations["provenance"],
        "dataset": current["dataset"],
        "protocol": current["protocol"],
        "common_complete_profiles": common,
        "excluded_from_common_comparison": sorted(profile_keys - set(common)),
        "source_content_sha256": {
            "qwen": canonical_hash(qwen),
            "jev": canonical_hash(jev),
            "reference": canonical_hash(reference),
        },
        "methods": methods,
        "one_label_at_a_time_sensitivity": sensitivity,
        "limitations": [
            "AI-reference agreement is not independent human relevance or real-user utility.",
            "Only three curated profiles and twenty abstracts; no significance or generalization claim.",
            "Labels were frozen without inspecting rankings, but after historical inference; this is retrospective analysis.",
            "Historical live request bodies did not retain a profile digest. Current lexical scores and committed profile history provide consistency evidence, not proof of exact historical prompts.",
            "Incomplete profiles are unscored. The common-profile comparison also reports which profile was excluded.",
            "Historical latency units differ; input-only API cost excludes failed calls, output fees and local hardware/electricity.",
            "One-label sensitivity is not a confidence interval and does not cover simultaneous judgement changes.",
        ],
    }


def render_review(report: dict) -> str:
    lines = [
        "# Exploratory AI-reference ranking review",
        "",
        "This is agreement with frozen assistant judgements, **not human relevance accuracy or a user study**.",
        "No new model calls were made. Original inference dates, failures and cost estimates are retained.",
        "",
        f"Common complete profiles: {', '.join(report['common_complete_profiles']) or 'none'}.",
        f"Excluded from the common comparison: {', '.join(report['excluded_from_common_comparison']) or 'none'}.",
        "",
        "## Comparable coverage",
        "",
        "| Method | Complete profiles | All-complete nDCG@5 | Common nDCG@5 | Common P@5 | Common R@5 |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for method in report["methods"]:
        overall, common = method["reference_agreement"], method["common_profile_agreement"]
        values = [overall["ndcg_at_5"], common["ndcg_at_5"], common["precision_at_5"], common["recall_at_5"]]
        cells = [f"{value:.3f}" if value is not None else "unavailable" for value in values]
        lines.append(f"| {method['id']} | {overall['evaluated_profiles']}/3 | " + " | ".join(cells) + " |")
    lines.extend(
        [
            "",
            "## Per-profile agreement",
            "",
            "The excluded agent-memory profile remains visible for every method that completed it.",
            "",
            "| Method | Profile | nDCG@5 | P@5 | R@5 |",
            "|---|---|---:|---:|---:|",
        ]
    )
    for method in report["methods"]:
        for row in method["reference_agreement"]["per_profile"]:
            lines.append(
                f"| {method['id']} | {row['profile_key']} | {row['ndcg_at_5']:.3f} | "
                f"{row['precision_at_5']:.3f} | {row['recall_at_5']:.3f} |"
            )
    lines.extend(
        [
            "",
            "## Retained historical execution",
            "",
            "These are the original runs, not fresh timing measurements. Latency units differ. "
            "Input-only API estimates exclude failed calls, output fees, hardware and electricity.",
            "",
            "| Method | Valid pairs | Original run (UTC) | p50 ms | Latency unit | Input / output tokens | Input API USD |",
            "|---|---:|---|---:|---|---:|---:|",
        ]
    )
    for method in report["methods"]:
        runtime = method["runtime"]
        cost = runtime.get("cost_usd")
        cost_cell = f"{cost:.9f}" if cost is not None else "unavailable"
        lines.append(
            f"| {method['id']} | {runtime['evaluated_pairs']}/60 | {method['historical_generated_at']} | "
            f"{runtime['latency_p50_ms']:.3f} | {runtime['latency_unit']} | "
            f"{runtime['input_tokens']} / {runtime['output_tokens']} | {cost_cell} |"
        )
    lines.extend(
        [
            "",
            "## Predeclared label sensitivity",
            "",
            "One plausible label is changed at a time. These ranges are **not confidence intervals**.",
            "",
            "| Method | Common nDCG@5 range |",
            "|---|---:|",
        ]
    )
    for method in report["methods"]:
        values = [method["common_profile_agreement"]["ndcg_at_5"]] + [
            row["common_profile_metrics"][method["id"]]["ndcg_at_5"]
            for row in report["one_label_at_a_time_sensitivity"]
        ]
        measured = [value for value in values if value is not None]
        cell = f"{min(measured):.3f}–{max(measured):.3f}" if measured else "unavailable"
        lines.append(f"| {method['id']} | {cell} |")
    lines.extend(["", "## Limits and interpretation", ""])
    lines.extend(f"- {limit}" for limit in report["limitations"])
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--qwen", type=Path, default=Path("artifacts/evaluation/qwen-report.json"))
    parser.add_argument("--jev", type=Path, default=Path("artifacts/evaluation/jev-report.json"))
    parser.add_argument("--labels", type=Path, default=Path("data/annotations.ai-reference-v1.json"))
    parser.add_argument(
        "--output", type=Path, default=Path("artifacts/evaluation/phase-c/reference-review.json")
    )
    args = parser.parse_args(argv)
    destinations = {args.output.resolve(), args.output.with_suffix(".md").resolve()}
    if destinations & {args.qwen.resolve(), args.jev.resolve(), args.labels.resolve()}:
        parser.error("The review cannot overwrite its evidence inputs")
    try:
        papers, profiles = load_papers(), load_profiles()
        inputs = [json.loads(path.read_text(encoding="utf-8")) for path in (args.qwen, args.jev, args.labels)]
        annotations = load_annotations(args.labels, papers, profiles)
        report = rescore_reports(*inputs, annotations, papers=papers, profiles=profiles)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(report, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8"
        )
        args.output.with_suffix(".md").write_text(render_review(report), encoding="utf-8")
    except (ValueError, KeyError, TypeError, OSError) as error:
        parser.error(str(error))
    print(f"Saved AI-reference review; no provider calls: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
