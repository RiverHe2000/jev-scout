import { useState } from "react";
import {
  Activity as ActivityIcon,
  Archive,
  ArrowRight,
  ArrowUpRight,
  BarChart3,
  BookOpen,
  Check,
  ChevronRight,
  CircleAlert,
  Clipboard,
  Clock3,
  Database,
  FileText,
  FlaskConical,
  FolderOpen,
  Layers3,
  LockKeyhole,
  Pencil,
  Plus,
  RefreshCw,
  RotateCcw,
  Search,
  Settings2,
  ShieldCheck,
  Sparkles,
  Square,
  Target,
  X,
} from "lucide-react";
import { formatDate, formatNumber } from "./api";
import {
  Empty,
  ErrorPanel,
  ModeBadge,
  routeNames,
  Spinner,
} from "./components";
import type { Activity, Job, Profile, Route, Settings, Stats } from "./types";

export function JobsList({
  jobs,
  onAction,
  busy,
}: {
  jobs: Job[];
  onAction: (job: Job, action: "cancel" | "retry") => void;
  busy: string;
}) {
  return jobs.length ? (
    <div className="jobs-list">
      {jobs.map((job) => (
        <div className="job-item" key={job.id}>
          <div className={`job-icon ${job.status}`}>
            {job.status === "running" || job.status === "queued" ? (
              <RefreshCw size={17} className="spinning" />
            ) : job.status === "completed" ? (
              <Check size={18} />
            ) : job.status === "failed" ? (
              <CircleAlert size={18} />
            ) : (
              <Square size={15} />
            )}
          </div>
          <div className="job-body">
            <div className="job-heading">
              <strong>
                {job.kind === "ingest" ? "arXiv import" : "Paper analysis"}
              </strong>
              <span className={`status-pill ${job.status}`}>{job.status}</span>
            </div>
            <p>
              {job.message ||
                `${job.completed} of ${job.total} papers processed`}
            </p>
            {(job.status === "running" || job.status === "queued") && (
              <progress
                aria-label="Job progress"
                max={Math.max(job.total, 1)}
                value={job.completed}
              />
            )}
            <div className="job-meta">
              <ModeBadge mode={job.mode} />
              <span>
                {job.completed}/{job.total} complete
                {job.failed ? ` · ${job.failed} failed` : ""}
              </span>
              <span>{formatDate(job.created_at)}</span>
            </div>
            {job.error && <p className="job-error">{job.error}</p>}
          </div>
          {(job.status === "running" || job.status === "queued") && (
            <button
              className="icon-button"
              disabled={busy === job.id}
              aria-label="Cancel job"
              onClick={() => onAction(job, "cancel")}
            >
              <X size={17} />
            </button>
          )}
          {(job.status === "failed" || job.status === "cancelled") && (
            <button
              className="button secondary small"
              disabled={busy === job.id}
              onClick={() => onAction(job, "retry")}
            >
              <RotateCcw size={13} />
              Retry
            </button>
          )}
        </div>
      ))}
    </div>
  ) : (
    <Empty icon={<ActivityIcon size={26} />} title="All quiet here">
      Imports and analyses will appear here, with progress and a record of what
      happened.
    </Empty>
  );
}

