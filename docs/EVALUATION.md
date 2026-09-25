# Evaluation that distinguishes measurement from evidence

The benchmark runs three retrieval baselines over 20 attributed arXiv abstracts and three starter research profiles. The included measurements contain an **actual local Qwen3-4B inference run with 60/60 structurally validated profile–paper decisions**, plus a separate [actual Jev run through OpenRouter](../artifacts/evaluation/jev-report.json). Rankings, runtime, and token usage are measured. Relevance-quality scores remain unavailable because the collection has not been annotated. Each provider is named separately; these results do not establish user time savings, adoption, or an independent study.

## Recorded local-model run

The [final Qwen report](../artifacts/evaluation/qwen-report.json) was generated on **2026-09-25 at 05:23:42 UTC**. The local bridge used constrained finite-enum decoding, and the independent application adapter validated every response. The [earlier prompt-only report](../artifacts/evaluation/qwen-prompt-only.json) is preserved as a diagnostic reference.

| Observation | Initial prompt-only bridge | Final constrained bridge |
| --- | --- | --- |
| Attempted profile–paper pairs | 60 | 60 |
| Structurally validated decisions | 51 | 60 |
| Rejected/failed decisions | 9 | 0 |
| Quality evaluated against reviewed labels | No | No |

One reproduced failure in the initial run was the string `"true"` where a JSON boolean was required. The adapter correctly rejected it. The final bridge prevents that invalid form during token generation and still validates the decoded result; it does not coerce invalid values into acceptable ones.

The final local model run took **261.989 seconds** in total, with **4.362-second p50** and **4.929-second p95** latency per profile–paper request. It recorded **54,299 input tokens** and **2,324 output tokens**. The configured local input-token API price was zero; that does not measure hardware, electricity, or an external provider's fees. These are observations on one development machine, not a general throughput or quality claim. The two bridge runs used different output-generation constraints, so they are not a controlled model-quality comparison.

Schema validity is a format/integration measurement. It does not establish correct relevance grades, sufficient evidence, calibrated confidence, or better recommendations than the baselines. Those claims still require reviewed labels and a held-out evaluation.

## Recorded Jev run

Real OpenRouter calls returned `typesafe/jev-1.13-20260917`. The [Jev rerun](../artifacts/evaluation/jev-report.json) has **59/60 validated decisions**, **450.088 ms p50**, **833.730 ms p95**, and **$0.004671618 estimated input cost for successful decisions**. One failed candidate remains in the report even though one isolated recheck passed. Neither that recheck nor the separate successful 21-paper workspace job turns the original benchmark into a clean 60/60 run.

An [earlier report](../artifacts/evaluation/jev-initial-validation.json) records 48/60 decisions before an overly strict precision check was corrected. The bounded compatibility rule checks whether one normalized probability distribution and score can exist within the observed two-decimal rounding intervals; it preserves the supplied values and records the assumption in the trace. The final rerun used this path for ten decisions. This observed precision behavior is not presented as an official rounding guarantee. See [the policy](INTELLIGENCE.md) and [full results](RESULTS.md).

The application displays a combined `report.json`: Qwen and its lexical baselines retain their original measurements, while the Jev method comes from the separate Jev report. Dataset and protocol equality were checked before combining. The raw reports and per-method timestamps are retained. Partial status, missing labels, and differing latency units remain visible.

## Reproduce the offline report

From the repository root, after installing the project:

```console
python -m jev_scout.evaluation --output artifacts/evaluation/offline-report.json
```

This writes a separate offline report and preserves the recorded local-model snapshot. The app's `/api/evaluation` endpoint reads `artifacts/evaluation/report.json`; explicitly select that output path when you want to replace the displayed report. A benchmark file can be available while `quality_evaluated` is false. The offline benchmark does not require a model key, the internet, a GPU, or scikit-learn.

The report records its timestamp, corpus digest, candidate groups, split policy, method statuses, raw rankings, scores, runtimes, and limitations. Local timings are a single observation and will vary between runs. Lexical methods time one profile against the whole corpus; live model methods time individual profile–paper requests. The `latency_unit` field makes that difference explicit. Do not compare those percentiles as though the work units were identical.

## Baselines

| Method | Scoring rule | Important limitation |
| --- | --- | --- |
| Keyword coverage | Twice the fraction of unique explicit profile keywords matched in title or abstract; case-insensitive phrase and word boundaries | Does not infer meaning, preferences, exclusions, or synonyms |
| TF-IDF cosine | Sublinear term frequency, smoothed inverse document frequency, cosine similarity; title counted twice | Lexical overlap only; no learned embedding model |
| BM25 | `k1=1.2`, `b=0.75`, positive smoothed IDF; title counted twice | Corpus length and lexical rarity affect scores |

All methods use the same frozen papers and explicit profile keywords. Ties break by arXiv ID ascending. Raw scores from different methods have different units. TF-IDF and BM25 fit their unsupervised vocabulary/statistics on the evaluation candidate set; neither trains on relevance labels. The app's offline decision engine uses keyword coverage. TF-IDF and BM25 are benchmark comparators, not selectable inference providers in the inbox.

## Add honest relevance labels

Create a fresh file or copy the bundled blank template:

```console
python -m jev_scout.evaluation --init-labels artifacts/evaluation/my-labels.json
```

The command refuses to overwrite existing labels. Each row has a stable profile key, arXiv ID, frozen paper version, title, source link, nullable grade, and notes. Research questions, preferences, exclusions, and keyword definitions are frozen in the file. The loader rejects changed task definitions, unknown papers, duplicate rows, incompatible paper versions, booleans, and grades outside the allowed set.

