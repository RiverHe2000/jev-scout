# Public-paper starter collection

`papers.json` is a fixed, attributed snapshot of **20 real arXiv papers**. It contains authors, titles, abstracts, categories, original publication dates, current revision dates, versioned source/PDF links, and retrieval provenance. It contains no PDFs, paper body text, extracted figures, or invented paper records.

The collection was retrieved on **2026-09-25** from official `https://arxiv.org/abs/…` pages. An initial request to the official Atom API returned HTTP 406 in the development environment; the maintenance script therefore reads the same descriptive metadata from the official abstract page's `citation_*` tags. Retrieval is serial, with starts at least 3.1 seconds apart. Page-reported dates have day precision; no publication time is invented. The records are a demonstration snapshot, not a current feed, representative sample, or evaluation gold set.

arXiv makes descriptive metadata, including title, abstract, authors, identifiers, and classification terms, available under **CC0 1.0**. See the [official API terms](https://info.arxiv.org/help/api/tou.html) and [CC0 dedication](https://creativecommons.org/publicdomain/zero/1.0/). Each record additionally preserves the *article's* license URL in `provenance.license_url`; that separate license applies to article content and is not a blanket license for PDFs or figures. Jev Scout is not endorsed by arXiv or the paper authors.

`profiles.json` contains three editable starter research questions. Their stable `fixture_key` values support idempotent loading. These questions and their keyword lists are product examples, not labels of paper relevance.

`annotations.template.json` contains **60 unlabelled profile–paper pairs**. Every grade is deliberately `null`. Copy the template before annotation and follow [the evaluation protocol](../docs/EVALUATION.md). No author-reference judgements or independent human labels are bundled.

The maintenance script `refresh_public_collection.py` fills missing IDs only and preserves existing frozen records. Review source versions and annotation compatibility explicitly before replacing a snapshot. It does not silently change an existing benchmark corpus.

## Source index

The complete machine-readable attribution is in `papers.json`. A compact index is in [SOURCES.md](SOURCES.md).
