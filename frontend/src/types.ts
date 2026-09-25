export type Mode = "baseline" | "jev" | "llm";
export type Route = "read" | "skim" | "review" | "later";
export type Page = "inbox" | "saved" | "profiles" | "insights" | "settings";
export type ReadingStatus = "unread" | "reading" | "done";
export interface Preference {
  id: string;
  label: string;
  question: string;
  weight: number;
}
export interface Profile {
  id: string;
  name: string;
  question: string;
  preferences: Preference[];
  exclusions: string;
  keywords: string[];
  seed_papers: string[];
  daily_limit: number;
  confidence_threshold: number;
  version: number;
  created_at: string;
  updated_at: string;
  archived: boolean;
}
export type ProfileInput = Omit<
  Profile,
  "id" | "version" | "created_at" | "updated_at" | "archived"
>;
export interface Sentence {
  id: string;
  text: string;
  start: number;
  end: number;
}
export interface Decision {
  id: string;
  paper_id: string;
  profile_id: string;
  profile_version: number;
  paper_version: number;
  mode: Mode;
  model: string;
  question_version: string;
  relevance: number;
  confidence: number | null;
  preference_scores: { id: string; label: string; value: number | null }[];
  route: Route;
  rank_score: number;
  evidence_ids: string[];
  sentences: Sentence[];
  reason: string;
  unknowns: string[];
  warnings: string[];
  input_tokens: number;
  output_tokens: number;
  cost_usd: number | null;
  latency_ms: number;
  created_at: string;
  cache_hit: boolean;
  stale: boolean;
}
export interface ReadingState {
  saved: boolean;
  status: ReadingStatus;
  note: string;
  feedback: null | "useful" | "not_now" | "irrelevant";
}
export interface Paper {
  id: string;
  arxiv_id: string;
  version: number;
  title: string;
  authors: string[];
  abstract: string;
  categories: string[];
  published: string;
  updated: string;
  source_url: string;
  pdf_url: string;
  source: string;
  content_hash: string;
  created_at: string;
}
export interface PaperEntry extends Paper {
  decision: Decision | null;
  reading: ReadingState;
}
export interface Activity {
  id: string;
  type: string;
  created_at: string;
  detail: Record<string, unknown> | string;
}
export interface PaperDetail extends PaperEntry {
  versions: Paper[];
  decisions: Decision[];
  activity: Activity[];
}
export interface PaperResponse {
  items: PaperEntry[];
  total: number;
  counts: Record<"all" | "saved" | "unread" | Route, number>;
  profile_version: number;
}
export interface Job {
  id: string;
  kind: "ingest" | "evaluate";
  status: "queued" | "running" | "completed" | "failed" | "cancelled";
  mode: Mode;
  profile_id: string;
  total: number;
  completed: number;
  failed: number;
  message: string;
  error: string | null;
  created_at: string;
  updated_at: string;
  finished_at: string | null;
}
export interface Settings {
  jev_configured: boolean;
  jev_provider: "typesafe" | "openrouter" | null;
  llm_configured: boolean;
  llm_model: string;
  llm_provider: string;
  available_modes: Mode[];
  model: string;
  default_mode: Mode;
  price_per_million_input: number | null;
  local_only: true;
  database_path_display: string;
  version: string;
}
export interface Stats {
  papers: number;
  decisions: number;
  saved: number;
  review: number;
  completed_reads: number;
  feedback_count: number;
  live_decisions: number;
  baseline_decisions: number;
  llm_decisions?: number;
  input_tokens: number;
  estimated_cost_usd: number | null;
  latency_p50_ms: number | null;
  latency_p95_ms: number | null;
  daily_activity: { date: string; evaluated: number; saved: number }[];
  route_counts: Record<Route, number>;
  recent_runs: Decision[];
  calibration_status: "not_calibrated";
}
