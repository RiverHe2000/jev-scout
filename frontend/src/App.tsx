import { useCallback, useEffect, useRef, useState } from "react";
import {
  Activity,
  ArrowDownToLine,
  ArrowRight,
  ArrowUpRight,
  BookOpen,
  Bookmark,
  BookmarkCheck,
  Check,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  CircleHelp,
  FileText,
  Inbox,
  Menu,
  Plus,
  Search,
  Settings2,
  SlidersHorizontal,
  Sparkles,
  Target,
  X,
} from "lucide-react";
import { api, formatDate, messageOf, post } from "./api";
import {
  Empty,
  ErrorPanel,
  Logo,
  Modal,
  ModeBadge,
  RouteBadge,
  Spinner,
  Toast,
} from "./components";
import { AnalyzeModal, ExportModal, ImportModal, ProfileModal } from "./forms";
import {
  stored,
  storeValue,
  useDebounce,
  useMediaQuery,
  useOverlayFocus,
  useResource,
} from "./hooks";
import PaperDetail from "./PaperDetail";
import {
  InsightsPage,
  JobsList,
  ProfilesPage,
  SettingsPage,
  type Benchmark,
} from "./pages";
import type {
  Activity as ActivityItem,
  Job,
  Page,
  PaperEntry,
  PaperResponse,
  Profile,
  ReadingState,
  Route,
  Settings,
  Stats,
} from "./types";

