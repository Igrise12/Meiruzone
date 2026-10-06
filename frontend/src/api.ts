import { categories, initialLabels, priorities, sampleEmails, type Category, type CategoryFilter, type CategoryStat, type Email, type HumanLabel, type LabelsById, type Priority } from "./data";
import { categoryStats } from "./treemap";

export type EmailSummary = Omit<Email, "body"> & { receivedAt: string; humanLabel: HumanLabel | null; needsReview: boolean };
export type EmailDetail = EmailSummary & { body: string };
export type EmailQuery = { q?: string; category?: Exclude<CategoryFilter, "All">; priority?: Priority; needsReview?: boolean; hasHumanLabel?: boolean; limit?: number; offset?: number };
export type EmailPage = { items: EmailSummary[]; total: number; limit: number; offset: number };
export type CategoryStats = { total: number; categories: CategoryStat[] };
export type LabelPatch = { category?: Category; priority?: Priority; source: "manual" | "correction" };
export type ModelStatus = {
  state: "ready" | "unconfigured" | "invalid" | "demo";
  modelVersion: string | null; supportedCategories: Category[];
  reviewThreshold: number | null; thresholdOverridden: boolean;
  evaluation: {
    macroF1: number; perClass: { category: Category; precision: number; recall: number; f1: number }[];
    confusionMatrix: number[][];
  } | null;
};
export type SyncStatus = {
  available: boolean; demo: boolean; state: "idle" | "running" | "succeeded" | "partial" | "failed" | "unavailable";
  startedAt: string | null; completedAt: string | null; imported: number; processed: number; total: number; skipped: number; errorCode: string | null;
};
export type InboxAdapter = {
  listEmails(query?: EmailQuery, signal?: AbortSignal): Promise<EmailPage>;
  getEmail(id: string, signal?: AbortSignal): Promise<EmailDetail>;
  getCategoryStats(signal?: AbortSignal): Promise<CategoryStats>;
  saveLabel(id: string, patch: LabelPatch): Promise<HumanLabel>;
  getSyncStatus(signal?: AbortSignal): Promise<SyncStatus>;
  getModelStatus(signal?: AbortSignal): Promise<ModelStatus>;
  sync(mode: "recent" | "unread"): Promise<SyncStatus>;
};

export class ApiError extends Error {
  constructor(readonly code: string) { super("The local API request failed."); }
}

export function receivedText(value: string): string {
  return new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" }).format(new Date(value));
}

export function createHttpAdapter(baseUrl = "http://127.0.0.1:8001/api/v1", transport: typeof fetch = (...args) => fetch(...args)): InboxAdapter {
  baseUrl = baseUrl.replace(/\/$/, "");
  let address: URL;
  try { address = new URL(baseUrl); }
  catch { throw new Error("The API URL must use a loopback host and /api/v1."); }
  if (!["http:", "https:"].includes(address.protocol) || !["localhost", "127.0.0.1", "[::1]"].includes(address.hostname) ||
      address.pathname !== "/api/v1" || address.username || address.password || address.search || address.hash) {
    throw new Error("The API URL must use a loopback host and /api/v1.");
  }
  async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
    const response = await transport(`${baseUrl}${path}`, { credentials: "omit", cache: "no-store", redirect: "error", ...options });
    if (!response.ok) {
      const body = await response.json().catch(() => null);
      throw new ApiError(typeof body?.error?.code === "string" ? body.error.code : "api_unavailable");
    }
    return response.json();
  }
  const write = (method: string, body: unknown): RequestInit => ({
    method, headers: { "Content-Type": "application/json", "X-Meiruzone-Request": "1" }, body: JSON.stringify(body),
  });
  return {
    async listEmails(query = {}, signal) {
      const params = new URLSearchParams();
      Object.entries(query).forEach(([key, value]) => { if (value !== undefined) params.set(key, String(value)); });
      const page = await request<EmailPage>(`/emails?${params}`, { signal });
      return { ...page, items: page.items.map((email) => ({ ...email, received: receivedText(email.receivedAt) })) };
    },
    async getEmail(id, signal) {
      const email = await request<EmailDetail>(`/emails/${encodeURIComponent(id)}`, { signal });
      return { ...email, received: receivedText(email.receivedAt) };
    },
    getCategoryStats: (signal) => request("/category-stats", { signal }),
    saveLabel: (id, patch) => request(`/emails/${encodeURIComponent(id)}/labels`, write("PATCH", patch)),
    getSyncStatus: (signal) => request("/sync", { signal }),
    getModelStatus: (signal) => request("/model", { signal }),
    sync: (mode) => request("/sync", write("POST", { mode, limit: 50 })),
  };
}

