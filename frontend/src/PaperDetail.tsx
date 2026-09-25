import { useEffect, useRef, useState } from "react";
import {
  ArrowUpRight,
  Bookmark,
  BookmarkCheck,
  Check,
  ChevronDown,
  CircleHelp,
  Clock3,
  FileText,
  History,
  MessageSquare,
  RefreshCw,
  Save,
  ThumbsDown,
  ThumbsUp,
  X,
} from "lucide-react";
import {
  abstractSegments,
  formatDate,
  formatNumber,
  safeExternal,
} from "./api";
import {
  Empty,
  ErrorPanel,
  ModeBadge,
  RouteBadge,
  Spinner,
} from "./components";
import {
  stored,
  storeValue,
  useMediaQuery,
  useOverlayFocus,
  useResource,
} from "./hooks";
import type { PaperDetail as Detail, Profile, ReadingState } from "./types";
import PreferenceSignals from "./PreferenceSignals";

export default function PaperDetail({
  paperId,
  profile,
  refresh,
  onReading,
  onAnalyze,
  onClose,
}: {
  paperId: string;
  profile: Profile;
  refresh: number;
  onReading: (paperId: string, patch: Partial<ReadingState>) => Promise<void>;
  onAnalyze: (id: string) => void;
  onClose: () => void;
}) {
  const paneRef = useRef<HTMLElement>(null);
  const isOverlay = useMediaQuery("(max-width: 1099px)");
  useOverlayFocus(paneRef, isOverlay, onClose);
  const paneAccessibility = {
    ref: paneRef,
    role: isOverlay ? "dialog" : undefined,
    "aria-modal": isOverlay ? true : undefined,
    "aria-label": "Paper details",
    tabIndex: -1,
  } as const;
  const [retry, setRetry] = useState(0);
  const resource = useResource<Detail>(
    `/papers/${paperId}?profile_id=${encodeURIComponent(profile.id)}`,
    refresh + retry,
  );
  const paper = resource.data?.id === paperId ? resource.data : null;
  const [tab, setTab] = useState<"evidence" | "notes" | "history">("evidence");
  const [note, setNote] = useState("");
  const [savedNote, setSavedNote] = useState("");
  const [saving, setSaving] = useState(false);
  const [action, setAction] = useState("");
  const draftKey = `jev-scout-note:${profile.id}:${paperId}`;
  useEffect(() => {
    setTab("evidence");
    setNote("");
    setSavedNote("");
  }, [paperId, profile.id]);
  useEffect(() => {
    if (paper) {
      setSavedNote(paper.reading.note);
      const draft = stored(draftKey, "__none__");
      setNote(draft === "__none__" ? paper.reading.note : draft);
    }
  }, [paper?.reading.note, draftKey, paperId]);
  async function update(patch: Partial<ReadingState>, key: string) {
    setAction(key);
    try {
      await onReading(paperId, patch);
    } catch {
      /* Parent displays the request error. */
    } finally {
      setAction("");
    }
  }
  async function saveNote() {
    setSaving(true);
    try {
      await onReading(paperId, { note });
      setSavedNote(note);
      try {
        localStorage.removeItem(draftKey);
      } catch {
        /* Optional local draft cache. */
      }
    } catch {
      /* Keep the draft intact after a failed save. */
    } finally {
      setSaving(false);
    }
  }
  if (resource.error)
    return (
      <aside className="detail-pane" {...paneAccessibility}>
        <button
          className="detail-close icon-button"
          onClick={onClose}
          aria-label="Close paper details"
        >
          <X size={18} />
        </button>
        <ErrorPanel
          message={resource.error}
          retry={() => setRetry((n) => n + 1)}
        />
      </aside>
    );
  if (!paper)
    return (
      <aside className="detail-pane detail-loading" {...paneAccessibility}>
        <Spinner label="Opening paper" />
        <div className="skeleton long" />
        <div className="skeleton" />
        <div className="skeleton long" />
      </aside>
    );
  const decision = paper.decision;
  const segments = abstractSegments(
    paper.abstract,
    decision?.sentences || [],
    decision?.evidence_ids || [],
  );
  const hasEvidence = segments.some((s) => s.highlight);
  return (
    <aside className="detail-pane" {...paneAccessibility}>
      <div className="detail-topline">
        <span className="eyebrow">A CLOSER LOOK</span>
        <button
          className="icon-button"
          onClick={onClose}
          aria-label="Close paper details"
        >
          <X size={18} />
        </button>
      </div>
      <div className="detail-content">
        <div className="detail-badges">
          {decision ? (
            <RouteBadge route={decision.stale ? "review" : decision.route} />
          ) : (
            <span className="muted-tag">Not analyzed yet</span>
          )}
          <span className="version-tag">v{paper.version}</span>
          {paper.reading.status === "done" && (
            <span className="read-tag">
              <Check size={12} /> Read
            </span>
          )}
        </div>
        <h2>{paper.title}</h2>
        <p className="detail-authors">{paper.authors.join(", ")}</p>
        <p className="detail-meta">
          {formatDate(paper.published)} <span>·</span> arXiv:{paper.arxiv_id}
        </p>
        <div className="detail-links">
          <a
            className="button secondary small"
            href={safeExternal(paper.source_url)}
            target="_blank"
            rel="noreferrer"
          >
            View on arXiv <ArrowUpRight size={14} />
          </a>
          <a
            className="text-button"
            href={safeExternal(paper.pdf_url)}
            target="_blank"
            rel="noreferrer"
          >
            <FileText size={15} /> PDF <ArrowUpRight size={12} />
          </a>
          <button
            className={`icon-button bookmark-button ${paper.reading.saved ? "saved" : ""}`}
            disabled={action === "save"}
            aria-label={
              paper.reading.saved
                ? "Remove from reading list"
                : "Save to reading list"
            }
            aria-pressed={paper.reading.saved}
            onClick={() => void update({ saved: !paper.reading.saved }, "save")}
          >
            {paper.reading.saved ? (
              <BookmarkCheck size={19} />
            ) : (
              <Bookmark size={19} />
            )}
          </button>
        </div>
        <div
          className="detail-tabs"
          role="tablist"
          onKeyDown={(event) => {
            if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key))
              return;
            event.preventDefault();
            const tabs = ["evidence", "notes", "history"] as const;
            const index = tabs.indexOf(tab);
            const next =
              event.key === "Home"
                ? 0
                : event.key === "End"
                  ? 2
                  : (index + (event.key === "ArrowRight" ? 1 : -1) + 3) % 3;
            setTab(tabs[next]);
            document.getElementById(`tab-${tabs[next]}`)?.focus();
          }}
          aria-label="Paper information"
        >
          {[
            { id: "evidence", label: "Evidence", icon: FileText },
            { id: "notes", label: "Your notes", icon: MessageSquare },
            { id: "history", label: "History", icon: History },
          ].map((item) => (
            <button
              key={item.id}
              role="tab"
              id={`tab-${item.id}`}
              aria-selected={tab === item.id}
              tabIndex={tab === item.id ? 0 : -1}
              aria-controls={`panel-${item.id}`}
              className={tab === item.id ? "active" : ""}
              onClick={() => setTab(item.id as typeof tab)}
            >
              <item.icon size={14} />
              {item.label}
              {item.id === "notes" && paper.reading.note && (
                <span className="tab-dot" />
              )}
            </button>
          ))}
        </div>
        {tab === "evidence" && (
          <div
            role="tabpanel"
            id="panel-evidence"
            aria-labelledby="tab-evidence"
            className="tab-panel"
          >
            {decision ? (
              <>
                <div
                  className={`decision-summary ${decision.stale ? "stale" : ""}`}
                >
                  <div className="section-title">
                    <span>
                      {decision.stale
                        ? "This decision needs a refresh"
                        : "Why it landed here"}
                    </span>
                    <CircleHelp size={14} />
                  </div>
                  <p>{decision.reason}</p>
                  <div className="decision-footer">
                    <ModeBadge mode={decision.mode} />
                    {decision.mode === "jev" &&
                      decision.confidence !== null && (
                        <span
                          className="confidence"
                          title="Uncalibrated model confidence for the relatedness question. Evidence selection is assessed separately; this is not measured accuracy."
                        >
                          {Math.round(decision.confidence * 100)}% relatedness
                          confidence <CircleHelp size={11} />
                        </span>
                      )}
                  </div>
                  {decision.stale && (
                    <button
                      className="text-button"
                      onClick={() => onAnalyze(paper.id)}
                    >
                      Analyze with current profile <RefreshCw size={13} />
                    </button>
                  )}
                </div>
                <PreferenceSignals decision={decision} />
              </>
            ) : (
              <div className="decision-summary">
                <strong>No decision for this profile yet.</strong>
                <p>
                  Run an analysis to see how this abstract relates to your
                  current question.
                </p>
                <button
                  className="text-button"
                  onClick={() => onAnalyze(paper.id)}
                >
                  Analyze paper <RefreshCw size={14} />
                </button>
              </div>
            )}
            <section className="abstract-section">
              <div className="section-title">
                <h3>From the abstract</h3>
                {hasEvidence && (
                  <span className="highlight-key">
                    <span /> Selected evidence
                  </span>
                )}
              </div>
              <p className="abstract-text">
                {segments.map((segment, i) =>
                  segment.highlight ? (
                    <mark
                      key={i}
                      title={`Original abstract sentence ${segment.id}`}
                    >
                      {segment.text}
                    </mark>
                  ) : (
                    <span key={i}>{segment.text}</span>
                  ),
                )}
              </p>
              <p className="source-note">
                {paper.source === "bundled"
                  ? "Attributed public-paper collection"
                  : "Retrieved from arXiv"}{" "}
                · Original abstract, unchanged.
                {!hasEvidence && " No supporting sentence selected."}
              </p>
            </section>
            {!!decision?.unknowns.length && (
              <div className="unknowns">
                <div className="section-title">
                  <CircleHelp size={15} />
                  <span>What the abstract leaves open</span>
                </div>
                <ul>
                  {decision.unknowns.map((text, i) => (
                    <li key={i}>{text}</li>
                  ))}
                </ul>
              </div>
            )}
            {!!decision?.warnings.length && (
              <details className="decision-warnings">
                <summary>
                  Method notes <ChevronDown size={14} />
                </summary>
                <ul>
                  {decision.warnings.map((text, i) => (
                    <li key={i}>{text}</li>
                  ))}
                </ul>
              </details>
            )}
            <div className="paper-categories">
              {paper.categories.map((category) => (
                <span key={category}>{category}</span>
              ))}
            </div>
          </div>
        )}
        {tab === "notes" && (
          <div
            role="tabpanel"
            id="panel-notes"
            aria-labelledby="tab-notes"
            className="tab-panel"
          >
            <div className="notes-intro">
              <h3>Your working notes</h3>
              <p>
                Capture why this paper matters, questions to revisit, or ideas
                for your next experiment.
              </p>
            </div>
            <label className="field">
              <span className="sr-only">Paper note</span>
              <textarea
                rows={11}
                maxLength={20000}
                value={note}
                onChange={(e) => {
                  setNote(e.target.value);
                  storeValue(draftKey, e.target.value);
                }}
                placeholder="A useful idea, an open question, a connection…"
              />
            </label>
            <div className="note-actions">
              <span>
                {note === savedNote
                  ? "All notes saved"
                  : "Unsaved draft · kept in this browser"}
              </span>
              <button
                className="button primary small"
                disabled={saving || note === savedNote}
                onClick={() => void saveNote()}
              >
                {saving ? (
                  <Spinner label="Saving" />
                ) : (
                  <>
                    <Save size={14} /> Save note
                  </>
                )}
              </button>
            </div>
          </div>
        )}
        {tab === "history" && (
          <div
            role="tabpanel"
            id="panel-history"
            aria-labelledby="tab-history"
            className="tab-panel"
          >
            <div className="notes-intro">
              <h3>A traceable decision</h3>
              <p>Paper and profile versions stay attached to each analysis.</p>
            </div>
            {paper.decisions.length ? (
              paper.decisions.map((run, i) => (
                <div className="history-item" key={run.id}>
                  <div className="history-dot" />
                  <div>
                    <div className="history-top">
                      <ModeBadge mode={run.mode} />
                      {i === 0 && <span className="tiny">LATEST</span>}
                    </div>
                    <p>
                      {run.model} · Paper v{run.paper_version} · Profile v
                      {run.profile_version}
                    </p>
                    <div className="history-metrics">
                      <span>{formatDate(run.created_at)}</span>
                      <span>{formatNumber(run.latency_ms)} ms</span>
                      <span>
                        {run.cost_usd === null
                          ? "Cost unavailable"
                          : `$${run.cost_usd.toFixed(6)}`}
                      </span>
                    </div>
                    <div className="history-metrics">
                      <span>{run.input_tokens} input tokens</span>
                      <span>{run.output_tokens} output tokens</span>
                      {run.cache_hit && <span>Cache hit</span>}
                    </div>
                    <details>
                      <summary>Decision details</summary>
                      <p>{run.reason}</p>
                      <p>Question schema: {run.question_version}</p>
                      <p>
                        Relevance score: {run.relevance.toFixed(2)} / 2 · Rank:{" "}
                        {run.rank_score.toFixed(3)}
                      </p>
                      <p>
                        {run.stale
                          ? "Outdated for current profile or paper."
                          : "Matches the recorded profile and paper versions."}
                      </p>
                    </details>
                  </div>
                </div>
              ))
            ) : (
              <Empty icon={<History size={25} />} title="A fresh start">
                No analysis has been recorded for this profile.
              </Empty>
            )}
            <div className="version-summary">
              <strong>
                {paper.versions.length} paper version
                {paper.versions.length === 1 ? "" : "s"} recorded
              </strong>
              <span>Source metadata updated {formatDate(paper.updated)}</span>
            </div>
          </div>
        )}
        <div className="reading-controls">
          <label className="reading-status-label">
            Reading progress
            <select
              aria-label="Reading progress"
              value={paper.reading.status}
              disabled={action === "status"}
              onChange={(e) =>
                void update(
                  { status: e.target.value as ReadingState["status"] },
                  "status",
                )
              }
            >
              <option value="unread">Unread</option>
              <option value="reading">Currently reading</option>
              <option value="done">Finished reading</option>
            </select>
          </label>
          <div className="feedback-heading">
            <span>Useful for this research question?</span>
            {paper.reading.feedback && (
              <button
                className="text-button"
                disabled={action === "feedback"}
                onClick={() => void update({ feedback: null }, "feedback")}
              >
                Undo
              </button>
            )}
          </div>
          <div className="feedback-options">
            {[
              { id: "useful", label: "Useful", icon: ThumbsUp },
              { id: "not_now", label: "Not now", icon: Clock3 },
              { id: "irrelevant", label: "Unrelated", icon: ThumbsDown },
            ].map((item) => (
              <button
                key={item.id}
                className={paper.reading.feedback === item.id ? "active" : ""}
                aria-pressed={paper.reading.feedback === item.id}
                disabled={action === "feedback"}
                onClick={() =>
                  void update(
                    {
                      feedback:
                        paper.reading.feedback === item.id
                          ? null
                          : (item.id as ReadingState["feedback"]),
                    },
                    "feedback",
                  )
                }
              >
                <item.icon size={14} />
                {item.label}
              </button>
            ))}
          </div>
          <p className="feedback-note">
            Feedback is saved to this profile. Your preferences stay yours to
            edit.
          </p>
        </div>
      </div>
    </aside>
  );
}
