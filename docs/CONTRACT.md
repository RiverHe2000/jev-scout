# Jev Scout application contract

A single-user local research workspace with real arXiv ingestion and three explicit analysis modes: `baseline`, `jev`, and `llm`. Bundled papers use an identified keyword baseline. Normal startup binds to loopback; credentials and provider configuration remain server-side. The stack is Python 3.12+, FastAPI, httpx, Pydantic 2, SQLite, and React/TypeScript/Vite.

## Module map

| Module | Responsibility |
| --- | --- |
| `api.py`, `schemas.py`, `config.py` | HTTP boundary, validated inputs, server configuration |
| `store.py`, `jobs.py` | Persistence, revisions, selected decisions, background work and recovery |
| `engine.py`, `arxiv.py` | Provider contracts, evidence, routing, official-source ingestion |
| `exports.py` | Escaped BibTeX, Markdown and JSON exports |
| `fixtures.py`, `evaluation.py` | Attributed fixtures, benchmark methods and label protocol |
| `local_model.py` | Optional local CUDA model service |
| `frontend/src/` | Research inbox, reading state, forms, activity and evidence views |

## Domain JSON

Timestamps are ISO strings; unavailable values are JSON `null`.

**Profile**

`{id,name,question,preferences:[{id,label,question,weight}],exclusions,keywords:[string],seed_papers:[string],daily_limit,confidence_threshold,version,created_at,updated_at,archived}`

Create/update inputs contain editable fields only; update also requires `expected_version`. A mismatched version returns `409`. Preference IDs are unique. Limits include three preferences, weights 0..2, 30 keywords, five seed references, question length 10–3,000 characters, and daily limit 1..50. Keyword/seed entries are trimmed, deduplicated and at most 200 characters each.

`daily_limit` defaults to 10 and controls the client's Read first page size; it is not a scheduler or daily inference quota. `seed_papers` stores reference text but does not automatically import papers or affect inference. `confidence_threshold` defaults to 0.65 and is an uncalibrated Jev review setting; baseline and LLM results do not have numerical confidence.

**Paper**

`{id,arxiv_id,version,title,authors:[string],abstract,categories:[string],published,updated,source_url,pdf_url,source,content_hash,created_at,metadata_source?,source_note?,...}`

`id` is a stable workspace UUID. `arxiv_id` is the base identifier without vN; `version` is a positive integer. Publication/update dates are normalized UTC timestamps. `created_at` is the storage time of the metadata snapshot. Source/PDF links are rebuilt from the validated identifier/version.

Semantic snapshots preserve title, abstract, authors, categories and dates. Verified live provenance may upgrade an otherwise identical bundled snapshot without changing its semantic hash. `source=arxiv` means official-source metadata; `source=bundled` means an attributed public fixture. Live retrieval adds `metadata_source=arxiv_atom_api|arxiv_abstract_page`; the latter includes a note about possible day-precision dates. Additional fixture provenance fields are permitted. This collection is not independently labeled evaluation gold.

Responses currently also include an opaque internal `_version_id` to distinguish metadata snapshots, including corrections at the same arXiv version. Clients must not derive meaning from it. JSON export removes top-level paper fields beginning with `_`.

**Sentence and decision**

`Sentence = {id:'s1',text,start,end}`

Offsets reference the unchanged stored abstract: start inclusive, end exclusive. Splitting uses a punctuation heuristic. Boundary whitespace is excluded; internal text is preserved.

`Decision = {id,paper_id,profile_id,profile_version,paper_version,mode,model,question_version,relevance,confidence,preference_scores:[{id,label,value}],route,rank_score,evidence_ids:[string],sentences:[Sentence],reason,unknowns:[string],warnings:[string],input_tokens,output_tokens,cost_usd,latency_ms,trace,created_at,cache_hit,stale}`

- `mode=baseline|jev|llm`; model records the returned provider model or lexical implementation name.
- Relevance is 0..2. Jev returns a fractional probability-weighted expectation. LLM values are ordinal 0, 1 or 2; an unknown uses zero only as a ranking placeholder, sets `trace.relevance_known=false`, records an unknown notice and routes to review.
- Confidence is Jev's Score confidence or null; it is not measured accuracy or a domain-calibrated probability of correctness.
- Preference value is 0..1 or null: Jev Noul probability, LLM true/false as 1/0, or null for unknown/unassessed.
- Route is `read|skim|review|later`; rank score is for sorting, not a probability. Missing/stale decisions have effective route `review` in list counts/filtering while their original stored routes remain inspectable.
- Evidence IDs reference original spans. Baseline evidence locates keywords. Model evidence is claimed topical support, not a scientific validity or entailment guarantee. No evidence is an allowed answer.
- Reason is an application template, not generated reasoning. Unknowns/warnings retain limitations. Trace contains bounded adapter-specific distributions, choices, policy, matched keywords or structured LLM answers; no credentials or private reasoning.
- Usage comes from successful provider responses. Baseline usage/cost are zero. Cost is null without configured input pricing; LLM estimates cover input tokens only. Failed/ambiguous requests and output-token charges are not reconstructed.
- `cache_hit` is transient on reuse; ordinary subsequent history/list reads return false. Stale status combines stored stale-at-completion state with current profile/paper revision comparisons.

