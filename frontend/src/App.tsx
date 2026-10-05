import { useEffect, useMemo, useRef, useState } from "react";
import type { CSSProperties, ReactNode } from "react";
import { ApiError, confirmedLabelsCsv, createHttpAdapter, priorityOf, type CategoryStats, type EmailDetail as StoredEmail, type EmailSummary, type InboxAdapter, type LabelPatch, type ModelStatus, type SyncStatus, receivedText } from "./api";
import { categories, priorities, type Category, type CategoryFilter, type HumanLabel, type Priority } from "./data";
import { buildTreemap, categoryColors, type TreemapNode } from "./treemap";

type Page = "inbox" | "review" | "models";
type QuickFilter = "all" | "review" | "high";

function Icon({ name }: { name: "mail" | "review" | "model" | "plus" | "search" | "download" | "sync" | "close" | "lock" }) {
  const paths: Record<typeof name, ReactNode> = {
    mail: <><path d="M4 4.8h16v14.4H4z" /><path d="M4 14h4l1.5 2h5L16 14h4" /></>,
    review: <><circle cx="11" cy="11" r="7" /><path d="m16.2 16.2 4.3 4.3M11 7.5v4l2.5 1.5" /></>,
    model: <><path d="M12 3.5 19 7v10l-7 3.5L5 17V7z" /><path d="m5.2 7.1 6.8 3.6 6.8-3.6M12 10.7v9.5" /></>,
    plus: <path d="M12 5v14M5 12h14" />,
    search: <><circle cx="10.8" cy="10.8" r="6.8" /><path d="m16 16 4.5 4.5" /></>,
    download: <><path d="M12 3.5v11M8 10.5l4 4 4-4M5 17.5v3h14v-3" /></>,
    sync: <><path d="M20 7v5h-5M4 17v-5h5" /><path d="M5.5 9a7 7 0 0 1 12-2L20 12M4 12l2.5 5a7 7 0 0 0 12-2" /></>,
    close: <path d="m6 6 12 12M18 6 6 18" />,
    lock: <><rect x="5" y="10" width="14" height="10" rx="2" /><path d="M8 10V7a4 4 0 0 1 8 0v3M12 14v2" /></>,
  };
  return <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{paths[name]}</svg>;
}

function categoryOf(email: EmailSummary): CategoryFilter {
  return email.humanLabel?.category ?? email.prediction?.category ?? "Unclassified";
}

const httpAdapter = createHttpAdapter(import.meta.env.VITE_API_BASE_URL);
type Draft = { category: Category | ""; priority: Priority | "" };
const confidenceText = (value: number) => `${value.toLocaleString(undefined, { maximumFractionDigits: 1 })}%`;
function categoryFailure(code: "model_unavailable" | "inference_failed" | null | undefined): string {
  return code === "model_unavailable" ? "Category model unavailable. Activate a local model, restart, and sync again to retry." :
    code === "inference_failed" ? "Category prediction failed. This message and its priority are available; sync again to retry." : "";
}
function syncFailure(code: string | null): string {
  switch (code) {
    case "sync_unavailable": return "Configure IMAP in the backend environment to enable sync.";
    case "sync_in_progress": return "A sync is already running. Its progress appears here.";
    case "imap_auth_failed": return "Mailbox login failed. Check the backend credentials and retry.";
    case "imap_uidvalidity_changed": return "Mailbox identifiers changed. Follow the database recovery instructions before retrying.";
    case "imap_message_skipped": return "Some messages could not be imported. Saved messages are available; retry is safe.";
    default: return "Sync did not finish. Check the connection and try again. Saved messages are retained.";
  }
}

function TreemapBranch({ node, onSelect, selected, depth = 0 }: { node: TreemapNode; onSelect: (category: CategoryFilter) => void; selected: CategoryFilter | "All"; depth?: number }) {
  if ("stat" in node) {
    const { category, count, percentage } = node.stat;
    const style = { "--tile-tone": categoryColors[category] } as CSSProperties;
    return (
      <button className="map-tile" style={style} type="button" aria-pressed={selected === category} aria-label={`${category}, ${count} messages, ${percentage}% of all messages. Filter inbox.`} onClick={() => onSelect(category)}>
        <span className="map-label">{category}</span>
        <span className="map-count">{count} <small>{percentage}%</small></span>
      </button>
    );
  }
  const direction = depth % 2 === 0 ? "split-row" : "split-column";
  return (
    <div className={`map-split ${direction}`}>
      <div className="map-half" style={{ flexGrow: node.leftWeight }}><TreemapBranch node={node.left} onSelect={onSelect} selected={selected} depth={depth + 1} /></div>
      <div className="map-half" style={{ flexGrow: node.rightWeight }}><TreemapBranch node={node.right} onSelect={onSelect} selected={selected} depth={depth + 1} /></div>
    </div>
  );
}

