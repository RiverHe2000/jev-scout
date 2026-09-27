# Exploratory AI-reference ranking review

This is agreement with frozen assistant judgements, **not human relevance accuracy or a user study**.
No new model calls were made. Original inference dates, failures and cost estimates are retained.

Common complete profiles: efficient-inference, retrieval-personalization.
Excluded from the common comparison: agent-memory.

## Comparable coverage

| Method | Complete profiles | All-complete nDCG@5 | Common nDCG@5 | Common P@5 | Common R@5 |
|---|---:|---:|---:|---:|---:|
| keyword-coverage | 3/3 | 0.914 | 1.000 | 1.000 | 0.406 |
| tfidf | 3/3 | 0.971 | 1.000 | 1.000 | 0.406 |
| bm25 | 3/3 | 1.000 | 1.000 | 1.000 | 0.406 |
| llm | 3/3 | 0.858 | 1.000 | 1.000 | 0.406 |
| jev | 2/3 | 1.000 | 1.000 | 1.000 | 0.406 |

## Per-profile agreement

The excluded agent-memory profile remains visible for every method that completed it.

| Method | Profile | nDCG@5 | P@5 | R@5 |
|---|---|---:|---:|---:|
| keyword-coverage | agent-memory | 0.743 | 0.800 | 0.267 |
| keyword-coverage | efficient-inference | 1.000 | 1.000 | 0.455 |
| keyword-coverage | retrieval-personalization | 1.000 | 1.000 | 0.357 |
| tfidf | agent-memory | 0.913 | 1.000 | 0.333 |
| tfidf | efficient-inference | 1.000 | 1.000 | 0.455 |
| tfidf | retrieval-personalization | 1.000 | 1.000 | 0.357 |
| bm25 | agent-memory | 1.000 | 1.000 | 0.333 |
| bm25 | efficient-inference | 1.000 | 1.000 | 0.455 |
| bm25 | retrieval-personalization | 1.000 | 1.000 | 0.357 |
| llm | agent-memory | 0.573 | 1.000 | 0.333 |
| llm | efficient-inference | 1.000 | 1.000 | 0.455 |
| llm | retrieval-personalization | 1.000 | 1.000 | 0.357 |
| jev | efficient-inference | 1.000 | 1.000 | 0.455 |
| jev | retrieval-personalization | 1.000 | 1.000 | 0.357 |

## Retained historical execution

These are the original runs, not fresh timing measurements. Latency units differ. Input-only API estimates exclude failed calls, output fees, hardware and electricity.

| Method | Valid pairs | Original run (UTC) | p50 ms | Latency unit | Input / output tokens | Input API USD |
|---|---:|---|---:|---|---:|---:|
| keyword-coverage | 60/60 | 2026-09-25T05:23:42.704434+00:00 | 2.178 | one_profile_full_corpus | 0 / 0 | 0.000000000 |
| tfidf | 60/60 | 2026-09-25T05:23:42.704434+00:00 | 1.722 | one_profile_full_corpus | 0 / 0 | 0.000000000 |
| bm25 | 60/60 | 2026-09-25T05:23:42.704434+00:00 | 1.016 | one_profile_full_corpus | 0 / 0 | 0.000000000 |
| llm | 60/60 | 2026-09-25T05:23:42.704434+00:00 | 4361.503 | one_paper_profile_pair | 54299 / 2324 | 0.000000000 |
| jev | 59/60 | 2026-09-25T07:53:20.183851+00:00 | 450.088 | one_paper_profile_pair | 111229 / 9832 | 0.004671618 |

## Predeclared label sensitivity

One plausible label is changed at a time. These ranges are **not confidence intervals**.

| Method | Common nDCG@5 range |
|---|---:|
| keyword-coverage | 1.000–1.000 |
| tfidf | 1.000–1.000 |
| bm25 | 1.000–1.000 |
| llm | 0.929–1.000 |
| jev | 1.000–1.000 |

## Limits and interpretation

- AI-reference agreement is not independent human relevance or real-user utility.
- Only three curated profiles and twenty abstracts; no significance or generalization claim.
- Labels were frozen without inspecting rankings, but after historical inference; this is retrospective analysis.
- Historical live request bodies did not retain a profile digest. Current lexical scores and committed profile history provide consistency evidence, not proof of exact historical prompts.
- Incomplete profiles are unscored. The common-profile comparison also reports which profile was excluded.
- Historical latency units differ; input-only API cost excludes failed calls, output fees and local hardware/electricity.
- One-label sensitivity is not a confidence interval and does not cover simultaneous judgement changes.