const storageKey = "meiruzo-confirmed-labels-v1";
function readLabels(): LabelsById {
  try {
    const value: unknown = JSON.parse(localStorage.getItem(storageKey) || "{}");
    if (!value || typeof value !== "object" || Array.isArray(value)) return { ...initialLabels };
    const valid: LabelsById = {};
    for (const [id, label] of Object.entries(value)) {
      if (!sampleEmails.some((email) => email.id === id) || !label || typeof label !== "object") continue;
      if ((label.category === null || categories.includes(label.category)) &&
          (label.priority === null || priorities.includes(label.priority)) &&
          (label.category !== null || label.priority !== null) && typeof label.confirmedAt === "string") {
        valid[id] = { category: label.category, priority: label.priority, confirmedAt: label.confirmedAt, source: label.source === "correction" ? "correction" : "manual" };
      }
    }
    return { ...initialLabels, ...valid };
  } catch { return { ...initialLabels }; }
}

function fixtureEmails(): EmailDetail[] {
  const labels = readLabels();
  return sampleEmails.map((email, index) => {
    const humanLabel = labels[email.id] ?? null;
    const receivedAt = new Date(Date.UTC(2026, 9, 5, 12) - index * 3600000).toISOString();
    return { ...email, receivedAt, humanLabel, needsReview: Boolean(
      !humanLabel?.category && email.prediction?.category && email.prediction.confidence != null && email.prediction.confidence < 70,
    ) };
  });
}
const demoStatus = (): SyncStatus => ({ available: true, demo: true, state: "idle", startedAt: null, completedAt: null, imported: 0, processed: 0, total: 0, skipped: 0, errorCode: null });
let fixtureSync = demoStatus();
export const fixtureAdapter: InboxAdapter = {
  async listEmails(query = {}) {
    const { limit = 50, offset = 0 } = query;
    const text = query.q?.trim().toLocaleLowerCase() ?? "";
    const emails = fixtureEmails().filter((email) => {
      const category = email.humanLabel?.category ?? email.prediction?.category ?? "Unclassified";
      const priority = priorityOf(email);
      return (!query.category || category === query.category) && (!query.priority || priority === query.priority) &&
        (!query.needsReview || email.needsReview) && (!query.hasHumanLabel || email.humanLabel !== null) &&
        (!text || [email.sender, email.address, email.subject, email.body, category, priority].join(" ").toLocaleLowerCase().includes(text));
    });
    return { items: emails.slice(offset, offset + limit).map(({ body: _body, ...email }) => { void _body; return email; }), total: emails.length, limit, offset };
  },
  async getEmail(id) {
    const email = fixtureEmails().find((email) => email.id === id);
    if (!email) throw new ApiError("email_not_found");
    return email;
  },
  async getCategoryStats() { return { total: sampleEmails.length, categories: categoryStats(sampleEmails, readLabels()) }; },
  async saveLabel(id, patch) {
    if (!sampleEmails.some((email) => email.id === id)) throw new ApiError("email_not_found");
    const labels = readLabels();
    const label = { category: labels[id]?.category ?? null, priority: labels[id]?.priority ?? null, ...patch, confirmedAt: new Date().toISOString() };
    labels[id] = label;
    localStorage.setItem(storageKey, JSON.stringify(labels));
    return label;
  },
  async getSyncStatus() { return { ...fixtureSync }; },
  async getModelStatus() {
    return { state: "demo", modelVersion: null, supportedCategories: [], reviewThreshold: null, thresholdOverridden: false, evaluation: null };
  },
  async sync() {
    const now = new Date().toISOString();
    fixtureSync = { ...demoStatus(), state: "succeeded", startedAt: now, completedAt: now };
    return { ...fixtureSync };
  },
};

export function priorityOf(email: EmailSummary): Priority | undefined {
  return email.humanLabel?.priority ?? email.prediction?.priority ?? undefined;
}

export async function confirmedLabelsCsv(adapter: InboxAdapter): Promise<{ csv: string; count: number }> {
  const rows: string[][] = [["message_id", "sender", "subject", "predicted_category", "predicted_priority", "confidence", "confirmed_category", "confirmed_priority", "confirmed_at"]];
  // ponytail: ordered pages are not a snapshot; add a snapshot export if concurrent imports require one.
  let offset = 0;
  while (true) {
    if (offset > 1_000_000) throw new ApiError("export_too_large");
    const page = await adapter.listEmails({ hasHumanLabel: true, limit: 100, offset });
    for (const email of page.items) {
      const label = email.humanLabel;
      if (!label) continue;
      rows.push([email.id, email.sender, email.subject, email.prediction?.category ?? "", email.prediction?.priority ?? "", String(email.prediction?.confidence ?? ""), label.category ?? "", label.priority ?? "", label.confirmedAt]);
    }
    offset += page.items.length;
    if (offset >= page.total) break;
    if (!page.items.length) throw new ApiError("export_incomplete");
  }
  const cell = (value: string) => `"${(/^[\s]*[=+\-@]|^[\t\r\n]/u.test(value) ? "'" + value : value).replaceAll('"', '""')}"`;
  return { csv: rows.map((row) => row.map(cell).join(",")).join("\r\n"), count: rows.length - 1 };
}
