# Exploratory AI-reference relevance review

Frozen before inspecting any saved method rankings on 2026-09-27. This is an
independent assistant task review requested by the project owner, **not a human
user study or expert gold standard**.

## Fixed scope and judgement rules

- Use all 20 already-attributed abstracts, their frozen versions, and all three
  unchanged starter profiles. No paper, profile, failed prediction or method may
  be dropped because its result is inconvenient.
- Grade the utility of the abstract for the complete profile question: 2 directly
  addresses the need with a concrete method or relevant evaluation; 1 supplies a
  supporting mechanism or adjacent evidence; 0 does not address the need.
- Distinguish conversational memory from GPU memory, personal adaptation from
  population preference alignment, and evidence quality from general agent skill.
  Infrastructure alone is not evidence of reliable conversational memory.
- Read only profiles, titles and abstracts while judging. Do not inspect recorded
  model rankings, scores, selected evidence or routes until labels are committed.
- Record a short rationale for every pair. Borderline cases also list plausible
  alternative grades; freeze them with the reference rather than after scoring.
- Label provenance is `ai_reference`, the annotator is an AI assistant, and
  `independent_review` remains false. No actual participants are represented.

## Evaluation after freezing

Rescore the original immutable Qwen, Jev and lexical results without making new
provider calls. Check corpus and protocol identity, complete candidate sets,
unique paper IDs, versions, profile definitions and source-file hashes. Preserve
the original run dates, model names, failed requests, latency units and cost
estimates. The rescore timestamp is separate from inference timestamps.

Report nDCG@5, Precision@5 and Recall@5 per profile and their macro averages under
the existing metric definitions. Incomplete method/profile candidate sets remain
unscored. Give a separate comparison on the common complete profiles so a method
with a failed request cannot appear superior by silently losing a hard profile.
Report the count and identity of excluded profiles. Do not impute failed model
decisions from another provider or rerun them selectively.

Evaluate each predeclared alternative label one at a time, leaving every other
label fixed. This is a subjective-label sensitivity analysis, not a confidence
interval. Three curated profiles cannot support a population significance claim.
Record all changes; do not tune prompts, keywords, thresholds or labels from them.

## What the result can support

This review can identify ranking disagreements and targeted cases for later
human inspection. Agreement with an AI reference is not recommendation accuracy
for real users. The corpus and models may share pretraining knowledge. Abstracts
omit full-paper details, and the reference was created after the historical model
runs even though their rankings were hidden during annotation. Keep author,
independent-human and AI references distinct. No user time savings are inferred.
