import { useEffect, useMemo, useRef, useState } from "react";
import type { CSSProperties, ReactNode } from "react";
import { fixtureAdapter, priorityOf, type InboxAdapter } from "./api";
import { categories, priorities, type Category, type CategoryFilter, type CategoryStat, type Email, type HumanLabel, type LabelsById, type Priority } from "./data";
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

function categoryOf(email: Email, labels: LabelsById): CategoryFilter {
  return labels[email.id]?.category ?? email.prediction?.category ?? "Unclassified";
}

function isNeedsReview(email: Email, labels: LabelsById) {
  return !labels[email.id] && email.prediction?.confidence !== undefined && email.prediction.confidence < 70;
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

function App({ adapter = fixtureAdapter }: { adapter?: InboxAdapter }) {
  const [emails, setEmails] = useState<Email[]>([]);
  const [labels, setLabels] = useState<LabelsById>({});
  const [stats, setStats] = useState<CategoryStat[]>([]);
  const [loadingStats, setLoadingStats] = useState(true);
  const [statsError, setStatsError] = useState("");
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState("");
  const [page, setPage] = useState<Page>("inbox");
  const [quickFilter, setQuickFilter] = useState<QuickFilter>("all");
  const [categoryFilter, setCategoryFilter] = useState<CategoryFilter | "All">("All");
  const [priorityFilter, setPriorityFilter] = useState<Priority | "All">("All");
  const [search, setSearch] = useState("");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [toast, setToast] = useState("");
  const [syncing, setSyncing] = useState(false);
  const [syncMessage, setSyncMessage] = useState("example messages, no live account connected.");
  const [syncError, setSyncError] = useState("");
  const [dialogOpen, setDialogOpen] = useState(false);
  const [saving, setSaving] = useState(false);
  const [mobileDetail, setMobileDetail] = useState(false);
  const [draftCategory, setDraftCategory] = useState<Category>("Other");
  const [draftPriority, setDraftPriority] = useState<Priority>("Medium");
  const dialogRef = useRef<HTMLDialogElement>(null);
  const toastTimer = useRef<number | undefined>(undefined);

  useEffect(() => {
    let alive = true;
    Promise.all([adapter.getEmails(), adapter.getLabels()]).then(([nextEmails, nextLabels]) => {
      if (!alive) return;
      setEmails(nextEmails);
      setLabels(nextLabels);
      setSelectedId(nextEmails[0]?.id ?? null);
      setLoading(false);
      adapter.getCategoryStats().then((nextStats) => {
        if (!alive) return;
        setStats(nextStats);
        setLoadingStats(false);
      }).catch(() => {
        if (!alive) return;
        setStatsError("Category counts could not be loaded. Reload the inbox to try again.");
        setLoadingStats(false);
      });
    }).catch(() => {
      if (!alive) return;
      setLoadError("Messages could not be loaded. Try reloading the sample inbox.");
      setLoading(false);
      setLoadingStats(false);
    });
    return () => { alive = false; };
  }, [adapter]);

  useEffect(() => {
    const dialog = dialogRef.current;
    if (!dialog) return;
    if (dialogOpen && !dialog.open) dialog.showModal();
    if (!dialogOpen && dialog.open) dialog.close();
  }, [dialogOpen]);

  useEffect(() => () => window.clearTimeout(toastTimer.current), []);

  const tree = useMemo(() => buildTreemap(stats), [stats]);
  const allReview = useMemo(() => emails.filter((email) => isNeedsReview(email, labels)).length, [emails, labels]);
  const confirmedCount = Object.keys(labels).length;

  const visibleEmails = useMemo(() => {
    const query = search.trim().toLocaleLowerCase();
    return emails.filter((email) => {
      const effectiveCategory = categoryOf(email, labels);
      const priority = priorityOf(email, labels);
      if (categoryFilter !== "All" && effectiveCategory !== categoryFilter) return false;
      if (priorityFilter !== "All" && priority !== priorityFilter) return false;
      if (quickFilter === "review" && !isNeedsReview(email, labels)) return false;
      if (quickFilter === "high" && priority !== "High") return false;
      if (query && ![email.sender, email.address, email.subject, email.body, effectiveCategory, priority].join(" ").toLocaleLowerCase().includes(query)) return false;
      return true;
    });
  }, [emails, labels, categoryFilter, priorityFilter, quickFilter, search]);

  const selectedEmail = visibleEmails.find((email) => email.id === selectedId) ?? null;

  useEffect(() => {
    if (!visibleEmails.some((email) => email.id === selectedId)) setSelectedId(visibleEmails[0]?.id ?? null);
  }, [visibleEmails, selectedId]);

  useEffect(() => {
    if (!selectedEmail) return;
    const label = labels[selectedEmail.id];
    setDraftCategory(label?.category ?? selectedEmail.prediction?.category ?? "Other");
    setDraftPriority(label?.priority ?? selectedEmail.prediction?.priority ?? "Medium");
  }, [selectedEmail, labels]);

  function notify(message: string) {
    setToast(message);
    window.clearTimeout(toastTimer.current);
    toastTimer.current = window.setTimeout(() => setToast(""), 2800);
  }

  function setFilter(next: QuickFilter) {
    setQuickFilter(next);
    setPage(next === "review" ? "review" : "inbox");
    setMobileDetail(false);
  }

  function selectCategory(category: CategoryFilter) {
    setCategoryFilter(category);
    setPriorityFilter("All");
    setQuickFilter("all");
    setPage("inbox");
    setMobileDetail(false);
    requestAnimationFrame(() => document.getElementById("messages-title")?.scrollIntoView?.({ behavior: "smooth", block: "start" }));
  }

  async function saveLabels() {
    if (!selectedEmail) return;
    const next: HumanLabel = { category: draftCategory, priority: draftPriority, confirmedAt: new Date().toISOString() };
    setSaving(true);
    try {
      await adapter.saveLabel(selectedEmail.id, next);
      setLabels((current) => ({ ...current, [selectedEmail.id]: next }));
      notify("Your labels are saved on this device.");
      setStatsError("");
      setLoadingStats(true);
      adapter.getCategoryStats().then((nextStats) => {
        setStats(nextStats);
        setLoadingStats(false);
      }).catch(() => {
        setStatsError("Category counts could not be refreshed. Reload the inbox to try again.");
        setLoadingStats(false);
      });
    } catch {
      notify("Labels could not be saved. Your changes are still here—try again.");
    } finally {
      setSaving(false);
    }
  }

  async function syncInbox() {
    setSyncing(true);
    setSyncError("");
    try {
      const result = await adapter.sync();
      setSyncMessage(`example messages, checked just now${result.imported ? ` · ${result.imported} new` : ""}`);
      notify("Sample inbox is up to date.");
    } catch {
      setSyncError("Sync did not finish. Check the connection and try again.");
    } finally {
      setSyncing(false);
    }
  }

  function exportLabels() {
    const labelled = emails.filter((email) => labels[email.id]);
    const rows = [["message_id", "sender", "subject", "predicted_category", "predicted_priority", "confidence", "confirmed_category", "confirmed_priority", "confirmed_at"]];
    labelled.forEach((email) => {
      const label = labels[email.id];
      rows.push([email.id, email.sender, email.subject, email.prediction?.category ?? "", email.prediction?.priority ?? "", String(email.prediction?.confidence ?? ""), label.category, label.priority, label.confirmedAt]);
    });
    const csv = rows.map((row) => row.map((cell) => `"${cell.replaceAll('"', '""')}"`).join(",")).join("\r\n");
    const url = URL.createObjectURL(new Blob([csv], { type: "text/csv;charset=utf-8" }));
    const link = document.createElement("a");
    link.href = url;
    link.download = "meiruzo-confirmed-labels.csv";
    document.body.append(link);
    link.click();
    link.remove();
    window.setTimeout(() => URL.revokeObjectURL(url), 0);
    notify(`Exported ${labelled.length} confirmed ${labelled.length === 1 ? "label" : "labels"}.`);
  }

  function clearFilters() {
    setPage("inbox");
    setCategoryFilter("All");
    setPriorityFilter("All");
    setQuickFilter("all");
    setSearch("");
  }

  function editSelection(email: Email) {
    setSelectedId(email.id);
    const label = labels[email.id];
    setDraftCategory(label?.category ?? email.prediction?.category ?? "Other");
    setDraftPriority(label?.priority ?? email.prediction?.priority ?? "Medium");
    setMobileDetail(true);
  }

  const pageTitle = page === "models" ? "Model lab" : page === "review" ? "Needs review" : "Smart inbox";
  const totalUnclassified = stats.find((stat) => stat.category === "Unclassified")?.count ?? 0;

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
          <div className="mailbox-card-head"><span className="status-dot" /><span className="mailbox-card-copy">Sample mailbox</span></div>
          <p className="mailbox-card-copy">Preview data only. No account connected.</p>
          <button className="mailbox-card-copy" type="button" onClick={() => setDialogOpen(true)}>Set up mailbox</button>
        </div>
      </aside>

      <div className="main-shell">
        <header className="topbar">
          <div className="breadcrumbs" aria-label="Breadcrumb"><span>Workspace</span><span aria-hidden="true">/</span><strong>{pageTitle}</strong></div>
          <div className="top-actions"><span className="demo-badge">Demo data</span><button className="avatar" type="button" aria-label="Demo account, Rowan Kim" title="Demo account">RK</button></div>
        </header>

        <main className="app-main">
          {page === "models" ? (
            <ModelLab confirmedCount={confirmedCount} onReview={() => { setPage("inbox"); setFilter("all"); }} onExport={exportLabels} />
          ) : (
            <section className="view" aria-labelledby="inbox-title">
              <header className="page-heading">
                <div className="page-heading-copy"><p className="eyebrow">Your mailbox, in focus</p><h1 id="inbox-title">{pageTitle}</h1><p>Find the messages that matter, then teach Meiruzo what matters to you.</p></div>
                <div className="page-actions">
                  <button className="btn btn-secondary" type="button" onClick={() => setDialogOpen(true)}><Icon name="plus" />Connect mailbox</button>
                  <button className="btn btn-primary" type="button" onClick={syncInbox} disabled={syncing}><Icon name="sync" />{syncing ? "Syncing…" : "Sync sample"}</button>
                </div>
              </header>

              <div className="workspace-note" role="status">
                <span><strong>Sample mailbox</strong> <span>— {syncMessage}</span></span>
                {syncError ? <button className="text-button" type="button" onClick={syncInbox}>Try again</button> : <button className="text-button" type="button" onClick={() => setDialogOpen(true)}>Set up a mailbox</button>}
              </div>

              {loadError && <div className="state-message error-message" role="alert"><strong>Inbox unavailable</strong><p>{loadError}</p><button className="text-button" type="button" onClick={() => window.location.reload()}>Reload inbox</button></div>}
              {syncError && <div className="state-message error-message" role="alert"><strong>Sync failed</strong><p>{syncError}</p></div>}

              <div className="inline-stats" aria-label="Inbox counts">
                <div className="inline-stat"><strong>{emails.length}</strong><span>messages</span></div>
                <div className="inline-stat"><strong>{allReview}</strong><span>needs review</span></div>
                <div className="inline-stat"><strong>{confirmedCount}</strong><span>labels confirmed</span></div>
              </div>

              <section className="panel overview-panel" aria-labelledby="overview-title">
                <div className="panel-head"><div className="panel-head-copy"><h2 id="overview-title">Inbox map</h2><p>All stored messages by category; tile area reflects count.</p></div></div>
                <div className="map-meta"><span>Full sample mailbox · independent of inbox filters</span><span>{emails.length} {emails.length === 1 ? "message" : "messages"}{totalUnclassified ? ` · ${totalUnclassified} unclassified` : ""}</span></div>
                <div className="map-root" id="treemap" role="group" aria-label="Category treemap for all stored messages">
                  {loading || loadingStats ? <div className="map-empty" role="status">Loading category counts…</div> : loadError || statsError ? <div className="map-empty" role="status">{statsError || "Category counts are unavailable."}</div> : tree ? <TreemapBranch node={tree} selected={categoryFilter} onSelect={selectCategory} /> : <div className="map-empty">No messages yet. Sync to load the local inbox.</div>}
                </div>
                <div className="category-list" aria-label="Category counts">
                  {stats.map(({ category, count, percentage }) => <button className="category-count" key={category} type="button" aria-pressed={categoryFilter === category} onClick={() => selectCategory(category)}>
                    <span className="category-swatch" style={{ background: categoryColors[category] }} aria-hidden="true" /><span className="category-name">{category}</span><strong>{count}</strong><span className="category-percent">{percentage}%</span>
                  </button>)}
                </div>
              </section>

              <section className="inbox-section" aria-labelledby="messages-title">
                <div className="section-bar"><div className="section-title"><h2 id="messages-title">Messages</h2><p id="result-count" aria-live="polite">{loading ? "Loading messages…" : `${visibleEmails.length} ${visibleEmails.length === 1 ? "message" : "messages"}`}</p></div>
                  <div className="inbox-tools">
                    <label className="search-control" htmlFor="search-input"><span>Search messages</span><input id="search-input" type="search" autoComplete="off" placeholder="Sender, subject, or body" value={search} onChange={(event) => setSearch(event.target.value)} /></label>
                    <button className="btn btn-secondary export-button" id="export-labels" type="button" onClick={exportLabels} aria-label="Export confirmed labels as CSV"><Icon name="download" />Export labels</button>
                  </div>
                </div>

                <div className="filter-row" role="group" aria-label="Filter messages">
                  <button className="filter-button" type="button" aria-pressed={quickFilter === "all"} onClick={() => setFilter("all")}>All messages <span className="filter-count">{emails.length}</span></button>
                  <button className="filter-button" type="button" aria-pressed={quickFilter === "review"} onClick={() => setFilter("review")}>Needs review <span className="filter-count">{allReview}</span></button>
                  <button className="filter-button" type="button" aria-pressed={quickFilter === "high"} onClick={() => setFilter("high")}>High priority</button>
                  <label className="filter-select"><span>Category</span><select aria-label="Filter by category" value={categoryFilter} onChange={(event) => setCategoryFilter(event.target.value as CategoryFilter | "All")}><option value="All">All categories</option>{categories.map((category) => <option key={category}>{category}</option>)}<option>Unclassified</option></select></label>
                  <label className="filter-select"><span>Priority</span><select aria-label="Filter by priority" value={priorityFilter} onChange={(event) => setPriorityFilter(event.target.value as Priority | "All")}><option value="All">All priorities</option>{priorities.map((priority) => <option key={priority}>{priority}</option>)}</select></label>
                  {(categoryFilter !== "All" || priorityFilter !== "All" || quickFilter !== "all" || search) && <button type="button" className="text-button clear-filters" onClick={clearFilters}>Clear filters</button>}
                </div>

                <div className={`email-layout ${mobileDetail ? "detail-open" : ""}`}>
                  <section className="panel list-panel" aria-label="Email message list">
                    <div className="list-head"><span>{page === "review" ? "Needs review" : "Inbox"}</span><span>Model signal</span></div>
                    <div className="email-list" aria-label="Messages">
                      {loading ? <div className="empty-list" role="status">Loading messages…</div> : !visibleEmails.length ? <div className="empty-list"><h3>{emails.length ? "No messages here" : "Your inbox is empty"}</h3><p>{emails.length ? "Try another filter or search to return to the inbox." : "Sync when you are ready to add local messages."}</p><button type="button" onClick={clearFilters}>Clear filters</button></div> : visibleEmails.map((email) => <EmailRow key={email.id} email={email} labels={labels} selected={email.id === selectedId} onClick={() => editSelection(email)} />)}
                    </div>
                  </section>
                  <article className="panel detail-panel" id="email-detail" aria-label="Selected email">
                    {selectedEmail ? <EmailDetail email={selectedEmail} label={labels[selectedEmail.id]} draftCategory={draftCategory} draftPriority={draftPriority} saving={saving} onCategory={setDraftCategory} onPriority={setDraftPriority} onSave={saveLabels} onBack={() => setMobileDetail(false)} /> : <div className="no-selection"><h3>No message selected</h3><p>Clear a filter or search for another message to continue reviewing your inbox.</p></div>}
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
          <p className="dialog-body">Meiruzo connects through IMAP and keeps message review available when a model is uncertain. This clickable preview uses sample messages and does not connect to a mail server.</p>
          <div className="secure-note"><Icon name="lock" /><span>This preview never asks for a mailbox password. In the product, IMAP credentials must be handled by the secure service.</span></div>
          <div className="dialog-actions"><button className="btn btn-secondary" type="button" onClick={() => setDialogOpen(false)}>Cancel</button><button className="btn btn-primary" type="button" onClick={() => { setSyncMessage("example messages only; no mail server connected."); setDialogOpen(false); notify("Demo mailbox is ready."); }}>Continue with demo</button></div>
        </div>
      </dialog>
      <div className={`toast ${toast ? "visible" : ""}`} role="status" aria-live="polite">{toast}</div>
    </div>
  );
}

function NavButton({ icon, label, count, current, onClick }: { icon: "mail" | "review" | "model"; label: string; count?: number; current: boolean; onClick: () => void }) {
  return <button className="nav-link" type="button" aria-label={label} aria-current={current ? "page" : undefined} onClick={onClick}><Icon name={icon} /><span>{label}</span>{count !== undefined && <span className="nav-count">{count}</span>}</button>;
}

function EmailRow({ email, labels, selected, onClick }: { email: Email; labels: LabelsById; selected: boolean; onClick: () => void }) {
  const category = categoryOf(email, labels);
  const priority = priorityOf(email, labels);
  const review = isNeedsReview(email, labels);
  return <button className={`email-row ${email.read ? "read" : "unread"}`} type="button" aria-current={selected ? "true" : "false"} aria-label={`${email.sender}, ${email.subject}, ${category}, ${priority ?? "priority unavailable"}${review ? ", needs review" : ""}`} onClick={onClick}>
    <span className="email-row-top"><span className="email-sender">{email.sender}</span><span className="email-time">{email.received}</span></span>
    <span className="email-subject">{email.subject}</span>
    <span className="email-snippet">{email.body.replace(/\s+/g, " ").trim()}</span>
    <span className="email-row-bottom"><span className="tag">{category}</span>{priority && <span className={`tag priority-tag ${priority.toLowerCase()}`}>{priority}</span>}{review && <span className="review-status">Needs review</span>}{email.hasAttachments && <span className="attachment-status">Attachment</span>}{!email.read && <span className="unread-status">Unread</span>}<span className="confidence">{email.prediction?.confidence === undefined ? "No prediction" : `Demo ${email.prediction.confidence}%`}</span></span>
  </button>;
}

function EmailDetail({ email, label, draftCategory, draftPriority, saving, onCategory, onPriority, onSave, onBack }: { email: Email; label?: HumanLabel; draftCategory: Category; draftPriority: Priority; saving: boolean; onCategory: (category: Category) => void; onPriority: (priority: Priority) => void; onSave: () => void; onBack: () => void }) {
  const prediction = email.prediction;
  return <>
    <div className="detail-top"><div className="detail-top-copy"><button className="back-to-list" type="button" onClick={onBack}>← Back to messages</button><h2>{email.subject}</h2><p className="detail-sender">{email.sender} &lt;{email.address}&gt;</p><span className="detail-time">{email.received} · Demo message</span></div></div>
    <div className="detail-body"><p>{email.body}</p><div className="message-flags"><span>{email.read ? "Read" : "Unread"}</span><span>{email.hasAttachments ? "Has attachment" : "No attachments"}</span></div></div>
    <section className="prediction-block" aria-label="Original demo prediction"><div className="prediction-head"><strong>Original prediction</strong><span className="demo-label">{prediction ? "Demo estimate" : "Not available"}</span></div>
      {prediction ? <><div className="prediction-values"><span className="tag">{prediction.category ?? "Category unavailable"}</span><span className="tag priority-tag">{prediction.priority ?? "Priority unavailable"} priority</span><span className="tag">{prediction.confidence === undefined ? "Confidence unavailable" : `Category confidence ${prediction.confidence}%`}</span></div><p className="prediction-explanation">{prediction.reasonCategory ?? "This is synthetic demo data; no model is connected."}</p></> : <p className="prediction-explanation">No model prediction is available for this message yet.</p>}
    </section>
    <section className="edit-block" aria-labelledby="edit-labels-title"><div className="edit-heading"><strong id="edit-labels-title">Your confirmed labels</strong><span>{label ? "Human label · saved on this device" : "Separate from prediction"}</span></div>
      <div className="edit-fields"><div className="field"><label htmlFor="edit-category">Category</label><select id="edit-category" value={draftCategory} onChange={(event) => onCategory(event.target.value as Category)}>{categories.map((category) => <option key={category}>{category}</option>)}</select></div><div className="field"><label htmlFor="edit-priority">Priority</label><select id="edit-priority" value={draftPriority} onChange={(event) => onPriority(event.target.value as Priority)}>{priorities.map((priority) => <option key={priority}>{priority}</option>)}</select></div></div>
      <div className="edit-actions"><p className="edit-note">Confirm or change either label. Original predictions remain available for comparison.</p><button className="btn btn-primary save-button" type="button" onClick={onSave} disabled={saving}>{saving ? "Saving…" : label ? "Update labels" : "Confirm labels"}</button></div>
    </section>
  </>;
}

function ModelLab({ confirmedCount, onReview, onExport }: { confirmedCount: number; onReview: () => void; onExport: () => void }) {
  const abbreviations = ["Rec", "Lnk", "Per", "Txn", "Nws", "Pro", "Spm", "Oth"];
  return <section className="view" aria-labelledby="models-title">
    <header className="page-heading"><div className="page-heading-copy model-intro"><p className="eyebrow">Explainable baseline</p><h1 id="models-title">Model lab</h1><p>Keep every model version accountable before it classifies new mail.</p></div></header>
    <section className="model-status" aria-labelledby="model-status-title"><div className="model-status-copy"><div className="model-status-icon"><Icon name="model" /></div><div><h2 id="model-status-title">No evaluated model is active</h2><p>This demo shows sample predictions only. A saved model becomes eligible for new mail after a held-out evaluation is recorded.</p><div className="model-count"><strong>{confirmedCount}</strong><span>confirmed labels available for export</span></div></div></div><div className="model-status-actions"><button className="btn btn-secondary" type="button" onClick={onReview}>Review labels</button><button className="btn btn-primary" type="button" onClick={onExport}>Export confirmed labels</button></div></section>
    <div className="model-grid"><section className="panel model-panel" aria-labelledby="metrics-title"><div className="model-panel-head"><h2 id="metrics-title">Held-out evaluation</h2><p>Report per-class precision, recall, and F1 before a model is used.</p></div><div className="macro-card"><span>Macro F1</span><strong aria-label="Not available">—</strong></div><table className="metrics-table"><caption className="sr-only">Per-class evaluation metrics are unavailable until a held-out run exists.</caption><thead><tr><th>Category</th><th>Precision</th><th>Recall</th><th>F1</th></tr></thead><tbody>{categories.map((category) => <tr key={category}><th scope="row">{category}</th><td>—</td><td>—</td><td>—</td></tr>)}</tbody></table><p className="table-note">No held-out run yet. Values appear after training and evaluation on labeled data.</p></section>
      <section className="panel model-panel" aria-labelledby="matrix-title"><div className="model-panel-head"><h2 id="matrix-title">Confusion matrix</h2><p>Actual labels by predicted labels.</p></div><p className="matrix-note">No evaluation has been run. Empty cells stay blank instead of implying zero errors.</p><div className="matrix-wrap"><table className="matrix-table"><caption className="sr-only">Confusion matrix has no values because no held-out evaluation exists.</caption><thead><tr><th>Actual / Pred.</th>{abbreviations.map((item, index) => <th key={item} title={categories[index]}>{item}</th>)}</tr></thead><tbody>{categories.map((category) => <tr key={category}><th scope="row" title={category}>{category}</th>{abbreviations.map((item) => <td key={item}>—</td>)}</tr>)}</tbody></table></div></section></div>
    <section className="workflow-steps" aria-label="Training workflow"><article className="workflow-step"><span className="step-index">1</span><strong>Build the label set</strong><p>Review sample messages; confirmed corrections stay separate from original predictions.</p></article><article className="workflow-step"><span className="step-index">2</span><strong>Evaluate offline</strong><p>Hold out examples and review per-category performance before activation.</p></article><article className="workflow-step"><span className="step-index">3</span><strong>Activate with care</strong><p>Use a model only after its evaluation and artifact have been saved locally.</p></article></section>
    <p className="threshold-note">Sample predictions are illustrative. Email content and labels remain in this browser preview; no remote model is used.</p>
  </section>;
}

export default App;