function App({ adapter = httpAdapter }: { adapter?: InboxAdapter }) {
  const [emails, setEmails] = useState<EmailSummary[]>([]);
  const [matchedTotal, setMatchedTotal] = useState(0);
  const [stats, setStats] = useState<CategoryStats | null>(null);
  const [loadingStats, setLoadingStats] = useState(true);
  const [statsError, setStatsError] = useState("");
  const [counts, setCounts] = useState<{ review: number; labeled: number } | null>(null);
  const [countsError, setCountsError] = useState("");
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState("");
  const [page, setPage] = useState<Page>("inbox");
  const [quickFilter, setQuickFilter] = useState<QuickFilter>("all");
  const [categoryFilter, setCategoryFilter] = useState<CategoryFilter>("All");
  const [priorityFilter, setPriorityFilter] = useState<Priority | "All">("All");
  const [search, setSearch] = useState("");
  const [offset, setOffset] = useState(0);
  const [refresh, setRefresh] = useState(0);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [detail, setDetail] = useState<StoredEmail | null>(null);
  const [loadingDetail, setLoadingDetail] = useState(false);
  const [detailError, setDetailError] = useState("");
  const [drafts, setDrafts] = useState<Record<string, Draft>>({});
  const [toast, setToast] = useState("");
  const [syncing, setSyncing] = useState(false);
  const [syncStatus, setSyncStatus] = useState<SyncStatus | null>(null);
  const [modelStatus, setModelStatus] = useState<ModelStatus | null>(null);
  const [modelError, setModelError] = useState("");
  const [syncCheck, setSyncCheck] = useState(0);
  const [syncMode, setSyncMode] = useState<"recent" | "unread">("recent");
  const [syncError, setSyncError] = useState("");
  const [syncRequestError, setSyncRequestError] = useState("");
  const [dialogOpen, setDialogOpen] = useState(false);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState("");
  const [exporting, setExporting] = useState(false);
  const [mobileDetail, setMobileDetail] = useState(false);
  const dialogRef = useRef<HTMLDialogElement>(null);
  const toastTimer = useRef<number | undefined>(undefined);
  const lastSyncState = useRef<string | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    setModelStatus(null);
    setModelError("");
    adapter.getModelStatus(controller.signal).then((status) => {
      if (!controller.signal.aborted) setModelStatus(status);
    }).catch(() => {
      if (!controller.signal.aborted) setModelError("Model status could not be loaded. Stored messages remain available.");
    });
    return () => controller.abort();
  }, [adapter, refresh]);

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setLoadError("");
    adapter.listEmails({ q: search, category: categoryFilter === "All" ? undefined : categoryFilter,
      priority: priorityFilter === "All" ? undefined : priorityFilter, needsReview: quickFilter === "review", limit: 50, offset,
    }, controller.signal).then((result) => {
      if (controller.signal.aborted) return;
      if (!result.items.length && offset > 0 && result.total > 0) {
        setOffset(Math.floor((result.total - 1) / 50) * 50);
        return;
      }
      setEmails(result.items);
      setMatchedTotal(result.total);
      setSelectedId((id) => result.items.some((email) => email.id === id) ? id : result.items[0]?.id ?? null);
    }).catch(() => {
      if (!controller.signal.aborted) setLoadError("Messages could not be loaded. Check that the local backend is running and retry.");
    }).finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [adapter, categoryFilter, priorityFilter, quickFilter, search, offset, refresh]);

  useEffect(() => {
    const controller = new AbortController();
    setLoadingStats(true);
    setStatsError("");
    adapter.getCategoryStats(controller.signal).then((result) => {
      if (!controller.signal.aborted) setStats(result);
    }).catch(() => {
      if (!controller.signal.aborted) setStatsError("Category counts could not be refreshed. Retry to load current totals.");
    }).finally(() => { if (!controller.signal.aborted) setLoadingStats(false); });
    setCounts(null);
    setCountsError("");
    Promise.all([adapter.listEmails({ needsReview: true, limit: 1 }, controller.signal), adapter.listEmails({ hasHumanLabel: true, limit: 1 }, controller.signal)]).then(([review, labeled]) => {
      if (!controller.signal.aborted) setCounts({ review: review.total, labeled: labeled.total });
    }).catch(() => { if (!controller.signal.aborted) setCountsError("Review and confirmed-label counts are unavailable. Retry to refresh them."); });
    return () => controller.abort();
  }, [adapter, refresh]);

  useEffect(() => {
    const controller = new AbortController();
    setDetail(null);
    setDetailError("");
    setLoadingDetail(selectedId !== null);
    if (selectedId !== null) adapter.getEmail(selectedId, controller.signal).then((email) => {
      if (!controller.signal.aborted) setDetail(email);
    }).catch(() => {
      if (!controller.signal.aborted) setDetailError("This message could not be loaded. Retry to open it.");
    }).finally(() => { if (!controller.signal.aborted) setLoadingDetail(false); });
    return () => controller.abort();
  }, [adapter, selectedId, refresh]);

  useEffect(() => {
    const controller = new AbortController();
    let timer: number | undefined;
    async function check() {
      try {
        const status = await adapter.getSyncStatus(controller.signal);
        if (controller.signal.aborted) return;
        const finished = lastSyncState.current === "running" && status.state !== "running";
        lastSyncState.current = status.state;
        setSyncStatus(status);
        setSyncError("");
        if (finished) {
          setSyncRequestError("");
          setRefresh((value) => value + 1);
        }
        if (status.state === "running" || syncing) timer = window.setTimeout(check, 1000);
      } catch {
        if (!controller.signal.aborted) {
          setSyncStatus(null);
          setSyncError("Sync status could not be loaded. Check the local backend and retry the status check.");
        }
      }
    }
    void check();
    return () => { controller.abort(); window.clearTimeout(timer); };
  }, [adapter, syncCheck, syncing]);

  useEffect(() => {
    const dialog = dialogRef.current;
    if (!dialog) return;
    if (dialogOpen && !dialog.open) dialog.showModal();
    if (!dialogOpen && dialog.open) dialog.close();
  }, [dialogOpen]);
  useEffect(() => () => window.clearTimeout(toastTimer.current), []);

  const tree = useMemo(() => buildTreemap(stats?.categories ?? []), [stats]);
  const selectedEmail = detail?.id === selectedId ? detail : null;
  const label = selectedEmail?.humanLabel ?? null;
  const draft: Draft = selectedId && drafts[selectedId] ? drafts[selectedId] : { category: label?.category ?? "", priority: label?.priority ?? "" };
  const allReview = counts?.review ?? "—";
  const confirmedCount = counts?.labeled ?? null;
  const globalTotal = !loadingStats && !statsError ? stats?.total ?? null : null;
  const syncRunning = syncing || syncStatus?.state === "running";
  const syncMessage = !syncStatus ? "Checking local sync status…" : syncStatus.demo ?
    "Demo data · sync is a no-op; no mailbox is contacted." : syncStatus.state === "running" ?
    `Syncing ${syncStatus.processed} of ${syncStatus.total} messages…` : !syncStatus.available ?
    "IMAP is not configured. Stored messages remain available." : syncStatus.state === "idle" ?
    "Ready to sync recent or unread mail." :
    `${syncStatus.state === "partial" ? "Partial sync" : syncStatus.state === "failed" ? "Sync failed" : "Last sync"}${syncStatus.completedAt ? ` · ${receivedText(syncStatus.completedAt)}` : ""} · ${syncStatus.imported} new · ${syncStatus.processed} processed · ${syncStatus.skipped} skipped`;
  const outcomeError = syncStatus?.errorCode ? syncFailure(syncStatus.errorCode) : "";

  function notify(message: string) {
    setToast(message);
    window.clearTimeout(toastTimer.current);
    toastTimer.current = window.setTimeout(() => setToast(""), 2800);
  }
  function refreshInbox() { setRefresh((value) => value + 1); }
  function setFilter(next: QuickFilter) {
    setQuickFilter(next);
    if (next === "high") setPriorityFilter("High");
    else if (quickFilter === "high") setPriorityFilter("All");
    setOffset(0);
    setPage(next === "review" ? "review" : "inbox");
    setMobileDetail(false);
  }
  function selectCategory(category: CategoryFilter) {
    setCategoryFilter(category);
    setPriorityFilter("All");
    setQuickFilter("all");
    setOffset(0);
    setPage("inbox");
    setMobileDetail(false);
    requestAnimationFrame(() => document.getElementById("messages-title")?.scrollIntoView?.({ behavior: "smooth", block: "start" }));
  }
  function editDraft(field: keyof Draft, value: Category | Priority | "") {
    if (!selectedId) return;
    setDrafts((current) => ({ ...current, [selectedId]: { ...draft, [field]: value } }));
  }
  const hasChanges = Boolean((draft.category && draft.category !== label?.category) || (draft.priority && draft.priority !== label?.priority));
  async function saveLabels() {
    if (!selectedEmail || !hasChanges || saving) return;
    const id = selectedEmail.id;
    const patch: LabelPatch = { source: "manual" };
    if (draft.category && draft.category !== label?.category) patch.category = draft.category;
    if (draft.priority && draft.priority !== label?.priority) patch.priority = draft.priority;
    if ((patch.category && (label?.category || (selectedEmail.prediction?.category && patch.category !== selectedEmail.prediction.category))) ||
        (patch.priority && (label?.priority || (selectedEmail.prediction?.priority && patch.priority !== selectedEmail.prediction.priority)))) patch.source = "correction";
    setSaving(true);
    setSaveError("");
    try {
      const saved = await adapter.saveLabel(id, patch);
      setDetail((current) => current?.id === id ? { ...current, humanLabel: saved } : current);
      setDrafts((current) => { const next = { ...current }; delete next[id]; return next; });
      notify("Your labels are saved on this device.");
      refreshInbox();
    } catch {
      setSaveError("Labels could not be saved. Your changes are still here—try again.");
    } finally { setSaving(false); }
  }
  async function syncInbox() {
    if (syncRunning || !syncStatus?.available) return;
    setSyncing(true);
    setSyncError("");
    setSyncRequestError("");
    setSyncCheck((value) => value + 1);
    try {
      const result = await adapter.sync(syncMode);
      setSyncStatus(result);
      notify(result.demo ? "Demo sync complete; no mailbox was contacted." : result.state === "partial" ? "Sync finished with partial results. Saved messages are available." : "Local inbox is up to date.");
    } catch (error) {
      setSyncRequestError(error instanceof ApiError ? syncFailure(error.code) : "The sync request could not be confirmed. Check the latest status before retrying. Saved messages are retained.");
    } finally {
      setSyncing(false);
      setSyncCheck((value) => value + 1);
      refreshInbox();
    }
  }
  async function exportLabels() {
    if (exporting || syncRunning) return;
    setExporting(true);
    try {
      const { csv, count } = await confirmedLabelsCsv(adapter);
      const url = URL.createObjectURL(new Blob([csv], { type: "text/csv;charset=utf-8" }));
      const link = document.createElement("a");
      link.href = url;
      link.download = "meiruzo-confirmed-labels.csv";
      document.body.append(link);
      link.click();
      link.remove();
      window.setTimeout(() => URL.revokeObjectURL(url), 0);
      notify(`Exported ${count} confirmed ${count === 1 ? "label" : "labels"}.`);
    } catch { notify("Labels could not be exported. No incomplete file was downloaded; try again."); }
    finally { setExporting(false); }
  }
  function clearFilters() {
    setPage("inbox"); setCategoryFilter("All"); setPriorityFilter("All"); setQuickFilter("all"); setSearch(""); setOffset(0);
  }
  function editSelection(email: EmailSummary) { setSelectedId(email.id); setMobileDetail(true); }
  const pageTitle = page === "models" ? "Model lab" : page === "review" ? "Needs review" : "Smart inbox";
  const totalUnclassified = stats?.categories.find((stat) => stat.category === "Unclassified")?.count ?? 0;

  return (
    <div className="app-shell">
      <aside className="sidebar" aria-label="Main navigation">
        <a className="brand" href="#" onClick={(event) => { event.preventDefault(); setPage("inbox"); }} aria-label="Meiruzo home">
          <span className="brand-mark"><Icon name="mail" /></span><span className="brand-name">meiruzo</span>
        </a>
        <p className="workspace-label">Personal inbox</p>
        <nav className="nav" aria-label="Workspace">
          <NavButton icon="mail" label="Smart inbox" current={page === "inbox"} onClick={() => { setPage("inbox"); setFilter("all"); }} />
          <NavButton icon="review" label="Needs review" count={allReview} current={page === "review"} onClick={() => setFilter("review")} />
          <NavButton icon="model" label="Model lab" current={page === "models"} onClick={() => setPage("models")} />
        </nav>
        <div className="side-spacer" />
        <div className="mailbox-card">
          <div className="mailbox-card-head"><span className="status-dot" /><span className="mailbox-card-copy">{syncStatus?.demo ? "Demo mailbox" : "Local mailbox"}</span></div>
          <p className="mailbox-card-copy">{syncStatus?.demo ? "Synthetic data only." : syncStatus?.available ? "Read-only IMAP sync available." : "Configure IMAP in the backend."}</p>
          <button className="mailbox-card-copy" type="button" onClick={() => setDialogOpen(true)}>Set up mailbox</button>
        </div>
      </aside>

      <div className="main-shell">
        <header className="topbar">
          <div className="breadcrumbs" aria-label="Breadcrumb"><span>Workspace</span><span aria-hidden="true">/</span><strong>{pageTitle}</strong></div>
          <div className="top-actions"><span className="demo-badge">{syncStatus?.demo ? "Demo data" : "Local data"}</span><span className="avatar" aria-label="Local workspace">L</span></div>
        </header>

        <main className="app-main">
          {countsError && <div className="state-message error-message" role="alert"><p>{countsError}</p><button type="button" className="text-button" onClick={refreshInbox}>Retry counts</button></div>}
          {page === "models" ? (
            <ModelLab status={modelStatus} error={modelError} onRetry={refreshInbox} exportDisabled={exporting || syncRunning} confirmedCount={confirmedCount} onReview={() => { setPage("inbox"); setFilter("all"); }} onExport={exportLabels} />
          ) : (
            <section className="view" aria-labelledby="inbox-title">
              <header className="page-heading">
                <div className="page-heading-copy"><p className="eyebrow">Your mailbox, in focus</p><h1 id="inbox-title">{pageTitle}</h1><p>Find the messages that matter, then teach Meiruzo what matters to you.</p></div>
                <div className="page-actions">
                  <button className="btn btn-secondary" type="button" onClick={() => setDialogOpen(true)}><Icon name="plus" />Mailbox setup</button>
                  <label className="filter-select"><span>Sync</span><select aria-label="Sync messages" value={syncMode} disabled={syncRunning} onChange={(event) => setSyncMode(event.target.value as "recent" | "unread")}><option value="recent">Recent</option><option value="unread">Unread</option></select></label><button className="btn btn-primary" type="button" onClick={syncInbox} disabled={syncRunning || !syncStatus?.available}><Icon name="sync" />{syncRunning ? "Syncing…" : syncStatus?.demo ? "Sync demo" : "Sync inbox"}</button>
                </div>
              </header>

              <div className="workspace-note" role="status">
                <span><strong>{syncStatus?.demo ? "Demo mailbox" : "Local mailbox"}</strong> <span>— {syncMessage}</span></span>
                {syncError ? <button className="text-button" type="button" onClick={() => setSyncCheck((value) => value + 1)}>Check sync status</button> : <button className="text-button" type="button" onClick={() => setDialogOpen(true)}>Set up a mailbox</button>}
              </div>

              {(modelError || modelStatus?.state === "unconfigured" || modelStatus?.state === "invalid") && <div className="workspace-note" role="status"><span>{modelError || (modelStatus?.state === "invalid" ? "The selected category model could not be loaded. Check the local artifact and restart the backend." : "No category model is active. Priority rules and manual labels remain available.")}</span><button className="text-button" type="button" onClick={() => setPage("models")}>View model status</button></div>}

              {loadError && <div className="state-message error-message" role="alert"><strong>Inbox unavailable</strong><p>{loadError}</p><button className="text-button" type="button" onClick={refreshInbox}>Retry inbox</button></div>}
              {(syncError || outcomeError || (syncRequestError && syncStatus?.state !== "running")) && <div className="state-message error-message" role="alert"><strong>Sync needs attention</strong><p>{syncError || outcomeError || syncRequestError}</p></div>}

              <div className="inline-stats" aria-label="Inbox counts">
                <div className="inline-stat"><strong>{globalTotal ?? "—"}</strong><span>messages</span></div>
                <div className="inline-stat"><strong>{allReview}</strong><span>needs review</span></div>
                <div className="inline-stat"><strong>{confirmedCount ?? "—"}</strong><span>labels confirmed</span></div>
              </div>

              <section className="panel overview-panel" aria-labelledby="overview-title">
                <div className="panel-head"><div className="panel-head-copy"><h2 id="overview-title">Inbox map</h2><p>All stored messages by category; tile area reflects count.</p></div></div>
                <div className="map-meta"><span>All stored messages · independent of inbox filters</span><span>{globalTotal ?? "—"} {globalTotal === 1 ? "message" : "messages"}{globalTotal !== null && totalUnclassified ? ` · ${totalUnclassified} unclassified` : ""}</span></div>
                <div className="map-root" id="treemap" role="group" aria-label="Category treemap for all stored messages">
                  {loadingStats ? <div className="map-empty" role="status">Loading category counts…</div> : statsError ? <div className="map-empty" role="status">{statsError || "Category counts are unavailable."}</div> : tree ? <TreemapBranch node={tree} selected={categoryFilter} onSelect={selectCategory} /> : <div className="map-empty">No messages yet. Sync to load the local inbox.</div>}
                </div>
                {statsError && <button type="button" className="text-button" onClick={refreshInbox}>Retry category counts</button>}
                <div className="category-list" aria-label="Category counts">
                  {(!loadingStats && !statsError ? stats?.categories ?? [] : []).map(({ category, count, percentage }) => <button className="category-count" key={category} type="button" aria-pressed={categoryFilter === category} onClick={() => selectCategory(category)}>
                    <span className="category-swatch" style={{ background: categoryColors[category] }} aria-hidden="true" /><span className="category-name">{category}</span><strong>{count}</strong><span className="category-percent">{percentage}%</span>
                  </button>)}
                </div>
              </section>

              <section className="inbox-section" aria-labelledby="messages-title">
                <div className="section-bar"><div className="section-title"><h2 id="messages-title">Messages</h2><p id="result-count" aria-live="polite">{loading ? "Loading messages…" : loadError ? "Results unavailable" : `${matchedTotal} ${matchedTotal === 1 ? "message" : "messages"}`}</p></div>
                  <div className="inbox-tools">
                    <label className="search-control" htmlFor="search-input"><span>Search messages</span><input id="search-input" type="search" autoComplete="off" placeholder="Sender, subject, or body" value={search} maxLength={200} onChange={(event) => { setSearch(event.target.value); setOffset(0); }} /></label>
                    <button className="btn btn-secondary" type="button" onClick={refreshInbox} disabled={loading}>Refresh inbox</button>
                    <button className="btn btn-secondary export-button" id="export-labels" type="button" onClick={exportLabels} disabled={exporting || syncRunning} aria-label="Export confirmed labels as CSV"><Icon name="download" />Export labels</button>
                  </div>
                </div>

                <div className="filter-row" role="group" aria-label="Filter messages">
                  <button className="filter-button" type="button" aria-pressed={quickFilter === "all"} onClick={() => setFilter("all")}>All messages <span className="filter-count">{globalTotal ?? "—"}</span></button>
                  <button className="filter-button" type="button" aria-pressed={quickFilter === "review"} onClick={() => setFilter("review")}>Needs review <span className="filter-count">{allReview}</span></button>
                  <button className="filter-button" type="button" aria-pressed={quickFilter === "high"} onClick={() => setFilter("high")}>High priority</button>
                  <label className="filter-select"><span>Category</span><select aria-label="Filter by category" value={categoryFilter} onChange={(event) => { setCategoryFilter(event.target.value as CategoryFilter); setOffset(0); }}><option value="All">All categories</option>{categories.map((category) => <option key={category}>{category}</option>)}<option>Unclassified</option></select></label>
                  <label className="filter-select"><span>Priority</span><select aria-label="Filter by priority" value={priorityFilter} onChange={(event) => { setPriorityFilter(event.target.value as Priority | "All"); if (quickFilter === "high") setQuickFilter("all"); setOffset(0); }}><option value="All">All priorities</option>{priorities.map((priority) => <option key={priority}>{priority}</option>)}</select></label>
                  {(categoryFilter !== "All" || priorityFilter !== "All" || quickFilter !== "all" || search) && <button type="button" className="text-button clear-filters" onClick={clearFilters}>Clear filters</button>}
                </div>

                <div className={`email-layout ${mobileDetail ? "detail-open" : ""}`}>
                  <section className="panel list-panel" aria-label="Email message list">
                    <div className="list-head"><span>{page === "review" ? "Needs review" : "Inbox"}</span><span>Model signal</span></div>
                    <div className="email-list" aria-label="Messages">
                      {loading ? <div className="empty-list" role="status">Loading messages…</div> : loadError ? <div className="empty-list">Messages are unavailable. Retry loading the inbox.</div> : !emails.length ? <div className="empty-list"><h3>{globalTotal !== 0 && (search || categoryFilter !== "All" || priorityFilter !== "All" || quickFilter !== "all") ? "No messages here" : "Your inbox is empty"}</h3><p>Sync to add messages, or clear filters to return to the inbox.</p><button type="button" onClick={clearFilters}>Clear filters</button></div> : emails.map((email) => <EmailRow key={email.id} email={email} selected={email.id === selectedId} onClick={() => editSelection(email)} />)}
                    </div>
                    <nav className="pagination" aria-label="Inbox pagination"><button type="button" className="btn btn-secondary" disabled={loading || Boolean(loadError) || offset === 0} onClick={() => { setOffset((value) => Math.max(0, value - 50)); setMobileDetail(false); }}>Previous</button><span aria-live="polite">{loadError ? "Page unavailable" : matchedTotal ? `${offset + 1}–${Math.min(offset + 50, matchedTotal)} of ${matchedTotal}` : "0 messages"}</span><button type="button" className="btn btn-secondary" disabled={loading || Boolean(loadError) || offset + 50 >= matchedTotal} onClick={() => { setOffset((value) => value + 50); setMobileDetail(false); }}>Next</button></nav>
                  </section>
                  <article className="panel detail-panel" id="email-detail" aria-label="Selected email">
                    {loadingDetail ? <div className="no-selection" role="status">Loading message…</div> : detailError ? <div className="no-selection" role="alert"><p>{detailError}</p><button type="button" onClick={refreshInbox}>Retry message</button><button type="button" onClick={() => setMobileDetail(false)}>Back to messages</button></div> : selectedEmail ? <EmailDetail email={selectedEmail} label={label} draftCategory={draft.category} draftPriority={draft.priority} saving={saving} hasChanges={hasChanges} saveError={saveError} onCategory={(value) => editDraft("category", value)} onPriority={(value) => editDraft("priority", value)} onSave={saveLabels} onBack={() => setMobileDetail(false)} /> : <div className="no-selection"><h3>No message selected</h3><p>Clear a filter or search for another message to continue reviewing your inbox.</p><button type="button" onClick={() => setMobileDetail(false)}>Back to messages</button></div>}
                  </article>
                </div>
              </section>
            </section>
          )}
        </main>
      </div>

      <dialog ref={dialogRef} id="connect-dialog" aria-labelledby="connect-title" onClose={() => setDialogOpen(false)}>
        <div className="dialog-content">
          <div className="dialog-head"><div className="dialog-head-copy"><p className="eyebrow">Mailbox setup</p><h2 id="connect-title">Connect your inbox</h2></div><button className="dialog-close" type="button" aria-label="Close mailbox setup" onClick={() => setDialogOpen(false)}><Icon name="close" /></button></div>
          <p className="dialog-body">Configure your IMAP account in the backend’s private environment file, then restart the backend and sync recent or unread messages. Sync retrieves up to 50 messages without changing your mailbox. Use the local setup instructions in the project README.</p>
          <div className="secure-note"><Icon name="lock" /><span>Passwords stay in the backend environment. This page never asks for or stores mailbox credentials.</span></div>
          <div className="dialog-actions"><button className="btn btn-primary" type="button" onClick={() => { setDialogOpen(false); setSyncCheck((value) => value + 1); }}>Check configuration</button></div>
        </div>
      </dialog>
      <div className={`toast ${toast ? "visible" : ""}`} role="status" aria-live="polite">{toast}</div>
    </div>
  );
}

