# A five-minute Jev Scout walkthrough

This demo uses a local research workspace and 20 real, attributed papers. Start the app using the root README. The starter collection works offline in the clearly labelled **lexical baseline** mode. A configured local or hosted language model can be demonstrated separately; call it Jev only when the selected provider is actually Jev.

## 1. Start with a research question

Open the **Agent memory & reliability** profile. Explain the task: “I want to find work that helps an agent retain useful information across sessions, and understand where long-context systems fail.” The question is separate from the explicit keyword list used by the offline baseline.

Show the other two starter profiles: **Efficient LLM systems** and **Retrieval & personalization**. Switching profiles changes the research question and the prioritization of the same papers. That makes the product's purpose visible without a slide full of architecture.

## 2. Inspect one recommendation

Search for **MemGPT** and open its detail. Show the original abstract, authors, versioned arXiv source link, and recorded decision mode. For the offline baseline, explain that highlighted text locates matched keywords; it does not claim semantic understanding. For actual model mode, show selected source sentences and any unknowns or review route.

Open the source link if you need to substantiate the paper's identity. The app indexes abstract metadata, not entire PDFs. It cannot establish experimental details that are absent from the abstract.

## 3. Turn a queue into a reading workflow

Save a paper, move its reading status forward, and add a short note such as “Compare memory evaluation tasks with LongMemEval.” Record useful/not-now/irrelevant feedback. Export saved items in Markdown or BibTeX and inspect the downloaded citations.

Feedback is stored for review and analysis. Do not describe this release as learning preferences automatically from clicks unless a later implementation actually adds and evaluates that behavior.

## 4. Show change and provenance

Edit a research profile, save the new version, and reevaluate. Explain why old decisions become stale when a research question changes. Show the run/job history and visible mode. A live import can use arXiv identifiers or a query when the network is available; the bundled snapshot keeps the walkthrough usable without a live arXiv dependency.

If a model provider is configured, run a small actual batch and identify the provider and model by name. A local Qwen run is an LLM run, not Jev. Do not call a mocked test response or offline lexical score an inference result.

For the optional Qwen bridge, explain that constrained decoding keeps answers inside the supported JSON schema while the application's own validator still checks them. The product retains unknown answers and review states; a valid response format does not guarantee a correct research recommendation.

## 5. Finish with an honest evaluation panel

Show the measured baseline report and the recorded local Qwen run: 60 profile–paper decisions passed structural validation, with actual runtime and token usage. Explain why relevance-quality scores are still unavailable: no reviewed relevance labels have been collected yet. Point to the blank annotation workflow and group/time holdout protocol. Distinguishing valid output and measured runtime from unmeasured utility is an engineering decision worth explaining in an interview.

For a recording, use the local dataset, keep credentials out of view, and avoid editing real notes you need to preserve. The project does not need to be pushed or published to run this walkthrough.

## Claims to keep precise

Say “a working research triage workspace with attributed abstract evidence, versioned decisions, explicit inference modes, and a reproducible evaluation harness.” Real Jev and local Qwen runtime measurements are recorded in RESULTS.md. Show Jev's partial 59/60 benchmark status and the separate completed 21-paper workspace job accurately. Do not claim reduced reading time, improved relevance, calibrated confidence, active users, or generalized provider performance without corresponding evidence.
