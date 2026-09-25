# Intelligence and source adapters

The app makes one decision for one paper and one version of a research profile.
Every decision records its adapter, returned model, question version, input paper
version, profile version, original abstract spans, policy, and token usage. There
is no silent switch of provider when a call fails.

## Three explicit modes

| Mode | Mechanism | Confidence | Evidence | Network |
| --- | --- | --- | --- | --- |
| `baseline` | Exact keyword/phrase coverage | Unavailable | Keyword locations | None |
| `jev` | Typed Jev decisions | Provider Score confidence; not domain-calibrated | Choice over original abstract sentences, including `none` | TypeSafe or OpenRouter Decisions |
| `llm` | Schema-constrained generative model | Unavailable | Original sentence ID or `none` | Configured OpenAI-compatible endpoint, including localhost |

The baseline is useful for a functioning offline demonstration and a reproducible
comparison. It is not represented as AI inference. It cannot judge free-form
exclusions or research preferences. LLM decisions are identified separately from
Jev, and no self-reported numerical confidence is requested or manufactured.

## Integration interface

```python
async def evaluate(
    paper: dict,
    profile: dict,
    *,
    mode: str,
    api_key: str | None = None,
    model: str = "jev-latest",
    timeout: float = 30,
    client: httpx.AsyncClient | None = None,
    price_per_million_input: float | None = None,
    base_url: str | None = None,
    endpoint: str | None = None,
) -> dict: ...
```

`endpoint` is a Jev REST endpoint, restricted to
`https://api.typesafe.ai/v1/systemone` or
`https://openrouter.ai/api/alpha/decisions`. The caller supplies the corresponding
credential and model identifier. For OpenRouter, use `typesafe/jev-1.13`.
`base_url` is used only for `llm`, e.g. `http://127.0.0.1:11434/v1`;
`/chat/completions` is appended. Remote LLM providers require HTTPS. This URL
comes from trusted server configuration, not paper contents or browser requests.

`build_questions(paper, profile)` returns the exact TypeSafe-compatible request:

```json
{
  "model": "jev-latest",
  "state": {
    "title": "Paper title",
    "abstract_sentences": [{"id": "s1", "text": "Original abstract sentence."}]
  },
  "questions": {
    "relevance": {"type": "score", "instructions": {}, "criteria": ["Unrelated", "Adjacent", "Direct"]},
    "evidence": {"type": "choice", "instructions": {}, "criteria": {"none": "No supporting sentence", "s1": "Original abstract sentence."}},
    "exclusion": {"type": "noul", "instructions": {}, "criteria": {"true": "Explicitly meets exclusion", "false": "Exclusion not established"}},
    "preference_1": {"type": "noul", "instructions": {}, "criteria": {"true": "Affirmative evidence", "false": "Affirmative evidence not established"}}
  }
}
```

This example abbreviates the actual instructions and rubrics. Exclusion is omitted
when blank; zero to three preference questions are included. Each question
includes its research question or condition explicitly. Paper metadata is source
data, never the instructions. Dates, weights, arithmetic, and routing remain in
Python. Paper text and preference text are bounded before constructing a request.

The LLM adapter asks for `relevance` in `0 | 1 | 2 | "unknown"`, `evidence` in the
sentence IDs or `"none"`, and `exclusion` plus each configured preference in
`true | false | "unknown"`. All fields are required and additional fields are
rejected. An unknown relatedness uses zero only as a ranking placeholder, routes
to review, and sets `trace.relevance_known=false`. Unknown preferences remain
`null`; they are never converted to false.

The optional local Qwen bridge enforces this finite-enum object schema during
token generation. It tokenizes the bounded set of valid JSON decisions and uses
a shared-prefix token trie to constrain each next token, including real JSON
booleans rather than the strings `"true"` or `"false"`. Schemas with unsupported
constraints, optional fields, nested values, or excessive combinations are
rejected before generation. A second check validates the decoded object, and
the application adapter still performs its own strict validation. This local
bridge is not a general-purpose JSON-schema implementation or proof of answer
quality. Constraints enforce output structure, not scientific correctness.