function NavButton({ icon, label, count, current, onClick }: { icon: "mail" | "review" | "model"; label: string; count?: number | string; current: boolean; onClick: () => void }) {
  return <button className="nav-link" type="button" aria-label={label} aria-current={current ? "page" : undefined} onClick={onClick}><Icon name={icon} /><span>{label}</span>{count !== undefined && <span className="nav-count">{count}</span>}</button>;
}

function EmailRow({ email, selected, onClick }: { email: EmailSummary; selected: boolean; onClick: () => void }) {
  const category = categoryOf(email);
  const priority = priorityOf(email);
  const review = email.needsReview;
  return <button className={`email-row ${email.read ? "read" : "unread"}`} type="button" aria-current={selected ? "true" : "false"} aria-label={`${email.sender}, ${email.subject}, ${category}, ${priority ?? "priority unavailable"}${review ? ", needs review" : ""}`} onClick={onClick}>
    <span className="email-row-top"><span className="email-sender">{email.sender}</span><span className="email-time">{email.received}</span></span>
    <span className="email-subject">{email.subject}</span>
    <span className="email-row-bottom"><span className="tag">{category}</span>{priority && <span className={`tag priority-tag ${priority.toLowerCase()}`}>{priority}</span>}{review && <span className="review-status">Needs review</span>}{email.hasAttachments && <span className="attachment-status">Attachment</span>}{!email.read && <span className="unread-status">Unread</span>}<span className="confidence">{email.prediction?.categoryError === "inference_failed" ? "Prediction failed" : email.prediction?.confidence == null ? "No prediction" : confidenceText(email.prediction.confidence)}</span></span>
  </button>;
}