export function ProfilesPage({
  profiles,
  activeId,
  onSelect,
  onEdit,
  onCreate,
  onArchive,
}: {
  profiles: Profile[];
  activeId: string;
  onSelect: (profile: Profile) => void;
  onEdit: (profile: Profile) => void;
  onCreate: () => void;
  onArchive: (profile: Profile) => void;
}) {
  const [showArchived, setShowArchived] = useState(false);
  const visible = profiles.filter((p) =>
    showArchived ? p.archived : !p.archived,
  );
  return (
    <div className="page-content">
      <div className="page-heading">
        <div>
          <span className="eyebrow">BETTER QUESTIONS, BETTER READING</span>
          <h1>A lens for your research.</h1>
          <p>
            Make your priorities explicit. See the same literature from a
            different perspective.
          </p>
        </div>
        <button className="button primary" onClick={onCreate}>
          <Plus size={17} />
          New profile
        </button>
      </div>
      <div className="profile-toolbar">
        <div className="segmented compact">
          <button
            className={!showArchived ? "active" : ""}
            onClick={() => setShowArchived(false)}
          >
            Active profiles{" "}
            <span>{profiles.filter((p) => !p.archived).length}</span>
          </button>
          <button
            className={showArchived ? "active" : ""}
            onClick={() => setShowArchived(true)}
          >
            Archived <span>{profiles.filter((p) => p.archived).length}</span>
          </button>
        </div>
        <span className="muted small-text">
          Each profile keeps its own reading list and feedback.
        </span>
      </div>
      {visible.length ? (
        <div className="profile-grid">
          {visible.map((profile, index) => (
            <article
              className={`profile-card ${activeId === profile.id ? "current" : ""}`}
              key={profile.id}
            >
              <div className="profile-card-top">
                <span className={`profile-icon color-${index % 3}`}>
                  <Target size={22} />
                </span>
                <div className="profile-card-tools">
                  {activeId === profile.id && !profile.archived && (
                    <span className="current-label">Current lens</span>
                  )}
                  <button
                    className="icon-button small"
                    onClick={() => onEdit(profile)}
                    aria-label={`Edit ${profile.name}`}
                  >
                    <Pencil size={16} />
                  </button>
                </div>
              </div>
              <h2>{profile.name}</h2>
              <p className="profile-question">{profile.question}</p>
              <div className="profile-preferences">
                {profile.preferences.length ? (
                  profile.preferences.map((p) => (
                    <span key={p.id}>
                      {p.label}
                      <small>{p.weight.toFixed(1)}×</small>
                    </span>
                  ))
                ) : (
                  <span>No extra preferences</span>
                )}
              </div>
              <div className="profile-card-meta">
                <span>
                  <BookOpen size={13} />
                  {profile.daily_limit}-paper daily focus
                </span>
                <span>Version {profile.version}</span>
              </div>
              <div className="profile-card-footer">
                {profile.archived ? (
                  <button
                    className="text-button"
                    onClick={() => onArchive(profile)}
                  >
                    <RotateCcw size={14} />
                    Restore profile
                  </button>
                ) : (
                  <button
                    className="text-button"
                    onClick={() => onSelect(profile)}
                  >
                    Explore this queue <ArrowRight size={15} />
                  </button>
                )}
                <button
                  className="icon-button small"
                  aria-label={
                    profile.archived
                      ? `Restore ${profile.name}`
                      : `Archive ${profile.name}`
                  }
                  onClick={() => onArchive(profile)}
                >
                  {profile.archived ? (
                    <RotateCcw size={15} />
                  ) : (
                    <Archive size={15} />
                  )}
                </button>
              </div>
            </article>
          ))}
          {!showArchived && (
            <button className="new-profile-card" onClick={onCreate}>
              <span>
                <Plus size={24} />
              </span>
              <strong>A different research question?</strong>
              <p>Create another lens for your library.</p>
              <span className="text-button">
                Build a research profile <ArrowRight size={15} />
              </span>
            </button>
          )}
        </div>
      ) : (
        <Empty
          icon={<FolderOpen size={28} />}
          title={
            showArchived ? "Nothing archived" : "Your first research question"
          }
          action={
            !showArchived && (
              <button className="button primary" onClick={onCreate}>
                <Plus size={16} />
                Create a profile
              </button>
            )
          }
        >
          {showArchived
            ? "Archived profiles can be restored here."
            : "Create a profile to start sorting papers around the work you care about."}
        </Empty>
      )}
      <div className="principle-note">
        <ShieldCheck size={22} />
        <div>
          <strong>Personalization you can inspect.</strong>
          <p>
            Preferences are explicit and versioned. Your feedback is recorded
            separately, and earlier decisions remain traceable when your
            question evolves.
          </p>
        </div>
      </div>
    </div>
  );
}