The bridge permits one GPU generation at a time. Cancelling the HTTP coroutine
does not stop an already running CUDA operation, so its lock stays held until
the generation thread actually finishes; competing calls receive a retryable
busy response. Model weights and CUDA support are optional and separate from
the core application and offline tests.

## Decision policy

The current question version is `scout-triage-1.0`. Changing questions or policy
requires a version change so cached decisions can be marked stale.

- Jev Score values are fractional probability-weighted expectations over the
  ordinal levels, not integer labels or a percentage of relevance. Returned
  distributions must cover the exact options, remain finite in `[0,1]`, and sum
  to one within `0.002`. Score and expectation normally agree within `0.005`;
  the narrowly bounded wire-rounding compatibility rule below handles observed
  independently rounded responses without changing their values.
- Basic routing is `read` at relevance `>=1.4`, `skim` at `>=0.6`, otherwise
  `later`. These are explicit product settings, not validated optimal thresholds.
- Jev relatedness confidence below the profile setting routes to `review`.
  Relatedness at or above `0.6` also requires an evidence sentence and evidence
  confidence at or above the profile setting. Confidence means distribution
  concentration; the app does not claim it is the probability of correctness.
- A Jev exclusion probability at least `0.8` routes to `later` and rank zero;
  values strictly between `0.2` and `0.8` route to `review`. Missing information
  does not satisfy an exclusion. A configured LLM exclusion of `unknown` routes
  to review and `true` routes to later.
- Rank is `100 * (0.85 * relevance / 2 + 0.15 * weighted_preferences)` when
  positively weighted preference values exist. Otherwise it is `50 * relevance`.
  It is a sorting score, not a calibrated probability. Review gating does not
  discard potentially useful papers' relevance scores.
- Baseline relevance is `2 * matched_unique_keywords / total_unique_keywords`.
  Matching is case-insensitive, uses Unicode word boundaries, and allows
  whitespace within phrases. There is no stemming, embedding, translation, or
  semantic inference. No keywords or a configured exclusion routes to review.

Low Jev preference probability means affirmative evidence is not established. It
does not prove the opposite. The local LLM adapter has no numerical confidence,
so the profile confidence setting is explicitly marked as not applied.

### Observed Jev wire precision

Live OpenRouter responses on September 25, 2026 exposed independently rounded
numeric fields. One response supplied score `0.62` and probabilities
`{0:0.39, 1:0.61, 2:0}`, whose directly recomputed expectation is `0.61`.
Other observed examples were score `0.35` versus expectation `0.34`, and score
`0.90` versus expectation `0.89`. Some evidence distributions also failed the
original strict sum check. These are integration observations, not quality labels.