function EmailDetail({ email, label, draftCategory, draftPriority, saving, hasChanges, saveError, onCategory, onPriority, onSave, onBack }: { email: StoredEmail; label: HumanLabel | null; draftCategory: Category | ""; draftPriority: Priority | ""; saving: boolean; hasChanges: boolean; saveError: string; onCategory: (category: Category | "") => void; onPriority: (priority: Priority | "") => void; onSave: () => void; onBack: () => void }) {
  const prediction = email.prediction;
  return <>
    <div className="detail-top"><div className="detail-top-copy"><button className="back-to-list" type="button" onClick={onBack}>← Back to messages</button><h2>{email.subject}</h2><p className="detail-sender">{email.sender} &lt;{email.address}&gt;</p><span className="detail-time">{email.received} · Stored locally</span></div></div>
    <div className="detail-body"><p>{email.body}</p><div className="message-flags"><span>{email.read ? "Read" : "Unread"}</span><span>{email.hasAttachments ? "Has attachment" : "No attachments"}</span></div></div>
    <section className="prediction-block" aria-label="Original prediction"><div className="prediction-head"><strong>Original prediction</strong><span className="demo-label">{prediction ? "Stored prediction" : "Not available"}</span></div>
      {prediction ? <><div className="prediction-values"><span className="tag">{prediction.category ?? "Category unavailable"}</span><span className="tag priority-tag">{prediction.priority ?? "Priority unavailable"} priority</span><span className="tag">{prediction.confidence == null ? "Confidence unavailable" : `Category confidence ${confidenceText(prediction.confidence)}`}</span></div><p className="prediction-explanation">{prediction.reasonCategory ?? "No prediction explanation is available."}</p></> : <p className="prediction-explanation">No model prediction is available for this message yet.</p>}
      {prediction?.categoryError && <p className="prediction-explanation" role="status">{categoryFailure(prediction.categoryError)}</p>}
      {prediction?.reasonPriority && <p className="prediction-explanation">{prediction.reasonPriority}</p>}
      {prediction?.category && <p className="prediction-explanation">Model: {prediction.modelVersion ?? "Version unavailable"}{prediction.predictedAt ? ` · ${receivedText(prediction.predictedAt)}` : ""}. {prediction.reviewThreshold === null ? "All unconfirmed category predictions need review." : prediction.reviewThreshold !== undefined ? `Review cutoff: ${confidenceText(prediction.reviewThreshold)}.` : ""}</p>}
    </section>
    <section className="edit-block" aria-labelledby="edit-labels-title"><div className="edit-heading"><strong id="edit-labels-title">Your confirmed labels</strong><span>{label ? "Human label · saved on this device" : "Separate from prediction"}</span></div>
      <div className="edit-fields"><div className="field"><label htmlFor="edit-category">Category</label><select id="edit-category" value={draftCategory} disabled={saving} onChange={(event) => onCategory(event.target.value as Category | "")}><option value="" disabled={Boolean(label?.category)}>Not labeled</option>{categories.map((category) => <option key={category}>{category}</option>)}</select></div><div className="field"><label htmlFor="edit-priority">Priority</label><select id="edit-priority" value={draftPriority} disabled={saving} onChange={(event) => onPriority(event.target.value as Priority | "")}><option value="" disabled={Boolean(label?.priority)}>Not labeled</option>{priorities.map((priority) => <option key={priority}>{priority}</option>)}</select></div></div>
      {saveError && <p className="save-error" role="alert">{saveError}</p>}
      <div className="edit-actions"><p className="edit-note">Confirm or change either label. Original predictions remain available for comparison.</p><button className="btn btn-primary save-button" type="button" onClick={onSave} disabled={saving || !hasChanges}>{saving ? "Saving…" : label ? "Update labels" : "Confirm labels"}</button></div>
    </section>
  </>;
}

