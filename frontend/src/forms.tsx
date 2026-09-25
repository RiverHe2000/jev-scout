import { useState, type FormEvent } from "react";
import {
  ArrowDownToLine,
  ArrowRight,
  BookOpen,
  Check,
  CircleAlert,
  FileText,
  Plus,
  Search,
  SlidersHorizontal,
  Sparkles,
  Trash2,
} from "lucide-react";
import { api, ApiError, messageOf, post } from "./api";
import { ErrorPanel, Modal, Spinner } from "./components";
import type { Job, Mode, Profile, ProfileInput, Settings } from "./types";

export function ModeSelector({
  value,
  onChange,
  settings,
}: {
  value: Mode;
  onChange: (mode: Mode) => void;
  settings: Settings | null;
}) {
  return (
    <fieldset className="mode-options">
      <legend>Analysis method</legend>
      {(
        [
          {
            id: "baseline",
            name: "Keyword baseline",
            description: "Local keyword matching. No API calls.",
            available: true,
            icon: SlidersHorizontal,
          },
          {
            id: "jev",
            name: "Jev semantic decisions",
            description: settings?.jev_configured
              ? `Via ${settings.jev_provider === "openrouter" ? "OpenRouter" : "TypeSafe"}. Uses your configured API key.`
              : "Configure a Jev key via OpenRouter or TypeSafe to enable.",
            available: !!settings?.jev_configured,
            icon: Sparkles,
          },
          {
            id: "llm",
            name: "Local / compatible LLM",
            description: settings?.llm_configured
              ? `${settings.llm_model} · ${settings.llm_provider}`
              : "Configure an OpenAI-compatible model endpoint to enable.",
            available: !!settings?.llm_configured,
            icon: BookOpen,
          },
        ] as const
      ).map((option) => (
        <label
          key={option.id}
          className={`${value === option.id ? "selected" : ""} ${!option.available ? "unavailable" : ""}`}
        >
          <input
            type="radio"
            name="mode"
            value={option.id}
            checked={value === option.id}
            disabled={!option.available}
            onChange={() => onChange(option.id)}
          />
          <option.icon size={19} />
          <span>
            <strong>{option.name}</strong>
            <small>{option.description}</small>
          </span>
          {value === option.id && <Check size={17} />}
        </label>
      ))}
    </fieldset>
  );
}
export function ImportModal({
  profile,
  settings,
  onClose,
  onJob,
}: {
  profile: Profile;
  settings: Settings | null;
  onClose: () => void;
  onJob: (job: Job) => void;
}) {
  const [tab, setTab] = useState<"query" | "ids">("query");
  const [value, setValue] = useState("");
  const [limit, setLimit] = useState(20);
  const [mode, setMode] = useState<Mode>(settings?.default_mode || "baseline");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      const input =
        tab === "query"
          ? { query: value.trim().replace(/\s+/g, " ") }
          : { ids: value.split(/[\s,;]+/).filter(Boolean) };
      const job = await post<Job>("/ingest", {
        profile_id: profile.id,
        ...input,
        max_results: limit,
        mode,
      });
      onJob(job);
      onClose();
    } catch (e) {
      setError(messageOf(e));
    } finally {
      setBusy(false);
    }
  }
  return (
    <Modal
      title="Bring your next idea in."
      subtitle="Import public arXiv metadata and abstracts, then sort them for your research question."
      onClose={onClose}
    >
      <form onSubmit={submit} className="modal-body">
        <div className="segmented">
          <button
            type="button"
            className={tab === "query" ? "active" : ""}
            onClick={() => {
              setTab("query");
              setValue("");
            }}
          >
            <Search size={16} /> Search arXiv
          </button>
          <button
            type="button"
            className={tab === "ids" ? "active" : ""}
            onClick={() => {
              setTab("ids");
              setValue("");
            }}
          >
            <FileText size={16} /> Paste paper IDs
          </button>
        </div>
        <label className="field">
          {tab === "query"
            ? "arXiv search query"
            : "arXiv IDs or arxiv.org links"}
          <textarea
            autoFocus
            required
            value={value}
            onChange={(e) => setValue(e.target.value)}
            rows={3}
            placeholder={
              tab === "query"
                ? 'all:"agent memory" AND cat:cs.AI'
                : "2303.11366\nhttps://arxiv.org/abs/2308.08155"
            }
          />
          <span>
            {tab === "query"
              ? 'Use arXiv syntax: all:"phrase", ti:keyword, or cat:cs.AI.'
              : "Separate papers with spaces, commas, or new lines."}
          </span>
        </label>
        <div className="two-fields">
          <label className="field">
            Research profile
            <div className="readonly-field">
              <BookOpen size={16} />
              {profile.name}
            </div>
          </label>
          <label className="field">
            Maximum papers
            <input
              type="number"
              min={1}
              max={100}
              value={limit}
              onChange={(e) => setLimit(Number(e.target.value))}
              required
            />
          </label>
        </div>
        <ModeSelector value={mode} onChange={setMode} settings={settings} />
        <p className="form-note">
          Imports run in the background. Existing papers are deduplicated, and
          updated versions keep their history.
        </p>
        {error && <ErrorPanel message={error} />}
        <div className="modal-footer">
          <button type="button" className="button secondary" onClick={onClose}>
            Cancel
          </button>
          <button disabled={busy || !value.trim()} className="button primary">
            {busy ? (
              <Spinner label="Starting" />
            ) : (
              <>
                Import & analyze <ArrowRight size={16} />
              </>
            )}
          </button>
        </div>
      </form>
    </Modal>
  );
}
export function AnalyzeModal({
  profile,
  settings,
  paperIds,
  onClose,
  onJob,
}: {
  profile: Profile;
  settings: Settings | null;
  paperIds?: string[];
  onClose: () => void;
  onJob: (job: Job) => void;
}) {
  const [mode, setMode] = useState<Mode>(settings?.default_mode || "baseline");
  const [force, setForce] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    try {
      onJob(
        await post<Job>("/evaluate", {
          profile_id: profile.id,
          mode,
          paper_ids: paperIds,
          force,
        }),
      );
      onClose();
    } catch (e) {
      setError(messageOf(e));
      setBusy(false);
    }
  }
  return (
    <Modal
      title={paperIds ? "Take another look." : "Refresh your perspective."}
      subtitle={`Analyze ${paperIds ? "this paper" : "your library"} against “${profile.name}”, version ${profile.version}.`}
      onClose={onClose}
    >
      <form className="modal-body" onSubmit={submit}>
        <ModeSelector value={mode} onChange={setMode} settings={settings} />
        <label className="checkbox-field">
          <input
            type="checkbox"
            checked={force}
            onChange={(e) => setForce(e.target.checked)}
          />
          <span>
            <strong>Re-run existing decisions</strong>
            <small>
              By default, matching results are reused. A forced Jev run may
              incur API charges.
            </small>
          </span>
        </label>
        <p className="form-note">
          Each decision records the paper version, profile version, method, and
          evidence. Feedback does not silently change your research question.
        </p>
        {error && <ErrorPanel message={error} />}
        <div className="modal-footer">
          <button type="button" className="button secondary" onClick={onClose}>
            Cancel
          </button>
          <button className="button primary" disabled={busy}>
            {busy ? (
              <Spinner label="Starting" />
            ) : (
              <>
                Start analysis <Sparkles size={16} />
              </>
            )}
          </button>
        </div>
      </form>
    </Modal>
  );
}
export function ExportModal({
  profile,
  onClose,
  onError,
}: {
  profile: Profile;
  onClose: () => void;
  onError: (message: string) => void;
}) {
  const [format, setFormat] = useState("bibtex");
  const [scope, setScope] = useState("saved");
  const [busy, setBusy] = useState(false);
  async function download() {
    setBusy(true);
    try {
      const params = new URLSearchParams({
        profile_id: profile.id,
        format,
        scope,
      });
      const response = await fetch(`/api/export?${params}`);
      if (!response.ok) {
        const body = await response.json().catch(() => ({}));
        throw new Error(body.detail || "Export could not be created.");
      }
      const blob = await response.blob();
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = `jev-scout-${scope}.${format === "bibtex" ? "bib" : format === "markdown" ? "md" : "json"}`;
      document.body.appendChild(link);
      link.click();
      link.remove();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
      onClose();
    } catch (e) {
      onError(messageOf(e));
    } finally {
      setBusy(false);
    }
  }
  return (
    <Modal
      title="Take your reading list along."
      subtitle="Your papers, notes, and references — ready for the next step."
      onClose={onClose}
    >
      <div className="modal-body">
        <label className="field">
          Collection
          <select value={scope} onChange={(e) => setScope(e.target.value)}>
            <option value="saved">Saved papers in {profile.name}</option>
            <option value="all">All papers in {profile.name}</option>
          </select>
        </label>
        <fieldset className="export-options">
          <legend>File format</legend>
          {[
            {
              id: "bibtex",
              name: "BibTeX",
              description: "References for Zotero or LaTeX",
            },
            {
              id: "markdown",
              name: "Markdown",
              description: "A portable reading list and notes",
            },
            {
              id: "json",
              name: "JSON",
              description: "Structured data for your workflow",
            },
          ].map((item) => (
            <label
              key={item.id}
              className={format === item.id ? "selected" : ""}
            >
              <input
                type="radio"
                name="format"
                checked={format === item.id}
                onChange={() => setFormat(item.id)}
              />
              <FileText size={20} />
              <span>
                <strong>{item.name}</strong>
                <small>{item.description}</small>
              </span>
            </label>
          ))}
        </fieldset>
        <div className="modal-footer">
          <button className="button secondary" onClick={onClose}>
            Cancel
          </button>
          <button className="button primary" disabled={busy} onClick={download}>
            {busy ? (
              <Spinner label="Exporting" />
            ) : (
              <>
                Download file <ArrowDownToLine size={16} />
              </>
            )}
          </button>
        </div>
      </div>
    </Modal>
  );
}