The [official Score documentation](https://docs.typesafe.ai/primitives/score)
defines the weighted expectation and normalized probabilities, but does not
promise a particular rounding precision. Adapter validation version
`jev-wire-1.1` therefore applies an explicit **observed wire-precision assumption**,
not a claimed provider guarantee:

1. Try the original strict sum and expectation checks first. Only values exactly
   on the two-decimal numeric grid qualify for the compatibility branch. A
   higher-precision score or probability retains the original strict checks.
2. For each qualifying probability `p`, consider the interval
   `[max(0,p-0.005), min(1,p+0.005)]`. A normalized distribution must exist inside
   those intervals: their lower bounds sum to at most one and their upper bounds
   sum to at least one.
3. For a Score, compute minimum and maximum possible expectations over those same
   intervals **while requiring total probability one**. The returned score's
   `[score-0.005, score+0.005]` interval must intersect this feasible expectation
   interval. This is not a generic tolerance multiplied by the number of options.
4. Choice selection still must be a highest reported probability, within the
   existing `0.002` numeric tolerance. Monotone rounding can create a tie but
   cannot justify selecting a visibly lower option.

All reported probabilities, confidence and scores remain unchanged. Nothing is
renormalized or replaced with a recomputed score. A rescued response carries a
warning and `trace.wire_validation` with rescued fields, reported sums, rounding
step and any feasible expectation interval. Genuinely inconsistent distributions
and scores still fail atomically. The question/routing version stays unchanged
because this update only validates the provider's wire representation.

## Evidence limits

`split_sentences()` is a deterministic punctuation heuristic with common
abbreviation and decimal handling. Each sentence contains a stable local ID and
exact start/end offsets into the unchanged stored abstract. Whitespace at span
boundaries is excluded; internal whitespace is preserved. It is not an NLP
sentence-boundary model.

Baseline highlights only keyword locations. Jev/LLM evidence identifies the
model's selected topical support. Neither establishes entailment, experimental
validity, code availability, replication, or full-text facts. The evidence picker
has a `none` option to avoid forced selection. Paper text can contain adversarial
instructions: separation, bounded answers, validation, and review make this
auditable, but do not guarantee immunity. Human-labeled adversarial evaluation
remains necessary before stronger claims.

## Failure and cost accounting

Malformed provider responses fail atomically: no partial decision is returned.
Errors omit response bodies and credential-bearing exception text. Redirects
are disabled. Responses are bounded to one million decoded bytes. Only `429`
and `529` receive bounded backoff retries (at most three attempts). A timeout or
network failure is not retried automatically because usage may already have
occurred. Cancelling an async task propagates normally.

Usage comes from the provider. Estimated cost is computed only if an input-token
price was explicitly configured; otherwise it is `null`. Provider-supplied cost
fields are not silently substituted. LLM cost estimates cover input tokens only
and say so; any output charges are excluded. Baseline reports zero tokens and
zero cost. Failed/ambiguous requests may incur charges not represented in a
successful-decision report; that report is not an invoice.

## arXiv ingestion

`normalize_arxiv_id()` accepts modern and historical arXiv identifiers, an
optional `arXiv:` prefix, or official `/abs/` and `/pdf/` URLs. Requested `vN`
versions are retained. Other hosts, credentials, custom ports, query parameters,
fragments, encoded path tricks, and invalid identifier forms are rejected.

Requests use the fixed HTTPS arXiv API endpoint. One async limiter serializes
request starts at least 3.1 seconds apart within the app event loop, including
concurrent jobs and official-page fallback requests. Run this local app as one
worker; multiple processes require a shared limiter. XML is limited to two
million decoded bytes and parsed with DTDs, entities, and external references
forbidden. Returned links are rebuilt from validated IDs, not trusted remote
link fields. Requested IDs and versions must match returned papers.

When the API returns `403`, `406`, or selected `5xx` statuses for an ID import,
the adapter may fetch the same paper's official arXiv abstract page. Such papers
carry `metadata_source=arxiv_abstract_page` and a provenance note; citation dates
can have day precision. Normal Atom imports carry
`metadata_source=arxiv_atom_api`. Query searches fail with an actionable message
when the upstream search API is unavailable. No mock papers are substituted.

## Verification

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_engine.py tests/test_arxiv.py tests/test_local_model.py -q
```

Tests exercise fractional Jev scores, invalid probabilities, schema violations,
missing answers, confidence/exclusion boundaries, exact span offsets, honest
unknowns, bounded retries, credential-safe errors, endpoint restrictions,
concurrent rate limiting, unsafe XML, provenance, and official-page fallback.
Local bridge tests also cover typed enum constraints, tokenizer boundaries,
unsupported-schema rejection, and GPU-lock retention after cancellation without
loading a model.
Mock transport tests verify the integration contract; they do not measure model
quality. A live arXiv ID import was additionally exercised during development.
Live Jev quality claims require an actual credential and a separate labeled test.
The optional local Qwen3-4B bridge was additionally exercised on all 60 starter
profile–paper pairs: every final response passed the strict adapter validation.
The [recorded report and protocol](EVALUATION.md) distinguish that format/runtime
measurement from unmeasured relevance quality and live Jev behavior.

Reference implementations follow the [TypeSafe API](https://docs.typesafe.ai/api),
[Jev limitations](https://docs.typesafe.ai/model-jaggedness/jev-1.13),
[OpenRouter Jev Decisions API](https://openrouter.ai/blog/insights/what-is-jev/),
and [arXiv API documentation](https://info.arxiv.org/help/api/user-manual.html).