function ModelLab({ status, error, onRetry, confirmedCount, exportDisabled, onReview, onExport }: { status: ModelStatus | null; error: string; onRetry: () => void; confirmedCount: number | null; exportDisabled: boolean; onReview: () => void; onExport: () => void }) {
  const evaluation = status?.evaluation;
  const matrixCategories = evaluation ? status.supportedCategories : categories;
  const percent = (value: number | undefined) => value === undefined ? "—" : `${(value * 100).toFixed(1)}%`;
  const title = error ? "Model status unavailable" : !status ? "Loading model status…" : {
    ready: "Active category model", unconfigured: "No evaluated model is active",
    invalid: "Selected model unavailable", demo: "Demo predictions are illustrative",
  }[status.state];
  const description = error || (!status ? "Checking the local backend." : status.state === "ready" ?
    "This evaluated local model classifies new mail and retries missing predictions during sync." : status.state === "invalid" ?
    "The selected artifact is missing, corrupt, or incompatible. Check the trusted local run and restart the backend. Stored mail and priority rules remain available." : status.state === "demo" ?
    "Synthetic predictions demonstrate the inbox. They are not an evaluated active model." :
    "Train from confirmed category labels, inspect the saved evaluation, then select the approved run in backend configuration and restart. Priority-only labels are retained separately.");
  return <section className="view" aria-labelledby="models-title">
    <header className="page-heading"><div className="page-heading-copy model-intro"><p className="eyebrow">Explainable baseline</p><h1 id="models-title">Model lab</h1><p>Keep every model version accountable before it classifies new mail.</p></div></header>
    <section className="model-status" aria-labelledby="model-status-title"><div className="model-status-copy"><div className="model-status-icon"><Icon name="model" /></div><div><h2 id="model-status-title">{title}</h2><p role="status">{description}</p>
      {status?.state === "ready" && <><p>Version: {status.modelVersion}</p><p>Supported categories: {status.supportedCategories.join(", ")}</p><p>{status.reviewThreshold === null ? "All unconfirmed category predictions need review." : `Review cutoff: ${confidenceText(status.reviewThreshold)}. Confidence equal to the cutoff is accepted.`} {status.thresholdOverridden ? "Backend configuration overrides saved model cutoffs." : "Saved cutoffs remain attached to earlier predictions."}</p></>}
      <div className="model-count"><strong>{confirmedCount ?? "—"}</strong><span>confirmed labels available for export</span></div></div></div><div className="model-status-actions">{error && <button className="btn btn-secondary" type="button" onClick={onRetry}>Retry model status</button>}<button className="btn btn-secondary" type="button" onClick={onReview}>Review labels</button><button className="btn btn-primary" type="button" onClick={onExport} disabled={exportDisabled}>Export confirmed labels</button></div></section>
    <div className="model-grid"><section className="panel model-panel" aria-labelledby="metrics-title"><div className="model-panel-head"><h2 id="metrics-title">Held-out evaluation</h2><p>Saved test results for the active model; probabilities are uncalibrated.</p></div><div className="macro-card"><span>Macro F1</span><strong aria-label={evaluation ? undefined : "Not available"}>{percent(evaluation?.macroF1)}</strong></div><table className="metrics-table"><caption className="sr-only">{evaluation ? "Per-class held-out metrics for the active model." : "No active held-out metrics are available."}</caption><thead><tr><th>Category</th><th>Precision</th><th>Recall</th><th>F1</th></tr></thead><tbody>{categories.map((category) => {
      const metric = evaluation?.perClass.find((row) => row.category === category);
      return <tr key={category}><th scope="row">{category}</th><td>{percent(metric?.precision)}</td><td>{percent(metric?.recall)}</td><td>{percent(metric?.f1)}</td></tr>;
    })}</tbody></table><p className="table-note">{evaluation ? "Excluded categories have no scores. Small held-out samples do not guarantee future performance." : "Activate an evaluated local model to display its saved metrics."}</p></section>
      <section className="panel model-panel" aria-labelledby="matrix-title"><div className="model-panel-head"><h2 id="matrix-title">Confusion matrix</h2><p>Actual labels by predicted labels.</p></div><p className="matrix-note">{evaluation ? "Saved class ordering is used for both axes." : "No active evaluation is available. Empty cells do not imply zero errors."}</p><div className="matrix-wrap"><table className="matrix-table"><caption className="sr-only">{evaluation ? "Held-out confusion matrix in saved class order." : "Confusion matrix values are unavailable."}</caption><thead><tr><th>Actual / Pred.</th>{matrixCategories.map((category) => <th key={category} title={category}>{category.slice(0, 3)}</th>)}</tr></thead><tbody>{matrixCategories.map((category, row) => <tr key={category}><th scope="row" title={category}>{category}</th>{matrixCategories.map((column, index) => <td key={column}>{evaluation?.confusionMatrix[row][index] ?? "—"}</td>)}</tr>)}</tbody></table></div></section></div>
    <section className="workflow-steps" aria-label="Training workflow"><article className="workflow-step"><span className="step-index">1</span><strong>Build the label set</strong><p>Review stored messages; confirmed corrections stay separate from original predictions. Category training uses human category labels only.</p></article><article className="workflow-step"><span className="step-index">2</span><strong>Evaluate offline</strong><p>Run <code>uv run python -m app.train</code> locally and inspect the saved evaluation before approving a replacement.</p></article><article className="workflow-step"><span className="step-index">3</span><strong>Activate with care</strong><p>Select the approved run in backend configuration and restart. Training never activates a model automatically.</p></article></section>
    <p className="threshold-note">{status?.state === "demo" ? "Demo predictions are illustrative. " : ""}Email content and labels stay local; no remote model is used. English and Indonesian text rules assign priority independently.</p>
  </section>;
}

export default App;