const blank: ProfileInput = {
  name: "",
  question: "",
  keywords: [],
  preferences: [],
  exclusions: "",
  seed_papers: [],
  daily_limit: 10,
  confidence_threshold: 0.65,
};
export function ProfileModal({
  profile,
  onClose,
  onSave,
}: {
  profile?: Profile;
  onClose: () => void;
  onSave: (profile: Profile) => void;
}) {
  const [form, setForm] = useState<ProfileInput>(
    profile
      ? {
          name: profile.name,
          question: profile.question,
          keywords: profile.keywords,
          preferences: profile.preferences,
          exclusions: profile.exclusions,
          seed_papers: profile.seed_papers,
          daily_limit: profile.daily_limit,
          confidence_threshold: profile.confidence_threshold,
        }
      : blank,
  );
  const [keywords, setKeywords] = useState(profile?.keywords.join(", ") || "");
  const [seeds, setSeeds] = useState(profile?.seed_papers.join("\n") || "");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [conflict, setConflict] = useState(false);
  function patch<K extends keyof ProfileInput>(key: K, value: ProfileInput[K]) {
    setForm((f) => ({ ...f, [key]: value }));
  }
  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      const body = {
        ...form,
        keywords: keywords
          .split(",")
          .map((k) => k.trim())
          .filter(Boolean),
        seed_papers: seeds
          .split(/[\n,]+/)
          .map((s) => s.trim())
          .filter(Boolean),
        ...(profile ? { expected_version: profile.version } : {}),
      };
      const saved = await api<Profile>(
        profile ? `/profiles/${profile.id}` : "/profiles",
        { method: profile ? "PUT" : "POST", body: JSON.stringify(body) },
      );
      onSave(saved);
      onClose();
    } catch (e) {
      setError(messageOf(e));
      setConflict(e instanceof ApiError && e.status === 409);
    } finally {
      setBusy(false);
    }
  }
  return (
    <Modal
      wide
      title={
        profile ? "Give your research more focus." : "What are you working on?"
      }
      subtitle="A good question makes a better reading list. Be specific about what would change your work."
      onClose={onClose}
    >
      <form className="modal-body profile-form" onSubmit={submit}>
        <label className="field">
          Profile name
          <input
            autoFocus
            required
            maxLength={100}
            value={form.name}
            onChange={(e) => patch("name", e.target.value)}
            placeholder="e.g. Reliable agent memory"
          />
        </label>
        <label className="field">
          Your research question
          <textarea
            required
            minLength={10}
            maxLength={3000}
            rows={3}
            value={form.question}
            onChange={(e) => patch("question", e.target.value)}
            placeholder="Which memory strategies help language agents stay reliable over long tasks?"
          />
          <span>
            Describe the research problem you want a paper to help solve.
          </span>
        </label>
        <label className="field">
          Keywords for the lexical baseline
          <input
            value={keywords}
            onChange={(e) => setKeywords(e.target.value)}
            placeholder="agent memory, long-horizon, retrieval"
          />
          <span>
            Comma-separated terms. The local baseline uses these explicit terms.
          </span>
        </label>
        <div className="section-label">
          <div>
            <strong>What would make a paper useful?</strong>
            <span>Up to three single-question preferences.</span>
          </div>
          <button
            type="button"
            className="text-button"
            disabled={form.preferences.length >= 3}
            onClick={() =>
              patch("preferences", [
                ...form.preferences,
                { id: crypto.randomUUID(), label: "", question: "", weight: 1 },
              ])
            }
          >
            <Plus size={15} /> Add preference
          </button>
        </div>
        {form.preferences.map((preference, index) => (
          <div className="preference-form" key={preference.id}>
            <div className="preference-heading">
              <span>Preference {index + 1}</span>
              <button
                type="button"
                className="icon-button small"
                aria-label={`Remove preference ${index + 1}`}
                onClick={() =>
                  patch(
                    "preferences",
                    form.preferences.filter((_, i) => i !== index),
                  )
                }
              >
                <Trash2 size={15} />
              </button>
            </div>
            <label className="field">
              Short label
              <input
                required
                maxLength={100}
                value={preference.label}
                onChange={(e) =>
                  patch(
                    "preferences",
                    form.preferences.map((p, i) =>
                      i === index ? { ...p, label: e.target.value } : p,
                    ),
                  )
                }
                placeholder="Failure analysis"
              />
            </label>
            <label className="field">
              Question answered from the abstract
              <input
                required
                minLength={5}
                maxLength={500}
                value={preference.question}
                onChange={(e) =>
                  patch(
                    "preferences",
                    form.preferences.map((p, i) =>
                      i === index ? { ...p, question: e.target.value } : p,
                    ),
                  )
                }
                placeholder="Does the abstract explicitly discuss failure cases?"
              />
            </label>
            <label className="range-field">
              <span>
                Preference weight{" "}
                <strong>{preference.weight.toFixed(1)}×</strong>
              </span>
              <input
                type="range"
                min={0}
                max={2}
                step={0.1}
                value={preference.weight}
                onChange={(e) =>
                  patch(
                    "preferences",
                    form.preferences.map((p, i) =>
                      i === index
                        ? { ...p, weight: Number(e.target.value) }
                        : p,
                    ),
                  )
                }
              />
              <span className="range-labels">
                <small>No weight</small>
                <small>High priority</small>
              </span>
            </label>
          </div>
        ))}
        <label className="field">
          What should wait? <span className="optional">Optional</span>
          <textarea
            rows={2}
            maxLength={1500}
            value={form.exclusions}
            onChange={(e) => patch("exclusions", e.target.value)}
            placeholder="e.g. Work focused only on increasing model size"
          />
        </label>
        <details className="advanced-form">
          <summary>Reading limits & advanced settings</summary>
          <div className="two-fields">
            <label className="field">
              Daily focus size
              <input
                type="number"
                min={1}
                max={50}
                required
                value={form.daily_limit}
                onChange={(e) => patch("daily_limit", Number(e.target.value))}
              />
              <span>
                Maximum papers per Read first page. You can always browse the
                full queue.
              </span>
            </label>
            <label className="field">
              Review threshold
              <input
                type="number"
                min={0}
                max={1}
                step={0.05}
                required
                value={form.confidence_threshold}
                onChange={(e) =>
                  patch("confidence_threshold", Number(e.target.value))
                }
              />
            </label>
          </div>
          <p className="form-note">
            The review threshold is an uncalibrated operating setting, not a
            guarantee of correctness.
          </p>
          <label className="field">
            Seed paper IDs <span className="optional">Optional context</span>
            <textarea
              rows={2}
              value={seeds}
              onChange={(e) => setSeeds(e.target.value)}
              placeholder="One arXiv ID per line"
            />
          </label>
        </details>
        {error && (
          <ErrorPanel
            message={
              conflict
                ? `${error} Your edits are still here. Close this form and reopen the profile to load its latest version before applying them.`
                : error
            }
          />
        )}
        <div className="form-note inline">
          <CircleAlert size={15} />
          <span>
            Changing a profile makes earlier decisions stale. Re-run analysis to
            update the queue.
          </span>
        </div>
        <div className="modal-footer">
          <button type="button" className="button secondary" onClick={onClose}>
            Cancel
          </button>
          <button disabled={busy || conflict} className="button primary">
            {busy ? (
              <Spinner label="Saving" />
            ) : profile ? (
              "Save research profile"
            ) : (
              "Create research profile"
            )}
          </button>
        </div>
      </form>
    </Modal>
  );
}
