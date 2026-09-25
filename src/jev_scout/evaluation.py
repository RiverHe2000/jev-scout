"""Reproducible ranking benchmarks with explicit label and calibration provenance.

Run ``python -m jev_scout.evaluation --help`` from an installed checkout.
The bundled collection has no human relevance labels. An unlabelled run measures
runtime and rankings, never quality, calibration, or time saved by a user.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import math
import re
import statistics
import time
from collections import Counter
from collections.abc import Mapping, Sequence
from datetime import UTC, date, datetime
from pathlib import Path
from urllib.parse import urlparse

from .fixtures import load_papers, load_profiles

REPORT_VERSION = "1.0"
LABEL_VERSION = "1.0"
K = 5


def _positive_k(k: int) -> None:
    if isinstance(k, bool) or not isinstance(k, int) or k < 1:
        raise ValueError("k must be a positive integer")


def _finite(value: float, *, minimum: float = 0, maximum: float | None = None) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("Metric values must be numeric, not boolean")
    value = float(value)
    if not math.isfinite(value) or value < minimum or (maximum is not None and value > maximum):
        raise ValueError("Metric value is outside its finite allowed range")
    return value


def dcg_at_k(relevances: Sequence[float], k: int = K) -> float:
    """Exponential gain DCG, with relevance grades restricted to [0, 2]."""
    _positive_k(k)
    values = [_finite(value, maximum=2) for value in relevances]
    return sum((2**grade - 1) / math.log2(index + 2) for index, grade in enumerate(values[:k]))


def _validate_ranking(ranking: Sequence[str], labels: Mapping[str, float]) -> None:
    if len(ranking) != len(set(ranking)):
        raise ValueError("Ranked document IDs must be unique")
    if any(document not in labels for document in ranking):
        raise ValueError("Every ranked document requires a relevance label")
    for value in labels.values():
        _finite(value, maximum=2)


def ndcg_at_k(ranking: Sequence[str], labels: Mapping[str, float], k: int = K) -> float:
    """Normalize against all labelled candidates, including omitted documents."""
    _positive_k(k)
    _validate_ranking(ranking, labels)
    ideal = dcg_at_k(sorted(labels.values(), reverse=True), k)
    return dcg_at_k([labels[key] for key in ranking], k) / ideal if ideal else 0.0


def precision_at_k(
    ranking: Sequence[str], labels: Mapping[str, float], k: int = K, *, relevant_threshold: float = 1
) -> float:
    """P@k uses k as denominator even if fewer than k documents are returned."""
    _positive_k(k)
    _validate_ranking(ranking, labels)
    threshold = _finite(relevant_threshold, maximum=2)
    return sum(labels[key] >= threshold for key in ranking[:k]) / k


def recall_at_k(
    ranking: Sequence[str], labels: Mapping[str, float], k: int = K, *, relevant_threshold: float = 1
) -> float:
    _positive_k(k)
    _validate_ranking(ranking, labels)
    threshold = _finite(relevant_threshold, maximum=2)
    relevant = sum(value >= threshold for value in labels.values())
    return sum(labels[key] >= threshold for key in ranking[:k]) / relevant if relevant else 0.0


def _binary_probabilities(
    outcomes: Sequence[int], probabilities: Sequence[float]
) -> tuple[list[int], list[float]]:
    if not outcomes or len(outcomes) != len(probabilities):
        raise ValueError("Outcomes and probabilities must be nonempty and equally sized")
    if any(type(value) is not int or value not in (0, 1) for value in outcomes):
        raise ValueError("Outcomes must be integer 0 or 1")
    return list(outcomes), [_finite(value, maximum=1) for value in probabilities]


def brier_score(outcomes: Sequence[int], probabilities: Sequence[float]) -> float:
    """Binary Brier score for a declared event; lower is better."""
    actual, predicted = _binary_probabilities(outcomes, probabilities)
    return statistics.fmean(
        (probability - outcome) ** 2 for outcome, probability in zip(actual, predicted, strict=True)
    )


def expected_calibration_error(
    outcomes: Sequence[int], probabilities: Sequence[float], *, bins: int = 10
) -> float:
    """Equal-width event-probability ECE (not top-label multiclass ECE)."""
    _positive_k(bins)
    actual, predicted = _binary_probabilities(outcomes, probabilities)
    buckets: dict[int, list[tuple[int, float]]] = {}
    for outcome, probability in zip(actual, predicted, strict=True):
        buckets.setdefault(min(int(probability * bins), bins - 1), []).append((outcome, probability))
    return sum(
        len(bucket)
        / len(actual)
        * abs(statistics.fmean(x[0] for x in bucket) - statistics.fmean(x[1] for x in bucket))
        for bucket in buckets.values()
    )


def risk_coverage_curve(errors: Sequence[int], confidences: Sequence[float]) -> list[dict]:
    """Selective risk at complete confidence tie groups; no arbitrary tie order.

    ``errors`` means 1=incorrect, 0=correct. Confidence must be a declared
    confidence-of-correctness score; it need not be calibrated for this curve.
    """
    errors, confidences = _binary_probabilities(errors, confidences)
    grouped: dict[float, list[int]] = {}
    for error, confidence in zip(errors, confidences, strict=True):
        grouped.setdefault(confidence, []).append(error)
    accepted = mistakes = 0
    points = []
    for confidence in sorted(grouped, reverse=True):
        accepted += len(grouped[confidence])
        mistakes += sum(grouped[confidence])
        points.append(
            {
                "threshold": confidence,
                "coverage": accepted / len(errors),
                "risk": mistakes / accepted,
                "accepted": accepted,
            }
        )
    return points


def area_under_risk_coverage(errors: Sequence[int], confidences: Sequence[float]) -> float:
    """Right-step AURC; tied scores are accepted together."""
    previous = area = 0.0
    for point in risk_coverage_curve(errors, confidences):
        area += (point["coverage"] - previous) * point["risk"]
        previous = point["coverage"]
    return area


def paper_group(paper: Mapping) -> str:
    identifier = str(paper.get("arxiv_id", "")).strip()
    identifier = re.sub(r"v\d+$", "", identifier)
    if not identifier:
        raise ValueError("A stable arXiv ID is required for splitting")
    return identifier


def group_split(
    papers: Sequence[dict], *, test_fraction: float = 0.2, seed: str = "jev-scout-v1"
) -> tuple[list[dict], list[dict]]:
    """Deterministic document-family holdout; every revision shares a split."""
    fraction = _finite(test_fraction, maximum=1)
    if not 0 < fraction < 1:
        raise ValueError("test_fraction must be strictly between 0 and 1")
    groups = sorted(
        {paper_group(paper) for paper in papers},
        key=lambda group: hashlib.sha256(f"{seed}:{group}".encode()).hexdigest(),
    )
    if len(groups) < 2:
        raise ValueError("At least two document groups are required")
    count = min(len(groups) - 1, max(1, math.ceil(len(groups) * fraction)))
    test_groups = set(groups[:count])
    return (
        [paper for paper in papers if paper_group(paper) not in test_groups],
        [paper for paper in papers if paper_group(paper) in test_groups],
    )


def time_split(papers: Sequence[dict], *, cutoff: str) -> tuple[list[dict], list[dict]]:
    """Chronological family split by original publication date, not revision date."""
    try:
        boundary = date.fromisoformat(cutoff)
        grouped: dict[str, list[date]] = {}
        for paper in papers:
            grouped.setdefault(paper_group(paper), []).append(
                date.fromisoformat(str(paper["published"])[:10])
            )
    except (TypeError, ValueError, KeyError) as error:
        raise ValueError("Time splits require valid ISO publication dates and cutoff") from error
    test_groups = {group for group, dates in grouped.items() if min(dates) >= boundary}
    train = [paper for paper in papers if paper_group(paper) not in test_groups]
    test = [paper for paper in papers if paper_group(paper) in test_groups]
    if not train or not test:
        raise ValueError("Time split must produce nonempty training and held-out groups")
    return train, test


def tokens(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", text.casefold())


def keyword_score(paper: dict, profile: dict) -> float:
    keywords = list(
        dict.fromkeys(
            str(value).strip().casefold() for value in profile.get("keywords", []) if str(value).strip()
        )
    )
    if not keywords:
        return 0.0
    text = f"{paper['title']}\n{paper['abstract']}".casefold()
    hits = sum(
        bool(
            re.search(r"(?<!\w)" + r"\s+".join(re.escape(part) for part in keyword.split()) + r"(?!\w)", text)
        )
        for keyword in keywords
    )
    return 2 * hits / len(keywords)


def bm25_scores(
    papers: Sequence[dict], profile: dict, *, k1: float = 1.2, b: float = 0.75
) -> dict[str, float]:
    """BM25 over title+abstract; title appears twice. No learned parameters."""
    _finite(k1)
    _finite(b, maximum=1)
    if not papers:
        return {}
    documents = [
        Counter(tokens(f"{paper['title']} {paper['title']} {paper['abstract']}")) for paper in papers
    ]
    query = set(tokens(" ".join(profile.get("keywords", []))))
    average_length = statistics.fmean(sum(document.values()) for document in documents)
    frequencies = Counter(term for document in documents for term in document)
    result = {}
    for paper, document in zip(papers, documents, strict=True):
        length = sum(document.values())
        score = 0.0
        for term in query:
            count = document[term]
            if not count:
                continue
            inverse_frequency = math.log(
                1 + (len(documents) - frequencies[term] + 0.5) / (frequencies[term] + 0.5)
            )
            denominator = count + k1 * (1 - b + b * length / average_length)
            score += inverse_frequency * count * (k1 + 1) / denominator
        result[paper_group(paper)] = score
    return result


def tfidf_scores(papers: Sequence[dict], profile: dict) -> dict[str, float]:
    """Sublinear TF, smoothed IDF, cosine similarity; title appears twice."""
    if not papers:
        return {}
    documents = [
        Counter(tokens(f"{paper['title']} {paper['title']} {paper['abstract']}")) for paper in papers
    ]
    query = Counter(tokens(" ".join(profile.get("keywords", []))))
    frequencies = Counter(term for document in documents for term in document)
    idf = {
        term: math.log((1 + len(documents)) / (1 + frequency)) + 1 for term, frequency in frequencies.items()
    }
    query_vector = {term: (1 + math.log(count)) * idf[term] for term, count in query.items() if term in idf}
    query_norm = math.sqrt(sum(value * value for value in query_vector.values()))
    result = {}
    for paper, document in zip(papers, documents, strict=True):
        vector = {term: (1 + math.log(count)) * idf[term] for term, count in document.items()}
        norm = math.sqrt(sum(value * value for value in vector.values()))
        result[paper_group(paper)] = (
            sum(query_vector.get(term, 0) * value for term, value in vector.items()) / (norm * query_norm)
            if norm and query_norm
            else 0.0
        )
    return result


def _profile_snapshot(profile: dict) -> dict:
    return {
        "fixture_key": profile["fixture_key"],
        "question": profile["question"],
        "preferences": profile.get("preferences", []),
        "exclusions": profile.get("exclusions", ""),
        "keywords": profile.get("keywords", []),
    }


def annotation_template(papers: Sequence[dict], profiles: Sequence[dict]) -> dict:
    return {
        "schema_version": LABEL_VERSION,
        "provenance": {
            "label_source": "unreviewed",
            "annotator": "",
            "instructions": "Fill grade 0=irrelevant, 1=partly useful, 2=directly useful, using the frozen profile question and available abstract. Leave unknown grades null. Declare author_reference for project-author judgements or independent_human only for actual independent annotation. Never score by looking at model rankings.",
            "created_at": datetime.now(UTC).isoformat(),
            "independent_review": False,
        },
        "profiles": [_profile_snapshot(profile) for profile in profiles],
        "annotations": [
            {
                "profile_key": profile["fixture_key"],
                "arxiv_id": paper_group(paper),
                "paper_version": paper["version"],
                "title": paper["title"],
                "source_url": paper["source_url"],
                "grade": None,
                "notes": "",
            }
            for profile in profiles
            for paper in papers
        ],
    }


def load_annotations(path: Path, papers: Sequence[dict], profiles: Sequence[dict]) -> dict:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("schema_version") != LABEL_VERSION:
        raise ValueError("Unsupported annotation schema version")
    provenance = payload.get("provenance", {})
    if not isinstance(provenance, dict):
        raise ValueError("Annotation provenance must be an object")
    source = provenance.get("label_source")
    if not isinstance(source, str) or source not in {
        "unreviewed",
        "author_reference",
        "independent_human",
        "synthetic_contract",
    }:
        raise ValueError("Declare annotation label_source explicitly")
    if source == "synthetic_contract":
        raise ValueError("Synthetic contract labels cannot evaluate the real-paper collection")
    known_profiles = {profile["fixture_key"]: profile for profile in profiles}
    known_papers = {paper_group(paper): paper for paper in papers}
    supplied_profiles = payload.get("profiles")
    if not isinstance(supplied_profiles, list) or any(
        not isinstance(profile, dict) or not isinstance(profile.get("fixture_key"), str)
        for profile in supplied_profiles
    ):
        raise ValueError("Frozen profiles must be an array of profile objects")
    declared_profiles = {profile["fixture_key"]: profile for profile in supplied_profiles}
    if len(declared_profiles) != len(supplied_profiles) or set(declared_profiles) != set(known_profiles):
        raise ValueError("Frozen profiles must match the benchmark exactly without duplicates")
    for key, profile in known_profiles.items():
        if declared_profiles.get(key) != _profile_snapshot(profile):
            raise ValueError(f"Profile task definition changed or is missing from annotations: {key}")
    labels: dict[str, dict[str, int]] = {key: {} for key in known_profiles}
    seen = set()
    annotations = payload.get("annotations")
    if not isinstance(annotations, list):
        raise ValueError("annotations must be an array")
    for row in annotations:
        if not isinstance(row, dict):
            raise ValueError("Each annotation must be an object")
        key, arxiv_id = row.get("profile_key"), row.get("arxiv_id")
        if (
            not isinstance(key, str)
            or not isinstance(arxiv_id, str)
            or key not in known_profiles
            or arxiv_id not in known_papers
        ):
            raise ValueError("Annotation references an unknown profile or paper")
        if (key, arxiv_id) in seen:
            raise ValueError("Duplicate profile-paper annotation")
        seen.add((key, arxiv_id))
        if (
            type(row.get("paper_version")) is not int
            or row["paper_version"] != known_papers[arxiv_id]["version"]
        ):
            raise ValueError("Annotation paper version does not match the frozen corpus")
        grade = row.get("grade")
        if grade is None:
            continue
        if type(grade) is not int or grade not in (0, 1, 2):
            raise ValueError("Relevance grade must be integer 0, 1, 2, or null")
        labels[key][arxiv_id] = grade
    labelled = sum(len(values) for values in labels.values())
    if labelled and (source == "unreviewed" or not str(provenance.get("annotator", "")).strip()):
        raise ValueError("Nonempty labels require a named annotator and reviewed label_source")
    if source == "independent_human" and provenance.get("independent_review") is not True:
        raise ValueError("Independent labels require an explicit independent_review declaration")
    return {"labels": labels, "provenance": provenance, "labelled_pairs": labelled}


def quality_for_rankings(rankings: dict[str, list[str]], annotations: dict | None, *, k: int = K) -> dict:
    result = {
        "evaluated": False,
        "ndcg_at_5": None,
        "precision_at_5": None,
        "recall_at_5": None,
        "brier": None,
        "ece": None,
        "risk_coverage": None,
        "evaluated_profiles": 0,
        "excluded_profiles": [],
        "per_profile": [],
        "calibration_status": "unavailable",
        "calibration_reason": "No declared event probabilities and independently observed correctness outcomes; score-distribution concentration is not a probability of correctness.",
    }
    for key, ranking in rankings.items():
        labels = (annotations or {}).get("labels", {}).get(key, {})
        if not ranking or any(paper_id not in labels for paper_id in ranking):
            result["excluded_profiles"].append(
                {
                    "profile_key": key,
                    "reason": "Every candidate in the evaluation subset must have a reviewed label.",
                }
            )
            continue
        scoped = {paper_id: labels[paper_id] for paper_id in ranking}
        result["per_profile"].append(
            {
                "profile_key": key,
                "candidates": len(ranking),
                "ndcg_at_5": ndcg_at_k(ranking, scoped, k),
                "precision_at_5": precision_at_k(ranking, scoped, k),
                "recall_at_5": recall_at_k(ranking, scoped, k),
            }
        )
    evaluated = result["per_profile"]
    if evaluated:
        result["evaluated"] = True
        result["evaluated_profiles"] = len(evaluated)
        for metric in ("ndcg_at_5", "precision_at_5", "recall_at_5"):
            result[metric] = statistics.fmean(profile[metric] for profile in evaluated)
    return result


def _percentile(values: Sequence[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    return ordered[max(0, math.ceil(fraction * len(ordered)) - 1)]


async def benchmark(
    *,
    papers: list[dict] | None = None,
    profiles: list[dict] | None = None,
    annotations: dict | None = None,
    live_mode: str | None = None,
    live_options: dict | None = None,
    split: str = "all",
    cutoff: str | None = None,
    test_fraction: float = 0.2,
    seed: str = "jev-scout-v1",
) -> dict:
    papers = load_papers() if papers is None else papers
    profiles = load_profiles() if profiles is None else profiles
    if not papers or not profiles:
        raise ValueError("Benchmark requires at least one paper and profile")
    if len({paper_group(paper) for paper in papers}) != len(papers):
        raise ValueError("Benchmark requires one frozen version per paper family")
    all_count = len(papers)
    train: list[dict] = []
    if split == "group":
        train, papers = group_split(papers, test_fraction=test_fraction, seed=seed)
    elif split == "time":
        if cutoff is None:
            raise ValueError("A cutoff date is required for time splits")
        train, papers = time_split(papers, cutoff=cutoff)
    elif split != "all":
        raise ValueError("split must be all, group, or time")
    dataset_hash = hashlib.sha256(json.dumps(papers, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    methods = []
    for method in ("keyword-coverage", "tfidf", "bm25"):
        start = time.perf_counter()
        rankings, scores, latencies = {}, {}, []
        for profile in profiles:
            one_start = time.perf_counter()
            if method == "keyword-coverage":
                score_map = {paper_group(paper): keyword_score(paper, profile) for paper in papers}
            else:
                score_map = (tfidf_scores if method == "tfidf" else bm25_scores)(papers, profile)
            elapsed = (time.perf_counter() - one_start) * 1000
            latencies.append(elapsed)
            rankings[profile["fixture_key"]] = sorted(score_map, key=lambda key: (-score_map[key], key))
            scores[profile["fixture_key"]] = score_map
        elapsed = (time.perf_counter() - start) * 1000
        methods.append(
            {
                "id": method,
                "label": {
                    "keyword-coverage": "Keyword coverage",
                    "tfidf": "TF-IDF cosine (title ×2)",
                    "bm25": "BM25 (title ×2)",
                }[method],
                "mode": "baseline",
                "status": "completed",
                "quality": quality_for_rankings(rankings, annotations),
                "runtime": {
                    "evaluated_pairs": len(papers) * len(profiles),
                    "elapsed_ms": elapsed,
                    "latency_p50_ms": _percentile(latencies, 0.5),
                    "latency_p95_ms": _percentile(latencies, 0.95),
                    "latency_unit": "one_profile_full_corpus",
                    "input_tokens": 0,
                    "output_tokens": 0,
                    "cost_usd": 0,
                },
                "rankings": rankings,
                "scores": scores,
            }
        )
    if live_mode:
        if live_mode not in {"jev", "llm"}:
            raise ValueError("Live mode must be jev or llm")
        from .engine import evaluate  # Optional provider dependencies load only here.

        rankings, scores, latencies, errors = {}, {}, [], []
        decisions = []
        abstained_pairs = 0
        input_tokens = output_tokens = 0
        costs: list[float | None] = []
        evaluated_pairs = 0
        start = time.perf_counter()
        for profile in profiles:
            score_map = {}
            for paper in papers:
                one_start = time.perf_counter()
                try:
                    decision = await evaluate(paper, profile, mode=live_mode, **(live_options or {}))
                    score_map[paper_group(paper)] = _finite(decision["rank_score"])
                    latencies.append((time.perf_counter() - one_start) * 1000)
                    input_tokens += decision.get("input_tokens") or 0
                    output_tokens += decision.get("output_tokens") or 0
                    costs.append(decision.get("cost_usd"))
                    known = decision.get("trace", {}).get("relevance_known", True)
                    abstained_pairs += int(not known)
                    decisions.append(
                        {
                            "profile_key": profile["fixture_key"],
                            "arxiv_id": paper_group(paper),
                            "model": decision.get("model"),
                            "question_version": decision.get("question_version"),
                            "relevance": decision.get("relevance") if known else None,
                            "confidence": decision.get("confidence"),
                            "rank_score": decision["rank_score"],
                            "route": decision.get("route"),
                            "relevance_known": known,
                        }
                    )
                    evaluated_pairs += 1
                except Exception as error:
                    # Avoid serializing provider text that might contain secrets.
                    errors.append(
                        {
                            "profile_key": profile["fixture_key"],
                            "arxiv_id": paper_group(paper),
                            "error_type": type(error).__name__,
                            "message": "Provider evaluation failed; quality is not evaluated on incomplete candidate sets.",
                        }
                    )
            scores[profile["fixture_key"]] = score_map
            rankings[profile["fixture_key"]] = (
                sorted(score_map, key=lambda key: (-score_map[key], key))
                if len(score_map) == len(papers)
                else []
            )
        provider_url = (
            (live_options or {}).get("base_url")
            or (live_options or {}).get("endpoint")
            or "https://api.typesafe.ai/v1/systemone"
        )
        methods.append(
            {
                "id": live_mode,
                "label": "Jev (live)" if live_mode == "jev" else "LLM provider (live)",
                "mode": live_mode,
                "model": (live_options or {}).get("model"),
                "provider_host": urlparse(provider_url).hostname,
                "status": "completed" if not errors else "partial" if evaluated_pairs else "failed",
                "quality": quality_for_rankings(rankings, annotations),
                "runtime": {
                    "evaluated_pairs": evaluated_pairs,
                    "abstained_pairs": abstained_pairs,
                    "elapsed_ms": (time.perf_counter() - start) * 1000,
                    "latency_p50_ms": _percentile(latencies, 0.5),
                    "latency_p95_ms": _percentile(latencies, 0.95),
                    "latency_unit": "one_paper_profile_pair",
                    "input_tokens": input_tokens,
                    "output_tokens": output_tokens,
                    "cost_usd": sum(costs) if costs and all(cost is not None for cost in costs) else None,
                },
                "rankings": rankings,
                "scores": scores,
                "decisions": decisions,
                "errors": errors,
            }
        )
    provenance = (annotations or {}).get(
        "provenance", {"label_source": "unreviewed", "independent_review": False}
    )
    return {
        "schema_version": REPORT_VERSION,
        "available": True,
        "quality_evaluated": any(method["quality"]["evaluated"] for method in methods),
        "generated_at": datetime.now(UTC).isoformat(),
        "dataset": {
            "papers": len(papers),
            "all_papers": all_count,
            "profiles": len(profiles),
            "pairs": len(papers) * len(profiles),
            "sha256": dataset_hash,
            "provenance": "Attributed public arXiv abstract metadata; curated demonstration collection, not a representative research feed.",
            "label_status": provenance.get("label_source", "unreviewed"),
            "label_provenance": provenance,
            "labelled_pairs": (annotations or {}).get("labelled_pairs", 0),
        },
        "protocol": {
            "k": K,
            "relevance_grades": {"0": "irrelevant", "1": "partly useful", "2": "directly useful"},
            "positive_threshold": 1,
            "gain": "2^grade - 1",
            "precision_denominator": K,
            "zero_relevant_policy": "nDCG and recall are 0",
            "tie_break": "arxiv_id ascending",
            "aggregation": "macro mean over fully labelled profile candidate sets",
            "split": split,
            "cutoff": cutoff,
            "seed": seed,
            "training_papers": len(train),
            "training_groups": sorted(paper_group(paper) for paper in train),
            "evaluation_groups": sorted(paper_group(paper) for paper in papers),
            "trained_model": False,
        },
        "methods": methods,
        "limitations": [
            "No quality claim is possible without reviewed relevance annotations for complete candidate sets.",
            "Author-reference labels, if imported, are subjective and are not an independent user study.",
            "The 20-paper starter corpus is small and selected for demonstration; do not generalize its results.",
            "Abstract-level evidence cannot establish findings that require the full paper.",
            "No measured user time savings, deployment traffic, or real-user adoption is claimed.",
            "No calibration metrics are reported without declared event probabilities and observed outcomes; model score confidence is uncalibrated.",
            "Runtime is a local one-pass observation; lexical per-profile timings and live per-pair timings have different units.",
            "Group and time holdouts prevent document-family overlap; they do not by themselves validate annotation independence or eliminate corpus-selection bias.",
        ],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("artifacts/evaluation/report.json"))
    parser.add_argument(
        "--init-labels", type=Path, help="Write a blank annotation template and exit; refuses overwrite"
    )
    parser.add_argument("--labels", type=Path, help="Reviewed annotations in the documented JSON schema")
    parser.add_argument(
        "--live",
        choices=("jev", "llm"),
        help="Explicit opt-in to paid/local provider calls; baseline always runs",
    )
    parser.add_argument("--split", choices=("all", "group", "time"), default="all")
    parser.add_argument("--cutoff", help="ISO publication date for a time holdout")
    parser.add_argument("--test-fraction", type=float, default=0.2)
    parser.add_argument("--seed", default="jev-scout-v1")
    arguments = parser.parse_args(argv)
    papers, profiles = load_papers(), load_profiles()
    if arguments.init_labels:
        arguments.init_labels.parent.mkdir(parents=True, exist_ok=True)
        with arguments.init_labels.open("x", encoding="utf-8") as handle:
            json.dump(annotation_template(papers, profiles), handle, indent=2, ensure_ascii=False)
            handle.write("\n")
        print(f"Created {len(papers) * len(profiles)} blank annotations: {arguments.init_labels}")
        return 0
    try:
        annotations = load_annotations(arguments.labels, papers, profiles) if arguments.labels else None
        options = {}
        if arguments.live:
            from .config import Settings

            settings = Settings.load()
            if arguments.live == "jev":
                if not settings.jev_provider:
                    raise ValueError("TYPESAFE_API_KEY or OPENROUTER_API_KEY is required for --live jev")
                options = {
                    "api_key": settings.typesafe_key or settings.openrouter_key,
                    "model": settings.resolved_jev_model,
                    "endpoint": settings.jev_endpoint,
                    "timeout": settings.model_timeout,
                    "price_per_million_input": settings.input_price,
                }
            else:
                if not settings.llm_base_url:
                    raise ValueError("JEV_SCOUT_LLM_BASE_URL is required for --live llm")
                options = {
                    "base_url": settings.llm_base_url,
                    "model": settings.llm_model,
                    "api_key": settings.llm_key or None,
                    "timeout": settings.model_timeout,
                    "price_per_million_input": settings.llm_input_price,
                }
        report = asyncio.run(
            benchmark(
                papers=papers,
                profiles=profiles,
                annotations=annotations,
                live_mode=arguments.live,
                live_options=options,
                split=arguments.split,
                cutoff=arguments.cutoff,
                test_fraction=arguments.test_fraction,
                seed=arguments.seed,
            )
        )
    except (ValueError, OSError, json.JSONDecodeError) as error:
        parser.error(str(error))
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = arguments.output.with_suffix(arguments.output.suffix + ".tmp")
    temporary.write_text(
        json.dumps(report, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8"
    )
    temporary.replace(arguments.output)
    print(
        f"Measured {report['dataset']['pairs']} pairs with {len(report['methods'])} methods. Quality evaluated: {report['quality_evaluated']}. Report: {arguments.output}"
    )
    return 1 if any(method["status"] in {"failed", "partial"} for method in report["methods"]) else 0


if __name__ == "__main__":
    raise SystemExit(main())