See [INTELLIGENCE.md](INTELLIGENCE.md) for exact thresholds, rank arithmetic, evidence limitations and response validation.

**Reading state and paper views**

`ReadingState = {saved:boolean,status:'unread'|'reading'|'done',note:string,feedback:null|'useful'|'not_now'|'irrelevant'}`

Reading state belongs to a profile–paper pair. PATCH changes only supplied fields. Feedback null clears feedback; saved/status/note cannot be null. Notes are at most 20,000 characters.

`PaperEntry = Paper + {decision:Decision|null,reading:ReadingState}`

`PaperDetail = PaperEntry + {versions:[Paper],decisions:[Decision],activity:[{id,type,created_at,detail}]}`

**Job**

`{id,kind,status,mode,profile_id,total,completed,failed,message,error,created_at,updated_at,finished_at}`

Kind is `ingest|evaluate`; status is `queued|running|completed|failed|cancelled`. Any failed paper makes a run failed while completed decisions remain available. Internal persisted payload/progress references are not returned by public job endpoints.

**Annotation**

`{profile_id,paper_id,relevance,split,note,created_at,profile_version,paper_version_id,paper_version,content_hash,stale}`

Labels capture current input revisions at labeling time; later input changes mark them stale. Relevance is 0..2; split is `development|calibration|test`. Legacy labels without revision references are stale. Workspace annotations are separate from the CLI's reviewed-label file format and are not automatically benchmark gold.

## HTTP API

Frontend requests use same-origin `/api`; the development proxy targets `http://127.0.0.1:8765`. Responses are JSON except exports. Application errors use `{detail:string}`; 422 validation errors may be FastAPI field-error arrays. Missing resources return 404; state/configuration conflicts 409; rejected mutation origins 403; oversized bodies 413. Mutation bodies are limited to 262,144 actual bytes, including chunked transfers. Unknown input fields are rejected.

| Method and path | Input / response |
| --- | --- |
| `GET /api/health` | `{status:'ok',version:'0.1.0'}` |
| `GET /api/settings` | Public settings below; no keys |
| `GET /api/profiles` | `{items:[Profile]}`; `include_archived=true` includes archived cards |
| `POST /api/profiles` | Editable Profile fields → Profile (201) |
| `PUT /api/profiles/{id}` | Editable fields + expected_version → Profile |
| `POST /api/profiles/{id}/archive` | Omitted body archives; `{archived:false}` restores → `{ok:true}` |
| `GET /api/papers` | Filters below → `{items:[PaperEntry],total,counts,profile_version}` |
| `GET /api/papers/{id}?profile_id=...` | PaperDetail; up to 30 recent decisions and activity items |
| `PATCH /api/papers/{id}/reading` | `{profile_id,saved?,status?,note?,feedback?}` → ReadingState |
| `POST /api/ingest` | `{profile_id,query?,ids?,max_results:30,mode:'baseline'}` → Job (202) |
| `POST /api/evaluate` | `{profile_id,mode:'baseline',paper_ids?,force:false}` → Job (202) |
| `GET /api/jobs` | `{items:[Job]}`, most recent 30 |
| `POST /api/jobs/{id}/cancel` | Job; finished jobs remain unchanged |
| `POST /api/jobs/{id}/retry` | New or equivalent active Job (202); only failed/cancelled jobs |
| `GET /api/stats?profile_id=...` | Statistics below |
| `GET /api/export?profile_id=...&format=bibtex&scope=saved` | Download; format bibtex/markdown/json, scope saved/all |
| `GET /api/activity?profile_id=...` | `{items:[{id,type,created_at,detail}]}`; profile optional |
| `POST /api/demo/load` | `{papers,profiles,message}`; preserves profile edits and reading state |
| `GET /api/evaluation` | Default local benchmark report or `{available:false,message}` |
| `GET /api/annotations` | `{items:[Annotation]}` |
| `POST /api/annotations` | `{profile_id,paper_id,relevance,split:'test',note:''}` → `{ok:true}` |

Paper filters: required profile_id; route all/read/skim/review/later; saved=false (true means saved only); status all/unread/reading/done; q up to 300 characters; sort priority/newest; limit defaults 50, range 1..200; offset defaults 0. Counts `{all,read,skim,review,later,saved,unread}` cover the profile's collection before requested filters.

Ingest requires a nonempty query or IDs, exclusively. Queries are at most 1,000 characters without control characters. IDs contain 1–50 official arXiv identifiers/URLs. max_results is 1..100. Imported papers are evaluated with valid cache reuse where allowed. Evaluate accepts up to 1,000 existing workspace paper IDs; omitting IDs selects current collection versions when the job runs. An explicitly empty list is rejected. All three modes are accepted; unconfigured Jev/LLM requests return 409. Omitted request mode defaults to baseline.

Archived profiles cannot be edited, annotated or used for new work until restored. Demo loading skips analysis of archived fixture profiles and does not replace an existing current decision with a baseline.

**Public settings**

