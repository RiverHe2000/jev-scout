# Discussing Jev Scout in an interview

## A concise project introduction

“I built a local research inbox that prioritizes papers against an explicit research question. It keeps the source abstract, decision mode, profile version, and evidence spans together, so the user can inspect a recommendation and revise their reading queue. The same interface supports an offline lexical baseline and configured structured model providers. I also built a reproducible ranking benchmark that refuses to present unlabelled data as evaluation gold.”

## Decisions worth discussing

**Why use a research question rather than only a topic feed?** A topic can be broad. A question expresses what the reader is trying to learn; preferences make the desired evidence explicit. The starter profiles let an interviewer compare the same corpus under different reading goals.

**Why keep a simple baseline?** It offers a transparent, reproducible comparator and makes the product usable offline. The UI identifies it clearly. It cannot infer semantics or evaluate arbitrary exclusion prose. More complicated inference needs to justify its extra cost with reviewed evidence, not a nicer-looking score.

**Why store evidence spans?** Source offsets let the interface highlight unchanged abstract text and let a reader verify what the model was given. A cited excerpt supports traceability. It does not prove the model's judgement or the paper's scientific conclusion.

**How are model differences handled?** Provider adapters validate structured outputs and preserve the actual mode/model. Jev offers probabilistic decisions; a compatible chat model supplies structured categorical answers. Their confidence semantics are different, so the app does not manufacture a common calibrated probability. Failures stay visible instead of silently switching to a different engine.

**How is the local model kept inside the output contract?** The optional local bridge constrains token generation to a bounded set of valid enum decisions. This handles actual tokenizer boundaries and preserves JSON booleans as booleans. A second validation step and the independent adapter checks remain in place. This guarantees the supported output structure; it does not establish the model's relevance judgement or evidence quality. The GPU lock also survives an HTTP cancellation until the running generation thread has finished.

**What prevents stale answers?** Paper and profile versions are part of the decision provenance. A changed question or revised abstract requires a new decision. Describe the implemented persistence and job safeguards using the root architecture documentation and the actual tests.

**What makes evaluation credible?** Real papers are clearly separated from synthetic contract tests. The public corpus is a demo collection. Labels require an explicit annotator and source declaration; incomplete candidate sets do not produce quality scores. The benchmark contains keyword, TF-IDF, and BM25 comparators, document-family/time holdouts, and tests for ranking/calibration metric edge cases.

**What has actually been measured?** A local Qwen3-4B run produced 60/60 structurally validated decisions across 20 real papers and three profiles. The recorded run took 261.989 seconds, with 4.362-second median request latency. An earlier prompt-only run yielded 51 valid decisions and nine failures; one reproduced failure was a quoted boolean. The final bridge constrains generation while preserving strict validation. These are format and execution measurements, not relevance-quality results.

Real Jev calls were also measured through OpenRouter: the separate rerun validated 59/60 decisions with 450.088 ms median successful-request latency. One anomaly remains in that single-pass report even though an isolated recheck passed. A separate application job completed all 21 workspace papers. Discuss the observed rounding-compatibility issue, the preservation of provider values, and the retained failure record; do not turn request completion into an accuracy claim.

**What has not been demonstrated yet?** There are no reviewed human relevance labels, user study, adoption metric, or validated quality advantage. Real Jev calls through OpenRouter are recorded separately in [RESULTS.md](RESULTS.md). Provider availability is separate from recommendation accuracy: neither a successful live call nor a mocked protocol test establishes real Jev accuracy. A schema-valid local answer likewise does not prove a useful reading recommendation.

## Resume wording supported by the initial implementation

- Built a local-first paper research workspace with versioned research profiles, source-linked abstract evidence, reading-state management, and citation export.
- Implemented explicit lexical and structured-model inference paths with validated responses, provenance, and visible uncertainty handling.
- Developed a reproducible evaluation harness with keyword, TF-IDF, and BM25 baselines; nDCG/precision/recall metrics; annotation provenance; and document-family/time holdouts over an attributed 20-paper starter corpus.
- Verified 60/60 structurally valid local Qwen3-4B decisions using constrained decoding and independent response validation, while preserving an earlier failed-run diagnostic and withholding unmeasured relevance-quality claims.

Use only features you have personally run and can explain. Add a performance or user-impact bullet after measuring it. If independent evaluators later label a held-out collection, report the dataset size, label provenance, split, comparator, metric, and uncertainty alongside the result. Keep author-reference exploratory results labelled as such.

## A useful next experiment

Collect a dated feed for one actual research question, freeze the question and candidate abstracts, and ask readers to label relevance before seeing rankings. Compare keyword, TF-IDF, BM25, and available live providers on the same held-out candidates. Record reading decisions and time only with an explicit study protocol. Use the result to decide whether better retrieval, richer source extraction, or a different decision model is the next worthwhile change.