Annotate using the question and available abstract *before inspecting model rankings*. Use `0` for irrelevant, `1` for partly useful, and `2` for directly useful. Keep an uncertain judgement `null`; a missing label is never treated as a negative. Record disagreements or full-paper information gaps in notes.

Set `provenance.label_source` to `author_reference` if the project author supplies judgements, record the annotator, and keep `independent_review` false. Only use `independent_human` with an actual independent annotator and an explicit true declaration. That declaration is recorded provenance, not independently verified by the software. Synthetic contract data is rejected by the real-paper label loader.

```console
python -m jev_scout.evaluation --labels artifacts/evaluation/my-labels.json --output artifacts/evaluation/labelled-report.json
```

A profile contributes to quality metrics only if **every candidate in its evaluation subset** has a reviewed label. The report lists excluded profiles. Partial annotation therefore cannot silently inflate recall or nDCG. Results from author-reference labels remain exploratory; they are not a user study or an unbiased estimate of product utility.

## Ranking metrics

- **nDCG@5** uses exponential gain `2^grade − 1` and logarithmic rank discount. The ideal ordering comes from all labelled candidates in the evaluation subset.
- **Precision@5** considers grades 1 and 2 relevant and always divides by 5, including when fewer than five candidates are returned.
- **Recall@5** divides relevant top-five items by all relevant candidates in the evaluation subset.
- Profiles with no relevant candidates receive zero nDCG and recall; the policy is explicit in the report. Results are macro-averaged across complete profiles.

`evaluation.py` also implements validated binary Brier score, equal-width event-probability ECE, confidence-tie-aware risk–coverage curves, and right-step AURC. These functions are covered by known-value and invalid-input tests. The default benchmark leaves calibration fields null: Jev score-distribution concentration is not a calibrated probability of correctness, and an LLM's relevance grade is not a probability. Dividing a relevance score by two would not establish the required event semantics. Reporting these metrics needs separately declared event probabilities and observed correctness outcomes.

## Group and time holdouts

```console
python -m jev_scout.evaluation --labels artifacts/evaluation/my-labels.json --split group --test-fraction 0.3 --seed study-v1
python -m jev_scout.evaluation --labels artifacts/evaluation/my-labels.json --split time --cutoff 2024-01-01
```

Group splits assign all revisions of an arXiv document to the same side using a deterministic seeded hash. Time splits use a family's earliest original publication date, so a later revision cannot move an older document into a future test set. The benchmark requires a single frozen revision per paper. Both split implementations reject empty/degenerate partitions. The report names the held-out and training groups. No model is actually trained by this command.

Do not tune prompts, keywords, thresholds, or labels using the held-out set. The current 20-paper corpus is too small and curated to support a broad scientific claim; expand and independently annotate a chronologically collected feed for that purpose. Preventing document overlap does not fix corpus-selection bias or label leakage.

## Optional actual model runs

The CLI loads the same `.env` configuration as the application. Live execution is explicit and may use provider quota:

For the optional local bridge on port 8766, start it first, then configure the benchmark's own shell (a different terminal does not inherit the launch script's environment):

```powershell
$env:JEV_SCOUT_LLM_BASE_URL = 'http://127.0.0.1:8766/v1'
$env:JEV_SCOUT_LLM_MODEL = 'qwen3-4b'
$env:JEV_SCOUT_LLM_PRICE_PER_MILLION_INPUT = '0'
.\.venv\Scripts\python.exe -m jev_scout.evaluation --live llm --output artifacts/evaluation/live-llm.json
```

For a provider already configured in `.env`, use:

```console
python -m jev_scout.evaluation --live jev --output artifacts/evaluation/live-jev.json
python -m jev_scout.evaluation --live llm --output artifacts/evaluation/live-llm.json
```

Jev uses `TYPESAFE_API_KEY` or `OPENROUTER_API_KEY`; TypeSafe takes precedence if both are configured. The alternative OpenAI-compatible provider uses `JEV_SCOUT_LLM_BASE_URL`, `JEV_SCOUT_LLM_MODEL`, and optional `JEV_SCOUT_LLM_API_KEY` for local servers. Model outputs are actual requests, never filled from fixtures. No automatic fallback replaces a failed provider with a baseline.

The application engine validates structured responses. The benchmark records failed requests without saving raw error bodies or credentials. A profile with an incomplete live candidate set is excluded from quality evaluation; any failed or partial live method makes the CLI exit nonzero after writing the report. Costs remain unavailable if actual pricing is not configured. Both local Qwen and real Jev through OpenRouter were exercised; see [RESULTS.md](RESULTS.md) for measured results and compatibility findings.

Live ranking evaluates the deployed prioritization score, which may include explicit preference weights. That score can rank differently from a relevance-only prediction; define your annotation instructions accordingly. The report preserves model identity, question version, relevance-known state, route, and abstention count. Unknown model answers retain the deployed ordering policy and are explicitly marked; they are not converted into confident negative labels. A model-selected abstract excerpt is proposed support for the reader to assess, not proof of relevance or a scientific claim.

## Report contract

`schema_version`, `available`, `quality_evaluated`, `generated_at`, `dataset`, `protocol`, `methods`, and `limitations` are top-level keys. Each method has `id`, `label`, `mode`, `status`, `quality`, `runtime`, `rankings`, and `scores`; live methods additionally include sanitized `errors`. Quality fields are null when unevaluated. Provider usage belongs to actual live runs; baseline token counts and API cost are zero.