interface BenchmarkMethod {
  id: string;
  label: string;
  mode: string;
  status: string;
  quality?: {
    evaluated: boolean;
    ndcg_at_5?: number | null;
    precision_at_5?: number | null;
    recall_at_5?: number | null;
    brier?: number | null;
    ece?: number | null;
  };
  runtime?: {
    evaluated_pairs: number;
    elapsed_ms: number;
    latency_p50_ms: number | null;
    latency_p95_ms: number | null;
    input_tokens: number;
    output_tokens: number;
    cost_usd: number | null;
  };
}
export interface Benchmark {
  available: boolean;
  message?: string;
  quality_evaluated?: boolean;
  generated_at?: string;
  dataset?: {
    papers: number;
    profiles: number;
    pairs: number;
    provenance: string;
    label_status: string;
  };
  methods?: BenchmarkMethod[];
  limitations?: string[];
  protocol?: unknown;
}
export function InsightsPage({
  stats,
  jobs,
  activity,
  benchmark,
  onJobAction,
  jobBusy,
  loading,
  error,
  onRetry,
}: {
  stats: Stats | null;
  jobs: Job[];
  activity: Activity[];
  benchmark: Benchmark | null;
  onJobAction: (job: Job, action: "cancel" | "retry") => void;
  jobBusy: string;
  loading: boolean;
  error: string | null;
  onRetry: () => void;
}) {
  const [tab, setTab] = useState<"overview" | "jobs" | "benchmark">("overview");
  const routes: Route[] = ["read", "skim", "review", "later"];
  const maxActivity = Math.max(
    1,
    ...(stats?.daily_activity || []).map((d) => d.evaluated),
  );
  return (
    <div className="page-content">
      <div className="page-heading">
        <div>
          <span className="eyebrow">OBSERVE THE WORK, NOT JUST THE OUTPUT</span>
          <h1>A little perspective.</h1>
          <p>
            Your reading rhythm, analysis runs, and measured performance in one
            place.
          </p>
        </div>
        <button className="button secondary" onClick={onRetry}>
          <RefreshCw size={16} />
          Refresh
        </button>
      </div>
      <div className="page-tabs">
        {[
          { id: "overview", label: "Workspace overview", icon: BarChart3 },
          { id: "jobs", label: "Activity & jobs", icon: ActivityIcon },
          { id: "benchmark", label: "Evaluation lab", icon: FlaskConical },
        ].map((item) => (
          <button
            key={item.id}
            className={tab === item.id ? "active" : ""}
            onClick={() => setTab(item.id as typeof tab)}
          >
            <item.icon size={16} />
            {item.label}
          </button>
        ))}
      </div>
      {error && <ErrorPanel message={error} retry={onRetry} />}
      {loading && !stats && <Spinner label="Loading workspace insights" />}
      {tab === "overview" && stats && (
        <>
          <div className="insight-metrics">
            <Metric
              label="Papers in your library"
              value={formatNumber(stats.papers)}
              icon={<FileText size={18} />}
              sub={`${stats.decisions} recorded decisions`}
            />
            <Metric
              label="Saved for a closer look"
              value={formatNumber(stats.saved)}
              icon={<BookmarkIcon />}
              sub={`${stats.completed_reads} finished reading`}
            />
            <Metric
              label="Research feedback"
              value={formatNumber(stats.feedback_count)}
              icon={<Target size={18} />}
              sub="Explicit responses, never inferred clicks"
            />
            <Metric
              label="Recorded analysis cost"
              value={
                stats.estimated_cost_usd === null
                  ? "Unavailable"
                  : `$${stats.estimated_cost_usd.toFixed(4)}`
              }
              icon={<Layers3 size={18} />}
              sub={`${formatNumber(stats.input_tokens)} input tokens`}
            />
          </div>
          <div className="insights-grid">
            <section className="surface chart-panel">
              <div className="surface-heading">
                <div>
                  <h2>Your research rhythm</h2>
                  <p>Papers analyzed in recent days</p>
                </div>
                <span className="chart-legend">
                  <span /> Analyses
                </span>
              </div>
              {stats.daily_activity.length ? (
                <div
                  className="activity-chart"
                  role="img"
                  aria-label={stats.daily_activity
                    .map(
                      (d) =>
                        `${d.date}: ${d.evaluated} analyzed, ${d.saved} saved`,
                    )
                    .join("; ")}
                >
                  {stats.daily_activity.slice(-14).map((day) => (
                    <div className="chart-column" key={day.date}>
                      <span className="chart-value">{day.evaluated || ""}</span>
                      <div className="chart-bar-wrap">
                        <div
                          className="chart-bar"
                          style={{
                            height: `${Math.max(2, (day.evaluated / maxActivity) * 100)}%`,
                          }}
                          title={`${day.evaluated} analyses · ${day.saved} saved`}
                        />
                      </div>
                      <span className="chart-date">
                        {new Date(day.date).toLocaleDateString("en-US", {
                          month: "short",
                          day: "numeric",
                        })}
                      </span>
                    </div>
                  ))}
                </div>
              ) : (
                <Empty
                  icon={<BarChart3 size={24} />}
                  title="Your rhythm starts here"
                >
                  Analyze a few papers to see activity over time.
                </Empty>
              )}
            </section>
            <section className="surface routes-panel">
              <div className="surface-heading">
                <div>
                  <h2>Where papers land</h2>
                  <p>Current decisions for this profile</p>
                </div>
              </div>
              <div className="route-distribution">
                {routes.map((route) => (
                  <div className={`distribution-row ${route}`} key={route}>
                    <div>
                      <span className="route-dot" />
                      {routeNames[route]}
                      <strong>{stats.route_counts[route]}</strong>
                    </div>
                    <div className="distribution-track">
                      <span
                        style={{
                          width: `${stats.papers ? (stats.route_counts[route] / stats.papers) * 100 : 0}%`,
                        }}
                      />
                    </div>
                  </div>
                ))}
              </div>
            </section>
          </div>
          <div className="insights-grid">
            <section className="surface method-panel">
              <div className="surface-heading">
                <div>
                  <h2>Know what did the work</h2>
                  <p>Methods remain visible in every decision.</p>
                </div>
                <Layers3 size={20} />
              </div>
              <div className="method-counts">
                <div>
                  <ModeBadge mode="baseline" />
                  <strong>{formatNumber(stats.baseline_decisions)}</strong>
                </div>
                <div>
                  <ModeBadge mode="jev" />
                  <strong>{formatNumber(stats.live_decisions)}</strong>
                </div>
                <div>
                  <ModeBadge mode="llm" />
                  <strong>{formatNumber(stats.llm_decisions || 0)}</strong>
                </div>
              </div>
              <p className="form-note">
                Baseline matches are not Jev results. Confidence scores are not
                calibrated accuracy estimates.
              </p>
            </section>
            <section className="surface latency-panel">
              <div className="surface-heading">
                <div>
                  <h2>Recorded latency</h2>
                  <p>Actual analysis times, across recorded methods</p>
                </div>
                <Clock3 size={20} />
              </div>
              <div className="latency-numbers">
                <div>
                  <span>MEDIAN · P50</span>
                  <strong>
                    {formatNumber(stats.latency_p50_ms)}
                    <small> ms</small>
                  </strong>
                </div>
                <div>
                  <span>P95</span>
                  <strong>
                    {formatNumber(stats.latency_p95_ms)}
                    <small> ms</small>
                  </strong>
                </div>
              </div>
              <p className="form-note">
                Latency depends on the method, model, and local hardware.
              </p>
            </section>
          </div>
        </>
      )}
      {tab === "jobs" && (
        <div className="insights-grid jobs-grid">
          <section className="surface">
            <div className="surface-heading">
              <div>
                <h2>Background work</h2>
                <p>Persistent jobs, with cancellation and retry.</p>
              </div>
              <ActivityIcon size={20} />
            </div>
            <JobsList jobs={jobs} onAction={onJobAction} busy={jobBusy} />
          </section>
          <section className="surface">
            <div className="surface-heading">
              <div>
                <h2>Workspace activity</h2>
                <p>Changes recorded for this research profile</p>
              </div>
            </div>
            {activity.length ? (
              <div className="activity-feed">
                {activity.slice(0, 25).map((event) => (
                  <div className="activity-event" key={event.id}>
                    <span>
                      <Check size={12} />
                    </span>
                    <div>
                      <strong>{event.type.replaceAll("_", " ")}</strong>
                      <p>{activityDescription(event.detail)}</p>
                      <time>{formatDate(event.created_at)}</time>
                    </div>
                  </div>
                ))}
              </div>
            ) : (
              <Empty icon={<ActivityIcon size={25} />} title="A clean notebook">
                Reading changes and decisions will appear here.
              </Empty>
            )}
          </section>
        </div>
      )}
      {tab === "benchmark" && (
        <section className="surface benchmark-panel">
          <div className="surface-heading">
            <div>
              <span className="eyebrow">MEASURE BEFORE YOU CLAIM</span>
              <h2>The evaluation lab</h2>
              <p>
                Runtime measurements and quality evaluation are reported
                separately.
              </p>
            </div>
            <FlaskConical size={28} />
          </div>
          {benchmark?.available ? (
            <>
              <div
                className={`benchmark-notice ${benchmark.quality_evaluated ? "verified" : ""}`}
              >
                <CircleAlert size={20} />
                <div>
                  <strong>
                    {benchmark.quality_evaluated
                      ? "Quality measurements are available"
                      : "Runtime measured. Recommendation quality not yet validated."}
                  </strong>
                  <p>
                    {benchmark.dataset?.papers} papers ·{" "}
                    {benchmark.dataset?.profiles} profiles ·{" "}
                    {benchmark.dataset?.pairs} pairs. Labels:{" "}
                    {benchmark.dataset?.label_status ||
                      "No independent human labels"}
                    .
                  </p>
                </div>
              </div>
              <div className="table-scroll">
                <table className="benchmark-table">
                  <thead>
                    <tr>
                      <th>Method</th>
                      <th>Status</th>
                      <th>Pairs</th>
                      <th>P50 latency</th>
                      <th>P95 latency</th>
                      <th>Recorded cost</th>
                      <th>nDCG@5</th>
                    </tr>
                  </thead>
                  <tbody>
                    {benchmark.methods?.map((method) => (
                      <tr key={method.id}>
                        <td>
                          <strong>{method.label}</strong>
                        </td>
                        <td>{method.status.replaceAll("_", " ")}</td>
                        <td>{method.runtime?.evaluated_pairs ?? "—"}</td>
                        <td>
                          {formatNumber(method.runtime?.latency_p50_ms)} ms
                        </td>
                        <td>
                          {formatNumber(method.runtime?.latency_p95_ms)} ms
                        </td>
                        <td>
                          {method.runtime?.cost_usd == null
                            ? "Unavailable"
                            : `$${method.runtime.cost_usd.toFixed(5)}`}
                        </td>
                        <td>
                          {method.quality?.evaluated
                            ? formatNumber(method.quality.ndcg_at_5)
                            : "Not evaluated"}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              {benchmark.limitations?.length && (
                <div className="benchmark-limitations">
                  <h3>How to read these results</h3>
                  <ul>
                    {benchmark.limitations.map((limitation, i) => (
                      <li key={i}>{limitation}</li>
                    ))}
                  </ul>
                </div>
              )}
              <p className="source-note">
                Generated{" "}
                {benchmark.generated_at
                  ? formatDate(benchmark.generated_at)
                  : "locally"}
                . Public-paper collections are not human-labeled evaluation
                gold.
              </p>
            </>
          ) : (
            <Empty
              icon={<FlaskConical size={30} />}
              title="Room for real evidence"
            >
              {benchmark?.message ||
                "Run the local benchmark to add a reproducible report. No quality numbers are invented for the demo."}
            </Empty>
          )}
        </section>
      )}
    </div>
  );
}
function BookmarkIcon() {
  return <BookOpen size={18} />;
}
function Metric({
  label,
  value,
  icon,
  sub,
}: {
  label: string;
  value: string;
  icon: React.ReactNode;
  sub: string;
}) {
  return (
    <div className="insight-metric">
      <div>
        {label}
        {icon}
      </div>
      <strong>{value}</strong>
      <span>{sub}</span>
    </div>
  );
}
function activityDescription(detail: Activity["detail"]) {
  if (typeof detail === "string") return detail;
  const meaningful = Object.entries(detail)
    .filter(([key]) => !key.endsWith("_id") && key !== "id")
    .slice(0, 3);
  return (
    meaningful
      .map(
        ([key, value]) =>
          `${key.replaceAll("_", " ")}: ${typeof value === "object" ? JSON.stringify(value) : String(value)}`,
      )
      .join(" · ") || "Workspace updated"
  );
}

export function SettingsPage({
  settings,
  onRefresh,
  onLoadDemo,
  demoBusy,
  onToast,
}: {
  settings: Settings | null;
  onRefresh: () => void;
  onLoadDemo: () => void;
  demoBusy: boolean;
  onToast: (message: string, error?: boolean) => void;
}) {
  const [setup, setSetup] = useState<"openrouter" | "typesafe" | "llm">(
    "openrouter",
  );
  const config =
    setup === "openrouter"
      ? "OPENROUTER_API_KEY=your-key-here"
      : setup === "typesafe"
        ? "TYPESAFE_API_KEY=your-key-here"
        : "JEV_SCOUT_LLM_BASE_URL=http://127.0.0.1:11434/v1\nJEV_SCOUT_LLM_MODEL=your-local-model\nJEV_SCOUT_LLM_API_KEY=local";
  async function copy() {
    try {
      await navigator.clipboard.writeText(config);
      onToast("Configuration example copied.");
    } catch {
      onToast(
        "Clipboard access is unavailable. Select and copy the configuration text.",
        true,
      );
    }
  }
  return (
    <div className="page-content settings-page">
      <div className="page-heading">
        <div>
          <span className="eyebrow">YOUR SPACE, YOUR TOOLS</span>
          <h1>Made to work your way.</h1>
          <p>
            Connect an analysis method and keep your research workspace close to
            home.
          </p>
        </div>
        <button className="button secondary" onClick={onRefresh}>
          <RefreshCw size={16} />
          Refresh settings
        </button>
      </div>
      <div className="settings-grid">
        <section className="surface settings-connections">
          <div className="surface-heading">
            <div>
              <h2>Analysis configuration</h2>
              <p>
                Keys stay on the server. Run an analysis to validate provider
                access.
              </p>
            </div>
            <Settings2 size={21} />
          </div>
          <Connection
            name="Keyword baseline"
            description="Deterministic matching against your explicit keywords."
            connected
            configuredLabel="Ready"
            model="Runs locally · no key needed"
            icon={<Search size={20} />}
          />
          <Connection
            name="Jev"
            description="Typed semantic decisions with source-linked evidence."
            connected={!!settings?.jev_configured}
            model={
              settings?.jev_configured
                ? `${settings.model} · ${settings.jev_provider || "TypeSafe"}`
                : "OpenRouter or TypeSafe API key required"
            }
            icon={<Sparkles size={20} />}
          />
          <Connection
            name="Local / compatible LLM"
            description="Structured analysis with an OpenAI-compatible model."
            connected={!!settings?.llm_configured}
            model={
              settings?.llm_configured
                ? `${settings.llm_model} · ${settings.llm_provider}`
                : "Model endpoint required"
            }
            icon={<Layers3 size={20} />}
          />
          <div className="default-method">
            <span>Default analysis method</span>
            <ModeBadge mode={settings?.default_mode || "baseline"} />
          </div>
        </section>
        <section className="surface privacy-card">
          <div className="privacy-icon">
            <LockKeyhole size={24} />
          </div>
          <h2>A workspace you own.</h2>
          <p>
            Your library, notes, feedback, and job history are stored in a local
            database.
          </p>
          <div>
            <ShieldCheck size={16} />
            <span>Local, single-user workspace</span>
          </div>
          <div>
            <Database size={16} />
            <span>Persistent SQLite storage</span>
          </div>
          <div>
            <FileText size={16} />
            <span>Export in open formats</span>
          </div>
          <p className="privacy-footnote">
            Cloud analysis sends selected paper metadata and your research
            profile to the configured provider. Local models use your configured
            endpoint.
          </p>
        </section>
        <section className="surface setup-panel">
          <div className="surface-heading">
            <div>
              <h2>Connect your preferred model</h2>
              <p>
                Update the project’s .env file, restart the server, then refresh
                these settings.
              </p>
            </div>
          </div>
          <div className="segmented compact">
            {[
              { id: "openrouter", label: "Jev via OpenRouter" },
              { id: "typesafe", label: "TypeSafe" },
              { id: "llm", label: "Compatible LLM" },
            ].map((provider) => (
              <button
                key={provider.id}
                className={setup === provider.id ? "active" : ""}
                onClick={() => setSetup(provider.id as typeof setup)}
              >
                {provider.label}
              </button>
            ))}
          </div>
          <div className="config-snippet">
            <pre>{config}</pre>
            <button
              className="icon-button"
              onClick={() => void copy()}
              aria-label="Copy configuration example"
            >
              <Clipboard size={16} />
            </button>
          </div>
          <p className="form-note">
            Replace example values on your own machine. Never commit .env files
            or paste API keys into notes or screenshots.
          </p>
          {setup === "openrouter" && (
            <a
              href="https://openrouter.ai/settings/keys"
              target="_blank"
              rel="noreferrer"
              className="text-button"
            >
              Manage OpenRouter keys <ArrowUpRight size={14} />
            </a>
          )}
          {setup === "typesafe" && (
            <a
              href="https://docs.typesafe.ai/introduction/quickstart"
              target="_blank"
              rel="noreferrer"
              className="text-button"
            >
              TypeSafe setup guide <ArrowUpRight size={14} />
            </a>
          )}
        </section>
        <section className="surface collection-panel">
          <div className="surface-heading">
            <div>
              <h2>Start with a public collection</h2>
              <p>Explore real papers before building your own library.</p>
            </div>
            <BookOpen size={22} />
          </div>
          <p>
            Load attributed public-paper abstracts and three research profiles.
            This collection uses the explicitly labeled keyword baseline; it is
            not a live Jev evaluation.
          </p>
          <button
            className="button secondary"
            disabled={demoBusy}
            onClick={onLoadDemo}
          >
            {demoBusy ? (
              <Spinner label="Loading collection" />
            ) : (
              <>
                Load public collection <ChevronRight size={16} />
              </>
            )}
          </button>
          <p className="form-note">
            Safe to load again. Existing notes and profile edits are preserved.
          </p>
        </section>
      </div>
      <div className="workspace-version">
        <span>Jev Scout {settings?.version || "0.1.0"}</span>
        <a href="/licenses/NOTICE.txt" target="_blank" rel="noreferrer">
          Third-party licenses
        </a>
        <span>
          {settings?.database_path_display || "Local workspace"}{" "}
          <Check size={12} />
        </span>
      </div>
    </div>
  );
}
function Connection({
  name,
  description,
  connected,
  configuredLabel = "Configured",
  model,
  icon,
}: {
  name: string;
  description: string;
  connected: boolean;
  configuredLabel?: string;
  model: string;
  icon: React.ReactNode;
}) {
  return (
    <div className="connection">
      <span className="connection-icon">{icon}</span>
      <div>
        <h3>{name}</h3>
        <p>{description}</p>
        <small>{model}</small>
      </div>
      <span className={`connection-status ${connected ? "connected" : ""}`}>
        <span />
        {connected ? configuredLabel : "Not configured"}
      </span>
    </div>
  );
}
