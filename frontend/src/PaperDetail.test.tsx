import { render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import PaperDetail from "./PaperDetail";
import type { PaperDetail as Detail, Profile } from "./types";

it("scopes high Jev confidence to relatedness while retaining an evidence-review route", async () => {
  const profile: Profile = {
    id: "synthetic-profile",
    name: "Synthetic research profile",
    question: "A synthetic relatedness question?",
    preferences: [],
    exclusions: "",
    keywords: [],
    seed_papers: [],
    daily_limit: 10,
    confidence_threshold: 0.65,
    version: 1,
    created_at: "2026-01-01",
    updated_at: "2026-01-01",
    archived: false,
  };
  const paper: Detail = {
    id: "synthetic-paper",
    arxiv_id: "test-only",
    title: "Synthetic paper for interface semantics",
    version: 1,
    authors: ["Synthetic author"],
    abstract: "Synthetic test abstract.",
    categories: [],
    published: "2026-01-01",
    updated: "2026-01-01",
    source_url: "https://arxiv.org",
    pdf_url: "https://arxiv.org",
    source: "test",
    content_hash: "test",
    created_at: "2026-01-01",
    reading: { saved: false, status: "unread", note: "", feedback: null },
    versions: [],
    decisions: [],
    activity: [],
    decision: {
      id: "synthetic-decision",
      paper_id: "synthetic-paper",
      profile_id: profile.id,
      profile_version: 1,
      paper_version: 1,
      mode: "jev",
      model: "test-model",
      question_version: "test",
      relevance: 2,
      confidence: 1,
      preference_scores: [],
      route: "review",
      rank_score: 2,
      evidence_ids: [],
      sentences: [],
      reason: "Evidence selection needs review.",
      unknowns: ["Evidence is uncertain."],
      warnings: [],
      input_tokens: 0,
      output_tokens: 0,
      cost_usd: 0,
      latency_ms: 0,
      created_at: "2026-01-01",
      cache_hit: false,
      stale: false,
    },
  };
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => new Response(JSON.stringify(paper))),
  );
  render(
    <PaperDetail
      paperId={paper.id}
      profile={profile}
      refresh={0}
      onReading={async () => {}}
      onAnalyze={vi.fn()}
      onClose={vi.fn()}
    />,
  );
  const confidence = await screen.findByText("100% relatedness confidence");
  expect(confidence).toHaveAttribute(
    "title",
    "Uncalibrated model confidence for the relatedness question. Evidence selection is assessed separately; this is not measured accuracy.",
  );
  expect(screen.getByText("Needs review")).toBeInTheDocument();
  expect(
    screen.getByText("Evidence selection needs review."),
  ).toBeInTheDocument();
});