`{jev_configured,jev_provider:'typesafe'|'openrouter'|null,model,llm_configured,llm_model,llm_provider,available_modes:[Mode],default_mode,price_per_million_input:number|null,local_only:true,database_path_display:'runtime/scout.sqlite3',version:'0.1.0'}`

LLM provider is local, a configured hostname or an empty string. Database path is a fixed friendly display label, not the absolute configured path. Pricing is the configured Jev input price; credentials and LLM base URL/key are omitted. Default mode prefers configured Jev, then LLM, then baseline. Configured availability does not prove connectivity/authentication has succeeded.

**Statistics**

`{papers,decisions,saved,review,completed_reads,feedback_count,live_decisions,baseline_decisions,llm_decisions,input_tokens,estimated_cost_usd:number|null,latency_p50_ms:number|null,latency_p95_ms:number|null,daily_activity:[{date,evaluated,saved}],route_counts:{read,skim,review,later},recent_runs:[Decision],calibration_status:'not_calibrated'}`

Usage includes persisted historical inference decisions. Cache activation creates no extra inference/cost. live_decisions counts Jev; LLM has its own count. Daily activity covers 14 UTC dates. Aggregate cost is null if any included decision lacks a cost. recent_runs contains up to ten decisions with current stale status.

## Revisions, cache and resume

Profile edits append a revision. Paper ingestion deduplicates identical semantic snapshots and retains historical corrections/versions. Re-importing an existing older snapshot cannot roll the current pointer backward; bundled metadata cannot supersede live metadata at the same arXiv version.

The cache binds paper content, profile ID/version/editable fields, mode, requested model, endpoint, question version and pricing. Reuse requires current profile and paper references. Jev names containing latest or preview bypass reuse across independent jobs. Other configured model names act as stable cache identities; force a new run or change the model identifier when local weights or external aliases change.

A separate selected-decision pointer makes cached method switches visible without duplicating inference records. A stale completion remains inspectable but cannot select itself over current-input analysis. Later input edits make earlier selected decisions stale and effective-route to review.

Active equivalent jobs coalesce using a work key containing the profile revision and, for evaluation, selected paper snapshot references. Progress updates do not change this identity. Cancellation is persisted, attempts to interrupt the async request, and is checked again in the save transaction. Late progress cannot overwrite terminal job status.

Successful decisions are linked to their job. Recovery/retry can reuse these even for force requests or floating Jev aliases, provided current inputs/configuration still match. Completed imports persist their original paper ID set; retry does not substitute changed query results. Running jobs requeue after restart, with completed records and history retained. A cancelled remote request may already have incurred provider usage.

## Intelligence and source interfaces

```python
split_sentences(abstract: str) -> list[dict]
build_questions(paper: dict, profile: dict) -> dict

async def evaluate(
    paper: dict, profile: dict, *, mode: str,
    api_key: str | None = None, model: str = "jev-latest",
    timeout: float = 30, client: httpx.AsyncClient | None = None,
    price_per_million_input: float | None = None,
    base_url: str | None = None, endpoint: str | None = None,
) -> dict: ...

async def fetch_papers(
    *, query: str | None = None, ids: list[str] | None = None,
    max_results: int = 30, client: httpx.AsyncClient | None = None,
) -> list[dict]: ...

normalize_arxiv_id(value: str) -> str
```

build_questions returns the exact Jev `{model,state,questions}` body: one relevance Score, an evidence Choice over original sentence IDs plus none, an optional exclusion Noul, and up to three preference Nouls. evaluate returns engine fields and trace; persistence supplies decision ID, creation timestamp and cache/stale state. `QUESTION_VERSION` identifies the question/policy version.

Jev endpoint is restricted to the official TypeSafe/OpenRouter Decisions URLs. LLM base_url is trusted configuration before `/chat/completions`; remote providers require HTTPS. Strict LLM schemas preserve unknowns. Invalid/partial answers raise credential-safe EngineError; no adapter silently falls back to another mode.

normalize_arxiv_id retains explicit vN. Fetched papers split this into base arxiv_id and integer version, without workspace IDs/hash/storage time. Requests use official endpoints, bounded safe parsing and credential-safe ArxivError messages. A shared per-event-loop limiter spaces starts at least 3.1 seconds apart. This app uses one process/worker; multiple processes would require a shared limiter.

## Fixture and evaluation boundary

`fixtures.load_papers()` and `fixtures.load_profiles()` load packaged data independently of cwd. Profiles include fixture_key for idempotent seeding. Public papers and synthetic protocol tests have distinct provenance.

The benchmark compares keyword coverage, TF-IDF, BM25 and explicitly requested Jev/LLM runs. Reports contain dataset/protocol provenance, method status, measured runtime/usage, errors and quality availability. Without reviewed labels, ranking-quality claims remain unavailable. Jev confidence is not relabeled as correctness probability. Group/time and annotation-version guards apply to the CLI label protocol.

Default output is `artifacts/evaluation/report.json`; the CLI can write another path. The API reads the default report; it does not run a benchmark or merge workspace annotations automatically. Passing contract tests demonstrates integration behavior, not scientific relevance quality.