const navItems = [
  { id: "inbox", label: "Paper inbox", icon: Inbox },
  { id: "saved", label: "Reading list", icon: Bookmark },
  { id: "profiles", label: "Research profiles", icon: Target },
  { id: "insights", label: "Activity & insights", icon: Activity },
] as const;
const emptyCounts = {
  all: 0,
  read: 0,
  skim: 0,
  review: 0,
  later: 0,
  saved: 0,
  unread: 0,
};
export default function App() {
  const [page, setPage] = useState<Page>("inbox");
  const [profiles, setProfiles] = useState<Profile[]>([]);
  const [settings, setSettings] = useState<Settings | null>(null);
  const [profileId, setProfileId] = useState(() => stored("jev-scout-profile"));
  const [bootLoading, setBootLoading] = useState(true);
  const [bootError, setBootError] = useState("");
  const [refresh, setRefresh] = useState(0);
  const [jobTick, setJobTick] = useState(0);
  const [route, setRoute] = useState<"all" | Route>("all");
  const [status, setStatus] = useState("all");
  const [sort, setSort] = useState("priority");
  const [query, setQuery] = useState("");
  const debouncedQuery = useDebounce(query);
  const [offset, setOffset] = useState(0);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [detailVisible, setDetailVisible] = useState(
    () => window.innerWidth >= 1100,
  );
  const [mobileNav, setMobileNav] = useState(false);
  const [modal, setModal] = useState<
    "import" | "analyze" | "export" | "profile" | "jobs" | null
  >(null);
  const [editProfile, setEditProfile] = useState<Profile | undefined>();
  const [analyzeIds, setAnalyzeIds] = useState<string[] | undefined>();
  const [toast, setToast] = useState<{
    message: string;
    error?: boolean;
  } | null>(null);
  const [demoBusy, setDemoBusy] = useState(false);
  const [jobBusy, setJobBusy] = useState("");
  const searchRef = useRef<HTMLInputElement>(null);
  const sidebarRef = useRef<HTMLElement>(null);
  const isCompactNavigation = useMediaQuery("(max-width: 799px)");
  useOverlayFocus(sidebarRef, mobileNav && isCompactNavigation, () =>
    setMobileNav(false),
  );
  const previousJobStatus = useRef("");
  const notify = useCallback(
    (message: string, error = false) => setToast({ message, error }),
    [],
  );
  const closeToast = useCallback(() => setToast(null), []);
  const reload = useCallback(() => setRefresh((n) => n + 1), []);
  const profile =
    profiles.find((p) => p.id === profileId && !p.archived) ||
    profiles.find((p) => !p.archived);
  const activeId = profile?.id || "";
  const pageSize = route === "read" ? profile?.daily_limit || 10 : 30;
  const jobs = useResource<{ items: Job[] }>("/jobs", jobTick);
  const activeJobs =
    jobs.data?.items.filter(
      (j) => j.status === "running" || j.status === "queued",
    ) || [];
  useEffect(() => {
    const timer = setInterval(
      () => setJobTick((n) => n + 1),
      activeJobs.length ? 1800 : 12000,
    );
    return () => clearInterval(timer);
  }, [activeJobs.length]);
  useEffect(() => {
    if (!jobs.data) return;
    const signature = jobs.data.items
      .map((j) => `${j.id}:${j.status}:${j.completed}`)
      .join("|");
    if (previousJobStatus.current && signature !== previousJobStatus.current)
      reload();
    previousJobStatus.current = signature;
  }, [jobs.data, reload]);
  const boot = useCallback(async () => {
    setBootLoading(true);
    setBootError("");
    try {
      const [profileResponse, config] = await Promise.all([
        api<{ items: Profile[] }>("/profiles?include_archived=true"),
        api<Settings>("/settings"),
      ]);
      setProfiles(profileResponse.items);
      setSettings(config);
    } catch (e) {
      setBootError(messageOf(e));
    } finally {
      setBootLoading(false);
    }
  }, []);
  useEffect(() => {
    void boot();
  }, [boot]);
  useEffect(() => {
    if (activeId) {
      storeValue("jev-scout-profile", activeId);
      setSelectedId(null);
      setRoute("all");
      setOffset(0);
    }
  }, [activeId]);
  useEffect(() => {
    setOffset(0);
  }, [route, status, debouncedQuery, sort, page, pageSize]);
  useEffect(() => {
    function shortcut(e: KeyboardEvent) {
      const target = e.target as HTMLElement;
      if (
        e.key === "/" &&
        !["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName) &&
        !target.isContentEditable &&
        !modal
      ) {
        e.preventDefault();
        setPage("inbox");
        requestAnimationFrame(() => searchRef.current?.focus());
      }
    }
    window.addEventListener("keydown", shortcut);
    return () => window.removeEventListener("keydown", shortcut);
  }, [modal]);
  const isQueue = page === "inbox" || page === "saved";
  const paperParams = new URLSearchParams({
    profile_id: activeId,
    route,
    saved: String(page === "saved"),
    status,
    q: debouncedQuery,
    sort,
    limit: String(pageSize),
    offset: String(offset),
  });
  const papers = useResource<PaperResponse>(
    activeId && isQueue ? `/papers?${paperParams}` : null,
    refresh,
  );
  const stats = useResource<Stats>(
    activeId ? `/stats?profile_id=${encodeURIComponent(activeId)}` : null,
    refresh,
  );
  const activity = useResource<{ items: ActivityItem[] }>(
    activeId && page === "insights"
      ? `/activity?profile_id=${encodeURIComponent(activeId)}`
      : null,
    refresh,
  );
  const benchmark = useResource<Benchmark>(
    page === "insights" ? "/evaluation" : null,
    refresh,
  );
  const counts = papers.data?.counts || emptyCounts;
  const entries = papers.data?.items || [];
  useEffect(() => {
    if (papers.data) {
      setSelectedId((current) =>
        current && papers.data!.items.some((p) => p.id === current)
          ? current
          : papers.data!.items[0]?.id || null,
      );
    }
  }, [papers.data]);
  function navigate(next: Page) {
    setPage(next);
    setMobileNav(false);
    setOffset(0);
    setQuery("");
    setRoute("all");
    setStatus("all");
  }
  function selectProfile(next: Profile) {
    setProfileId(next.id);
    navigate("inbox");
    notify(`Now viewing “${next.name}”.`);
  }
  async function reading(id: string, patch: Partial<ReadingState>) {
    try {
      await api(`/papers/${id}/reading`, {
        method: "PATCH",
        body: JSON.stringify({ profile_id: activeId, ...patch }),
      });
      reload();
      if ("saved" in patch)
        notify(
          patch.saved
            ? "Added to your reading list."
            : "Removed from your reading list.",
        );
      else if ("note" in patch) notify("Your note is saved.");
      else if ("feedback" in patch)
        notify(
          patch.feedback
            ? "Feedback recorded for this profile."
            : "Feedback removed.",
        );
    } catch (e) {
      notify(messageOf(e), true);
      throw e;
    }
  }
  async function loadDemo() {
    setDemoBusy(true);
    try {
      const result = await post<{
        papers: number;
        profiles: number;
        message: string;
      }>("/demo/load");
      await boot();
      reload();
      setJobTick((n) => n + 1);
      notify(result.message || "Public-paper collection is ready.");
      navigate("inbox");
    } catch (e) {
      notify(messageOf(e), true);
    } finally {
      setDemoBusy(false);
    }
  }
  function newJob(job: Job) {
    setJobTick((n) => n + 1);
    reload();
    notify(
      `${job.kind === "ingest" ? "Import" : "Analysis"} started. Follow its progress in Activity.`,
    );
  }
  async function jobAction(job: Job, action: "cancel" | "retry") {
    setJobBusy(job.id);
    try {
      await post<Job>(`/jobs/${job.id}/${action}`);
      setJobTick((n) => n + 1);
      reload();
      notify(
        action === "cancel"
          ? "Job cancellation requested."
          : "Job queued for another attempt.",
      );
    } catch (e) {
      notify(messageOf(e), true);
    } finally {
      setJobBusy("");
    }
  }
  async function archive(p: Profile) {
    try {
      await post(`/profiles/${p.id}/archive`, { archived: !p.archived });
      await boot();
      reload();
      notify(
        p.archived
          ? "Profile restored."
          : "Profile archived. You can restore it from Research profiles.",
      );
    } catch (e) {
      notify(messageOf(e), true);
    }
  }
  function openProfile(p?: Profile) {
    setEditProfile(p);
    setModal("profile");
  }
  function analyze(ids?: string[]) {
    setAnalyzeIds(ids);
    setModal("analyze");
  }
  const savedCount = stats.data?.saved || 0;
  return (
    <div className="app-shell">
      <a className="skip-link" href="#main-content">
        Skip to content
      </a>
      {mobileNav && (
        <button
          className="sidebar-backdrop"
          aria-label="Close navigation"
          onClick={() => setMobileNav(false)}
        />
      )}
      <aside
        className={`sidebar ${mobileNav ? "open" : ""}`}
        ref={sidebarRef}
        tabIndex={-1}
        role={mobileNav && isCompactNavigation ? "dialog" : undefined}
        aria-modal={mobileNav && isCompactNavigation ? true : undefined}
        aria-hidden={isCompactNavigation && !mobileNav ? true : undefined}
        inert={isCompactNavigation && !mobileNav}
        aria-label="Workspace navigation"
      >
        <a
          className="brand"
          href="#"
          onClick={(e) => {
            e.preventDefault();
            navigate("inbox");
          }}
        >
          <Logo />
          <span>
            Jev Scout<small>A little less noise.</small>
          </span>
        </a>
        <button
          className="mobile-nav-close icon-button"
          aria-label="Close navigation"
          onClick={() => setMobileNav(false)}
        >
          <X size={18} />
        </button>
        <div className="workspace-label">
          <span className="workspace-avatar">R</span>
          <span>
            Research workspace<small>Personal · local</small>
          </span>
          <LockIcon />
        </div>
        <div className="nav-label">WORKSPACE</div>
        <nav aria-label="Main navigation">
          {navItems.map((item) => (
            <button
              className={`nav-item ${page === item.id ? "active" : ""}`}
              key={item.id}
              onClick={() => navigate(item.id)}
              aria-current={page === item.id ? "page" : undefined}
            >
              <item.icon size={18} />
              <span>{item.label}</span>
              {item.id === "inbox" && !!stats.data?.papers && (
                <span className="nav-count">{stats.data.papers}</span>
              )}
              {item.id === "saved" && savedCount > 0 && (
                <span className="nav-count">{savedCount}</span>
              )}
            </button>
          ))}
        </nav>
        <div className="sidebar-bottom">
          <div className="research-note">
            <div className="note-flower">
              <Logo small />
            </div>
            <span className="eyebrow">FOLLOW THE QUESTION.</span>
            <p>
              Good research starts
              <br />
              with a little curiosity.
            </p>
            <button className="text-button" onClick={() => openProfile()}>
              Create a research profile <ArrowUpRight size={14} />
            </button>
          </div>
          <button
            className={`nav-item ${page === "settings" ? "active" : ""}`}
            onClick={() => navigate("settings")}
          >
            <Settings2 size={18} />
            <span>Settings & connections</span>
          </button>
          <div className="local-status">
            <span />
            <span>Local workspace</span>
            <small>v{settings?.version || "0.1.0"}</small>
          </div>
        </div>
      </aside>
      <div className="main-shell">
        <header className="topbar">
          <div className="breadcrumb">
            <button
              className="icon-button mobile-menu"
              aria-label="Open navigation"
              onClick={() => setMobileNav(true)}
            >
              <Menu size={20} />
            </button>
            <span>Workspace</span>
            <ChevronRight size={13} />
            <strong>
              {page === "settings"
                ? "Settings"
                : navItems.find((n) => n.id === page)?.label}
            </strong>
          </div>
          <div className="topbar-right">
            <span className="today-date">
              {new Date().toLocaleDateString("en-US", {
                weekday: "short",
                month: "short",
                day: "numeric",
              })}
            </span>
            <button
              className={`job-status-button ${activeJobs.length ? "working" : ""}`}
              onClick={() => setModal("jobs")}
              aria-label={`Background activity: ${activeJobs.length} active jobs`}
            >
              {activeJobs.length ? (
                <>
                  <span className="working-dot" />
                  {activeJobs.length} running
                </>
              ) : (
                <>
                  <Check size={13} />
                  All caught up
                </>
              )}
            </button>
            <span className="user-avatar" title="Personal research workspace">
              R
            </span>
          </div>
        </header>
        <main id="main-content">
          {bootError ? (
            <div className="page-content">
              <ErrorPanel message={bootError} retry={() => void boot()} />
            </div>
          ) : bootLoading && !profiles.length ? (
            <div className="app-loading">
              <Logo />
              <Spinner label="Opening your research workspace" />
              <p>Making a little room for your next idea.</p>
            </div>
          ) : isQueue ? (
            <div className="queue-page">
              <div className="page-heading">
                <div>
                  <span className="eyebrow">
                    {page === "saved"
                      ? "IDEAS WORTH COMING BACK TO"
                      : "A SMALLER PILE. A CLEARER PICTURE."}
                  </span>
                  <h1>
                    {page === "saved"
                      ? "The reading list, refined."
                      : "Your next good read."}
                    <span className="heading-star">✳</span>
                  </h1>
                  <p>
                    {page === "saved"
                      ? "A personal shelf of papers worth a closer look."
                      : "From a growing world of papers to the ones that move your research forward."}
                  </p>
                </div>
                <div className="heading-actions">
                  <button
                    className="button secondary"
                    disabled={!profile}
                    onClick={() => setModal("export")}
                  >
                    <ArrowDownToLine size={15} />
                    Export
                  </button>
                  <button
                    className="button primary"
                    disabled={!profile}
                    onClick={() => setModal("import")}
                  >
                    <Plus size={17} />
                    Import papers
                  </button>
                </div>
              </div>
              {!profile ? (
                <div className="onboarding surface">
                  <div className="onboarding-art">
                    <div className="orbit orbit-one" />
                    <div className="orbit orbit-two" />
                    <div className="paper-tile tile-back">
                      <FileText size={38} />
                    </div>
                    <div className="paper-tile tile-front">
                      <Logo />
                      <span />
                      <span />
                      <span />
                    </div>
                    <div className="art-spark">✳</div>
                  </div>
                  <span className="eyebrow">
                    EVERY GOOD DISCOVERY STARTS SOMEWHERE
                  </span>
                  <h2>Make room for what matters.</h2>
                  <p>
                    Tell Scout what you’re researching. Bring in a few papers,
                    follow the evidence, and build a reading list with a point
                    of view.
                  </p>
                  <div className="onboarding-actions">
                    <button
                      className="button primary"
                      onClick={() => openProfile()}
                    >
                      <Plus size={17} />
                      Create your first profile
                    </button>
                    <button
                      className="button secondary"
                      disabled={demoBusy}
                      onClick={() => void loadDemo()}
                    >
                      {demoBusy ? (
                        <Spinner label="Loading" />
                      ) : (
                        <>
                          <BookOpen size={17} />
                          Explore a public collection
                        </>
                      )}
                    </button>
                  </div>
                  <div className="onboarding-steps">
                    <span>
                      <Target size={17} />
                      Ask a research question
                    </span>
                    <ChevronRight size={15} />
                    <span>
                      <Search size={17} />
                      Inspect the evidence
                    </span>
                    <ChevronRight size={15} />
                    <span>
                      <Bookmark size={17} />
                      Keep the useful ideas
                    </span>
                  </div>
                </div>
              ) : (
                <>
                  <section
                    className="focus-card"
                    aria-label="Current research profile"
                  >
                    <div className="focus-icon">
                      <Target size={22} />
                    </div>
                    <div className="focus-content">
                      <div className="focus-overline">
                        <label htmlFor="active-profile">
                          YOUR RESEARCH LENS
                        </label>
                        <span>v{profile.version}</span>
                      </div>
                      <div className="focus-title">
                        <select
                          id="active-profile"
                          value={activeId}
                          onChange={(e) => {
                            setProfileId(e.target.value);
                            setDetailVisible(window.innerWidth >= 1100);
                          }}
                        >
                          {profiles
                            .filter((p) => !p.archived)
                            .map((p) => (
                              <option key={p.id} value={p.id}>
                                {p.name}
                              </option>
                            ))}
                        </select>
                        <ChevronDown size={16} />
                      </div>
                      <p>{profile.question}</p>
                      <div className="focus-preferences">
                        {profile.preferences.slice(0, 3).map((p) => (
                          <span key={p.id}>
                            <Check size={11} />
                            {p.label}
                          </span>
                        ))}
                      </div>
                    </div>
                    <button
                      className="button focus-edit"
                      onClick={() => openProfile(profile)}
                    >
                      <SlidersHorizontal size={15} />
                      <span>Adjust lens</span>
                    </button>
                  </section>
                  <div className="queue-summary">
                    <div>
                      <span className="summary-number">
                        {stats.data?.papers ?? counts.all}
                      </span>
                      <span>papers in your library</span>
                    </div>
                    <span className="summary-divider" />
                    <div>
                      <span className="summary-dot read" />
                      <strong>
                        {stats.data?.route_counts.read ?? counts.read}
                      </strong>
                      <span>to read first</span>
                    </div>
                    <div>
                      <span className="summary-dot review" />
                      <strong>{stats.data?.review ?? counts.review}</strong>
                      <span>need a closer look</span>
                    </div>
                    <button className="text-button" onClick={() => analyze()}>
                      <Sparkles size={14} />
                      Run analysis <ArrowUpRight size={13} />
                    </button>
                  </div>
                  <div className="queue-controls">
                    <div
                      className="route-tabs"
                      aria-label="Filter by reading priority"
                    >
                      {(
                        [
                          {
                            id: "all",
                            label:
                              page === "saved" ? "Saved papers" : "All papers",
                          },
                          { id: "read", label: "Read first" },
                          { id: "skim", label: "Skim" },
                          { id: "review", label: "Needs review" },
                          { id: "later", label: "For later" },
                        ] as const
                      ).map((item) => (
                        <button
                          className={route === item.id ? "active" : ""}
                          key={item.id}
                          onClick={() => setRoute(item.id)}
                          aria-pressed={route === item.id}
                        >
                          {item.id === "read" && <Sparkles size={13} />}
                          <span>{item.label}</span>
                          <small>
                            {item.id === "all" && page === "saved"
                              ? counts.saved
                              : counts[item.id]}
                          </small>
                        </button>
                      ))}
                    </div>
                    <div className="search-row">
                      <label className="search-field">
                        <Search size={17} />
                        <input
                          ref={searchRef}
                          value={query}
                          onChange={(e) => setQuery(e.target.value)}
                          placeholder="Search your papers…"
                          aria-label="Search papers"
                        />
                        {query ? (
                          <button
                            aria-label="Clear search"
                            onClick={() => setQuery("")}
                          >
                            <X size={14} />
                          </button>
                        ) : (
                          <kbd>/</kbd>
                        )}
                      </label>
                      <label className="filter-select">
                        <span className="sr-only">Reading status filter</span>
                        <select
                          value={status}
                          onChange={(e) => setStatus(e.target.value)}
                        >
                          <option value="all">All reading states</option>
                          <option value="unread">Unread</option>
                          <option value="reading">Currently reading</option>
                          <option value="done">Finished</option>
                        </select>
                        <ChevronDown size={13} />
                      </label>
                      <label className="sort-select">
                        <span>Sort:</span>
                        <select
                          aria-label="Sort papers"
                          value={sort}
                          onChange={(e) => setSort(e.target.value)}
                        >
                          <option value="priority">Research fit</option>
                          <option value="newest">Newest first</option>
                        </select>
                        <ChevronDown size={13} />
                      </label>
                    </div>
                  </div>
                  <div
                    className={`paper-workspace ${selectedId && detailVisible ? "has-detail" : ""}`}
                  >
                    <section className="paper-list" aria-label="Paper results">
                      <div className="results-heading">
                        <span>
                          {papers.loading ? (
                            <Spinner label="Updating queue" />
                          ) : (
                            <>
                              {papers.data?.total || 0} paper
                              {papers.data?.total === 1 ? "" : "s"}
                              {route === "all" ? " in this view" : ""}
                            </>
                          )}
                        </span>
                        <span>
                          {page === "saved"
                            ? "YOUR PERSONAL SHELF"
                            : route === "read"
                              ? `DAILY FOCUS · UP TO ${pageSize} PAPERS`
                              : "CURATED AROUND YOUR QUESTION"}
                        </span>
                      </div>
                      {papers.error ? (
                        <ErrorPanel message={papers.error} retry={reload} />
                      ) : papers.loading && !papers.data ? (
                        <div className="paper-skeletons">
                          {[1, 2, 3].map((i) => (
                            <div key={i}>
                              <div className="skeleton short" />
                              <div className="skeleton long" />
                              <div className="skeleton" />
                            </div>
                          ))}
                        </div>
                      ) : entries.length ? (
                        entries.map((paper, index) => (
                          <PaperCard
                            key={paper.id}
                            paper={paper}
                            selected={paper.id === selectedId && detailVisible}
                            index={offset + index}
                            onSelect={() => {
                              setSelectedId(paper.id);
                              setDetailVisible(true);
                            }}
                            onSave={() =>
                              void reading(paper.id, {
                                saved: !paper.reading.saved,
                              }).catch(() => {})
                            }
                          />
                        ))
                      ) : (
                        <Empty
                          icon={
                            page === "saved" ? (
                              <Bookmark size={28} />
                            ) : query ? (
                              <Search size={28} />
                            ) : (
                              <BookOpen size={28} />
                            )
                          }
                          title={
                            query
                              ? "No papers match just yet"
                              : page === "saved"
                                ? "Keep an idea for later"
                                : counts.all
                                  ? "A little breathing room"
                                  : "Your next discovery starts here"
                          }
                          action={
                            query || route !== "all" || status !== "all" ? (
                              <button
                                className="button secondary"
                                onClick={() => {
                                  setQuery("");
                                  setRoute("all");
                                  setStatus("all");
                                }}
                              >
                                Clear filters
                              </button>
                            ) : page === "saved" ? (
                              <button
                                className="button secondary"
                                onClick={() => navigate("inbox")}
                              >
                                Browse the inbox <ArrowRight size={15} />
                              </button>
                            ) : (
                              <button
                                className="button primary"
                                onClick={() => setModal("import")}
                              >
                                <Plus size={15} />
                                Import from arXiv
                              </button>
                            )
                          }
                        >
                          {query
                            ? "Try a title, author, keyword, or a broader search."
                            : page === "saved"
                              ? "Save a paper from your inbox and it will be waiting on this shelf."
                              : counts.all
                                ? "There are no papers in this reading queue. Try another view."
                                : "Search arXiv or paste paper IDs. Scout will organize them around your research question."}
                        </Empty>
                      )}
                      {!!papers.data?.total && (
                        <div className="pagination">
                          <span>
                            Showing {offset + 1}–
                            {Math.min(offset + pageSize, papers.data.total)} of{" "}
                            {papers.data.total}
                          </span>
                          <div>
                            <button
                              className="icon-button"
                              aria-label="Previous page"
                              disabled={offset === 0 || papers.loading}
                              onClick={() =>
                                setOffset(Math.max(0, offset - pageSize))
                              }
                            >
                              <ChevronLeft size={17} />
                            </button>
                            <button
                              className="icon-button"
                              aria-label="Next page"
                              disabled={
                                offset + pageSize >= papers.data.total ||
                                papers.loading
                              }
                              onClick={() => setOffset(offset + pageSize)}
                            >
                              <ChevronRight size={17} />
                            </button>
                          </div>
                        </div>
                      )}
                    </section>
                    {selectedId && detailVisible && (
                      <>
                        <button
                          className="detail-backdrop"
                          aria-label="Close paper details"
                          onClick={() => setDetailVisible(false)}
                        />
                        <PaperDetail
                          paperId={selectedId}
                          profile={profile}
                          refresh={refresh}
                          onReading={reading}
                          onAnalyze={(id) => analyze([id])}
                          onClose={() => setDetailVisible(false)}
                        />
                      </>
                    )}
                  </div>
                  <footer className="queue-footer">
                    <span>
                      <CircleHelp size={13} />A useful signal, never the final
                      word. Read the evidence and make it yours.
                    </span>
                    <button
                      className="text-button"
                      onClick={() => navigate("settings")}
                    >
                      How analysis works <ArrowUpRight size={12} />
                    </button>
                  </footer>
                </>
              )}
            </div>
          ) : page === "profiles" ? (
            <ProfilesPage
              profiles={profiles}
              activeId={activeId}
              onSelect={selectProfile}
              onEdit={openProfile}
              onCreate={() => openProfile()}
              onArchive={(p) => void archive(p)}
            />
          ) : page === "insights" ? (
            <InsightsPage
              stats={stats.data}
              jobs={jobs.data?.items || []}
              activity={activity.data?.items || []}
              benchmark={benchmark.data}
              onJobAction={(job, action) => void jobAction(job, action)}
              jobBusy={jobBusy}
              loading={stats.loading}
              error={
                stats.error || jobs.error || activity.error || benchmark.error
              }
              onRetry={() => {
                reload();
                setJobTick((n) => n + 1);
              }}
            />
          ) : (
            <SettingsPage
              settings={settings}
              onRefresh={() => {
                void boot();
                reload();
                notify("Refreshing workspace settings.");
              }}
              onLoadDemo={() => void loadDemo()}
              demoBusy={demoBusy}
              onToast={notify}
            />
          )}
        </main>
      </div>
      {modal === "profile" && (
        <ProfileModal
          key={editProfile?.id || "new"}
          profile={editProfile}
          onClose={() => {
            setModal(null);
            void boot();
          }}
          onSave={(saved) => {
            setProfiles((current) => [
              ...current.filter((p) => p.id !== saved.id),
              saved,
            ]);
            setProfileId(saved.id);
            reload();
            notify(
              editProfile
                ? "Research profile updated. Re-run analysis to refresh earlier decisions."
                : "Your new research profile is ready.",
            );
          }}
        />
      )}
      {modal === "import" && profile && (
        <ImportModal
          profile={profile}
          settings={settings}
          onClose={() => setModal(null)}
          onJob={newJob}
        />
      )}{" "}
      {modal === "analyze" && profile && (
        <AnalyzeModal
          profile={profile}
          settings={settings}
          paperIds={analyzeIds}
          onClose={() => setModal(null)}
          onJob={newJob}
        />
      )}{" "}
      {modal === "export" && profile && (
        <ExportModal
          profile={profile}
          onClose={() => setModal(null)}
          onError={(m) => notify(m, true)}
        />
      )}{" "}
      {modal === "jobs" && (
        <Modal
          title="A little work in the background."
          subtitle="Imports and analyses are saved across restarts. You can cancel or retry a job here."
          onClose={() => setModal(null)}
          wide
        >
          <div className="modal-body">
            {jobs.error ? (
              <ErrorPanel
                message={jobs.error}
                retry={() => setJobTick((n) => n + 1)}
              />
            ) : (
              <JobsList
                jobs={jobs.data?.items || []}
                onAction={(job, action) => void jobAction(job, action)}
                busy={jobBusy}
              />
            )}
            <div className="modal-footer">
              <button
                className="text-button"
                onClick={() => {
                  setModal(null);
                  navigate("insights");
                }}
              >
                Open activity & insights <ArrowRight size={15} />
              </button>
              <button
                className="button secondary"
                onClick={() => setModal(null)}
              >
                Done
              </button>
            </div>
          </div>
        </Modal>
      )}
      {toast && (
        <Toast
          message={toast.message}
          error={toast.error}
          onClose={closeToast}
        />
      )}
    </div>
  );
}
function LockIcon() {
  return <span className="workspace-dot" />;
}
function PaperCard({
  paper,
  selected,
  index,
  onSelect,
  onSave,
}: {
  paper: PaperEntry;
  selected: boolean;
  index: number;
  onSelect: () => void;
  onSave: () => void;
}) {
  return (
    <article
      className={`paper-card ${selected ? "selected" : ""} ${paper.reading.status === "done" ? "finished" : ""}`}
    >
      <button
        className="paper-select"
        onClick={onSelect}
        aria-label={`Open ${paper.title}`}
        aria-pressed={selected}
      >
        <div className="paper-topline">
          <span className="paper-index">
            {String(index + 1).padStart(2, "0")}
          </span>
          {paper.decision ? (
            <RouteBadge
              route={paper.decision.stale ? "review" : paper.decision.route}
            />
          ) : (
            <span className="muted-tag">Awaiting analysis</span>
          )}
          {paper.decision?.stale && (
            <span className="stale-tag">Needs refresh</span>
          )}
          <span className="paper-date">{formatDate(paper.published)}</span>
        </div>
        <h2>{paper.title}</h2>
        <p className="paper-authors">
          {paper.authors.slice(0, 3).join(", ")}
          {paper.authors.length > 3 ? " et al." : ""}
        </p>
        <p className="paper-excerpt">{paper.abstract}</p>
        <div className="paper-bottom">
          <div className="paper-tags">
            {paper.categories.slice(0, 2).map((category) => (
              <span key={category}>{category}</span>
            ))}
            {paper.reading.status !== "unread" && (
              <span className="reading-tag">
                {paper.reading.status === "done" ? (
                  <Check size={10} />
                ) : (
                  <BookOpen size={10} />
                )}{" "}
                {paper.reading.status === "done" ? "Read" : "Reading"}
              </span>
            )}
          </div>
          {paper.decision && <ModeBadge mode={paper.decision.mode} />}
          <ArrowUpRight className="paper-open-arrow" size={15} />
        </div>
      </button>
      <button
        className={`paper-save icon-button ${paper.reading.saved ? "saved" : ""}`}
        aria-label={
          paper.reading.saved ? `Unsave ${paper.title}` : `Save ${paper.title}`
        }
        aria-pressed={paper.reading.saved}
        onClick={onSave}
      >
        {paper.reading.saved ? (
          <BookmarkCheck size={17} />
        ) : (
          <Bookmark size={17} />
        )}
      </button>
    </article>
  );
}
