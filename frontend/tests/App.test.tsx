import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import App from "../src/App";
import { ApiError, fixtureAdapter, type EmailDetail, type InboxAdapter, type SyncStatus } from "../src/api";

function adapter(overrides: Partial<InboxAdapter> = {}): InboxAdapter { return { ...fixtureAdapter, ...overrides }; }
function show(overrides: Partial<InboxAdapter> = {}) { return render(<App adapter={adapter(overrides)} />); }
const messages = () => within(screen.getByLabelText("Email message list"));
const detail = () => within(screen.getByRole("article", { name: "Selected email" }));
const ready = () => screen.findByRole("button", { name: /Jo Park.*Product designer interview/ });
async function edit(category: string) {
  fireEvent.click(await ready());
  fireEvent.change(await detail().findByLabelText("Category"), { target: { value: category } });
}

beforeEach(() => localStorage.clear());
afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.unstubAllGlobals(); });

describe("Smart Inbox", () => {
  it("uses the HTTP API by default and never falls back to fixture data", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("offline")));
    render(<App />);
    expect(await screen.findByRole("button", { name: "Retry inbox" })).toBeInTheDocument();
    expect(messages().queryByText("A note for Rowan")).not.toBeInTheDocument();
  });
  it("filters from a treemap category without changing global totals", async () => {
    show(); await ready();
    const list = screen.getByLabelText("Category counts");
    fireEvent.click(await within(list).findByRole("button", { name: /Recruitment/ }));
    await waitFor(() => expect(messages().queryByText("A new message from Avery Chen")).not.toBeInTheDocument());
    expect(await ready()).toBeInTheDocument();
    expect(screen.getByText("All stored messages · independent of inbox filters")).toBeInTheDocument();
    expect(within(list).getByRole("button", { name: /Personal 4 22%/ })).toBeInTheDocument();
  });

  it("combines search, review and priority through list queries", async () => {
    const listEmails = vi.fn(fixtureAdapter.listEmails); show({ listEmails }); await ready();
    fireEvent.change(screen.getByRole("searchbox"), { target: { value: "Northstar" } });
    fireEvent.click(within(screen.getByRole("group", { name: "Filter messages" })).getByRole("button", { name: /Needs review/ }));
    fireEvent.change(screen.getByLabelText("Filter by priority"), { target: { value: "High" } });
    await waitFor(() => expect(listEmails).toHaveBeenCalledWith(expect.objectContaining({ q: "Northstar", priority: "High", needsReview: true, offset: 0 }), expect.any(AbortSignal)));
    expect(await ready()).toHaveAttribute("type", "button");
    fireEvent.change(screen.getByRole("searchbox"), { target: { value: "no matching message" } });
    expect(await screen.findByText("No messages here")).toBeInTheDocument();
  });

  it("pages on the server and resets pagination when filters change", async () => {
    const first = (await fixtureAdapter.listEmails()).items[0];
    const listEmails = vi.fn(async (query = {}) => {
      if (query.hasHumanLabel || query.needsReview) return fixtureAdapter.listEmails(query);
      return { items: [{ ...first, id: `page-${query.offset ?? 0}`, subject: `Page ${query.offset ?? 0}` }], total: 51, limit: 50, offset: query.offset ?? 0 };
    });
    const getEmail = vi.fn(async (id: string) => ({ ...await fixtureAdapter.getEmail("m01"), id }));
    show({ listEmails, getEmail });
    await messages().findByText("Page 0");
    fireEvent.click(screen.getByRole("button", { name: "Next" }));
    await messages().findByText("Page 50");
    expect(screen.getByText("51–51 of 51")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Next" })).toBeDisabled();
    fireEvent.change(screen.getByLabelText("Filter by category"), { target: { value: "Personal" } });
    await messages().findByText("Page 0");
    expect(screen.getByRole("button", { name: "Previous" })).toBeDisabled();
    expect(listEmails).toHaveBeenLastCalledWith(expect.objectContaining({ category: "Personal", offset: 0 }), expect.any(AbortSignal));
  });

  it("ignores a stale detail response after switching selection", async () => {
    let resolveFirst: (email: EmailDetail) => void = () => {};
    const getEmail = vi.fn((id: string) => id === "m01" ? new Promise<EmailDetail>((resolve) => { resolveFirst = resolve; }) : fixtureAdapter.getEmail(id));
    show({ getEmail }); await ready();
    fireEvent.click(screen.getByRole("button", { name: /TalentWorks/ }));
    await detail().findByText("Your application has moved to review");
    await act(async () => resolveFirst(await fixtureAdapter.getEmail("m01")));
    expect(detail().getByText("Your application has moved to review")).toBeInTheDocument();
    expect(detail().queryByText("Product designer interview — Thursday")).not.toBeInTheDocument();
  });

  it("ignores a stale list response after a newer search completes", async () => {
    let resolveOld: (page: Awaited<ReturnType<InboxAdapter["listEmails"]>>) => void = () => {};
    const listEmails: InboxAdapter["listEmails"] = (query = {}) => query.q === "old" ? new Promise((resolve) => { resolveOld = resolve; }) : fixtureAdapter.listEmails(query);
    show({ listEmails }); await ready();
    fireEvent.change(screen.getByRole("searchbox"), { target: { value: "old" } });
    fireEvent.change(screen.getByRole("searchbox"), { target: { value: "TalentWorks" } });
    await messages().findByText("Your application has moved to review");
    await act(async () => resolveOld(await fixtureAdapter.listEmails()));
    expect(messages().queryByText("A note for Rowan")).not.toBeInTheDocument();
  });

  it("saves category-only corrections with a server timestamp and refreshes counts", async () => {
    const saveLabel = vi.fn(fixtureAdapter.saveLabel); show({ saveLabel }); await edit("Personal");
    expect(detail().getByLabelText("Priority")).toHaveValue("");
    fireEvent.click(screen.getByRole("button", { name: "Confirm labels" }));
    await screen.findByText("Your labels are saved on this device.");
    expect(saveLabel).toHaveBeenCalledWith("m01", { category: "Personal", source: "correction" });
    await detail().findByText("Human label · saved on this device");
    expect(detail().getByText("Recruitment", { selector: ".prediction-values .tag" })).toBeInTheDocument();
    await waitFor(() => expect(within(screen.getByLabelText("Category counts")).getByRole("button", { name: /Personal 5 28%/ })).toBeInTheDocument());
    expect((await fixtureAdapter.getEmail("m01")).humanLabel?.confirmedAt).toMatch(/Z$/);
  });

  it("does not confirm category when saving priority only", async () => {
    const saveLabel = vi.fn(fixtureAdapter.saveLabel); show({ saveLabel }); await ready();
    fireEvent.change(await detail().findByLabelText("Priority"), { target: { value: "Low" } });
    fireEvent.click(screen.getByRole("button", { name: "Confirm labels" }));
    await screen.findByText("Your labels are saved on this device.");
    expect(saveLabel).toHaveBeenCalledWith("m01", { priority: "Low", source: "correction" });
    const email = await fixtureAdapter.getEmail("m01");
    expect(email.humanLabel?.category).toBeNull(); expect(email.needsReview).toBe(true);
    await waitFor(() => expect(detail().getByLabelText("Category")).toHaveValue(""));
  });

  it("keeps drafts through a failed save, refresh and selection change before retry", async () => {
    const saveLabel = vi.fn().mockRejectedValueOnce(new Error("offline")).mockImplementation(fixtureAdapter.saveLabel);
    show({ saveLabel }); await edit("Personal");
    fireEvent.click(screen.getByRole("button", { name: "Confirm labels" }));
    await screen.findByText("Labels could not be saved. Your changes are still here—try again.");
    fireEvent.click(screen.getByRole("button", { name: "Refresh inbox" }));
    await waitFor(() => expect(detail().getByLabelText("Category")).toHaveValue("Personal"));
    fireEvent.click(await screen.findByRole("button", { name: /TalentWorks/ }));
    await detail().findByText("Your application has moved to review");
    fireEvent.click(await ready());
    expect(await detail().findByLabelText("Category")).toHaveValue("Personal");
    fireEvent.click(screen.getByRole("button", { name: "Confirm labels" }));
    await screen.findByText("Your labels are saved on this device.");
    expect(saveLabel).toHaveBeenCalledTimes(2);
  });

  it("has no fabricated labels or confidence for missing predictions", async () => {
    show(); await ready(); fireEvent.click(screen.getByRole("button", { name: /Local Notes/ }));
    expect(await detail().findByLabelText("Category")).toHaveValue("");
    expect(detail().getByLabelText("Priority")).toHaveValue("");
    expect(screen.getByRole("button", { name: "Confirm labels" })).toBeDisabled();
    expect(detail().getByText("No model prediction is available for this message yet.")).toBeInTheDocument();
  });

  it("uses the server review flag rather than a hard-coded confidence threshold", async () => {
    const getEmail = async (id: string) => ({ ...await fixtureAdapter.getEmail(id), needsReview: false });
    const listEmails: InboxAdapter["listEmails"] = async (query) => {
      const result = await fixtureAdapter.listEmails(query);
      return { ...result, items: result.items.map((email) => ({ ...email, needsReview: false })) };
    };
    show({ listEmails, getEmail });
    expect(await ready()).not.toHaveAccessibleName(/needs review/);
  });

  it("identifies demo sync and refreshes messages after success", async () => {
    const listEmails = vi.fn(fixtureAdapter.listEmails); show({ listEmails }); await ready();
    fireEvent.change(screen.getByLabelText("Sync messages"), { target: { value: "unread" } });
    fireEvent.click(await screen.findByRole("button", { name: "Sync demo" }));
    await screen.findByText("Demo sync complete; no mailbox was contacted.");
    await waitFor(() => expect(listEmails.mock.calls.filter(([query]) => query?.limit === 50).length).toBe(2));
  });

  it("shows partial sync counters and failure without discarding saved messages", async () => {
    const status: SyncStatus = { ...await fixtureAdapter.getSyncStatus(), demo: false, state: "partial", imported: 2, processed: 3, total: 5, skipped: 1, errorCode: "imap_message_skipped" };
    const sync = vi.fn(async () => status);
    show({ sync, getSyncStatus: async () => status }); await ready();
    fireEvent.click(await screen.findByRole("button", { name: "Sync inbox" }));
    await screen.findByText("Sync finished with partial results. Saved messages are available.");
    expect(screen.getByText(/2 new · 3 processed · 1 skipped/)).toBeInTheDocument();
    expect(await ready()).toBeInTheDocument();
  });

  it("polls an existing running sync and refreshes when it finishes", async () => {
    const base = await fixtureAdapter.getSyncStatus();
    const listEmails = vi.fn(fixtureAdapter.listEmails);
    const getSyncStatus = vi.fn().mockResolvedValueOnce({ ...base, demo: false, state: "running", processed: 1, total: 2 }).mockResolvedValue({ ...base, demo: false, state: "succeeded", processed: 2, total: 2 });
    show({ listEmails, getSyncStatus }); await ready();
    expect(await screen.findByRole("button", { name: "Syncing…" })).toBeDisabled();
    await screen.findByRole("button", { name: "Sync inbox" }, { timeout: 2500 });
    await waitFor(() => expect(listEmails.mock.calls.filter(([query]) => query?.limit === 50).length).toBe(2));
    expect(getSyncStatus).toHaveBeenCalledTimes(2);
  });

  it("disables unavailable sync while keeping local messages accessible", async () => {
    show({ getSyncStatus: async () => ({ ...await fixtureAdapter.getSyncStatus(), available: false, demo: false }) });
    await ready(); expect(await screen.findByRole("button", { name: "Sync inbox" })).toBeDisabled();
    expect(screen.getByText(/IMAP is not configured. Stored messages remain available./)).toBeInTheDocument();
  });

  it("offers a sync status retry after an API failure", async () => {
    const getSyncStatus = vi.fn().mockRejectedValueOnce(new ApiError("api_unavailable")).mockImplementation(fixtureAdapter.getSyncStatus);
    show({ getSyncStatus }); await ready();
    fireEvent.click(await screen.findByRole("button", { name: "Check sync status" }));
    expect(await screen.findByRole("button", { name: "Sync demo" })).toBeEnabled();
  });

  it("retains a failed sync request warning after refreshing status and allows retry", async () => {
    show({ sync: async () => { throw new Error("offline"); } }); await ready();
    fireEvent.click(await screen.findByRole("button", { name: "Sync demo" }));
    await screen.findByText("The sync request could not be confirmed. Check the latest status before retrying. Saved messages are retained.");
    expect(await screen.findByRole("button", { name: "Sync demo" })).toBeEnabled();
    expect(await ready()).toBeInTheDocument();
  });

  it("renders ingested markup as text without remote images", async () => {
    const unsafe = '<img src="https://tracker.invalid/pixel" onerror="alert(1)">';
    show({ getEmail: async (id) => ({ ...await fixtureAdapter.getEmail(id), body: unsafe }) });
    await ready(); expect(await detail().findByText(unsafe)).toBeInTheDocument();
    expect(document.querySelector(".detail-body img")).toBeNull();
  });

  it("shows empty inbox and map states", async () => {
    show({ listEmails: async () => ({ items: [], total: 0, limit: 50, offset: 0 }), getCategoryStats: async () => ({ total: 0, categories: [] }) });
    expect(await screen.findByText("Your inbox is empty")).toBeInTheDocument();
    expect(screen.getByText("No messages yet. Sync to load the local inbox.")).toBeInTheDocument();
  });

  it("keeps messages available during aggregate loading and errors", async () => {
    const view = show({ getCategoryStats: () => new Promise(() => {}) }); await ready();
    expect(screen.getByText("Loading category counts…")).toBeInTheDocument(); view.unmount();
    show({ getCategoryStats: async () => { throw new Error("offline"); } }); await ready();
    expect(await screen.findByRole("button", { name: "Retry category counts" })).toBeInTheDocument();
    expect(screen.getByText("18 messages", { selector: "#result-count" })).toBeInTheDocument();
  });
});
