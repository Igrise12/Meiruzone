import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError, confirmedLabelsCsv, createHttpAdapter, fixtureAdapter, type EmailDetail, type InboxAdapter } from "../src/api";

afterEach(() => vi.unstubAllGlobals());

describe("HTTP inbox adapter", () => {
  it("rejects remote, credential-bearing and malformed API URLs", () => {
    for (const url of ["https://external.invalid/api/v1", "http://user:secret@localhost/api/v1", "invalid", "http://localhost/api/v1?token=secret"]) {
      expect(() => createHttpAdapter(url)).toThrow("The API URL must use a loopback host and /api/v1.");
    }
  });
  it("sends server filters and formats dates without accessing browser labels", async () => {
    const email = await fixtureAdapter.getEmail("m01");
    const transport = vi.fn<typeof fetch>(async () => new Response(JSON.stringify({ items: [email], total: 51, limit: 50, offset: 50 })));
    const api = createHttpAdapter("http://127.0.0.1:8000/api/v1", transport);
    const page = await api.listEmails({ category: "Unclassified", priority: "Low", needsReview: true, hasHumanLabel: true, q: "a & b", offset: 50, limit: 50 });
    const [url, options] = transport.mock.calls[0];
    expect(String(url)).toContain("category=Unclassified&priority=Low&needsReview=true&hasHumanLabel=true&q=a+%26+b&offset=50&limit=50");
    expect(options).toMatchObject({ credentials: "omit", cache: "no-store", redirect: "error" });
    expect(page.total).toBe(51); expect(page.items[0].received).not.toBe(email.received);
  });

  it("marks writes, sends partial fields only and retains server timestamps", async () => {
    const saved = { category: "Personal", priority: null, confirmedAt: "2026-10-05T01:00:00Z", source: "correction" };
    const transport = vi.fn<typeof fetch>(async () => new Response(JSON.stringify(saved)));
    const api = createHttpAdapter(undefined, transport);
    expect(await api.saveLabel("message_id", { category: "Personal", source: "correction" })).toEqual(saved);
    const [, options] = transport.mock.calls[0];
    expect(options).toMatchObject({ method: "PATCH", headers: { "Content-Type": "application/json", "X-Meiruzone-Request": "1" } });
    expect(JSON.parse(String(options?.body))).toEqual({ category: "Personal", source: "correction" });
    await api.sync("unread");
    expect(JSON.parse(String(transport.mock.calls[1][1]?.body))).toEqual({ mode: "unread", limit: 50 });
  });

  it("does not expose provider text from error responses", async () => {
    const transport = vi.fn<typeof fetch>(async () => new Response(JSON.stringify({ error: { code: "imap_auth_failed", message: "private-provider-secret" } }), { status: 503 }));
    const api = createHttpAdapter(undefined, transport);
    await expect(api.sync("recent")).rejects.toMatchObject({ code: "imap_auth_failed", message: "The local API request failed." });
    transport.mockImplementation(async () => new Response("private proxy error", { status: 502 }));
    await expect(api.listEmails()).rejects.toBeInstanceOf(ApiError);
  });

  it("reads model status from the local endpoint without replacing prediction metadata", async () => {
    const status = { ...await fixtureAdapter.getModelStatus(), state: "ready", modelVersion: "approved-run" };
    const transport = vi.fn<typeof fetch>(async () => new Response(JSON.stringify(status)));
    const api = createHttpAdapter(undefined, transport);
    expect(await api.getModelStatus()).toEqual(status);
    expect(transport.mock.calls[0][0]).toBe("http://127.0.0.1:8000/api/v1/model");
    const email = { ...await fixtureAdapter.getEmail("m01"), prediction: { priority: "High", categoryError: "inference_failed", reviewThreshold: null } };
    transport.mockImplementation(async () => new Response(JSON.stringify(email)));
    expect((await api.getEmail("m01")).prediction).toEqual(email.prediction);
  });
});

describe("confirmed label CSV", () => {
  it("exports every labeled page independently of UI filters and escapes formulas", async () => {
    const first = await fixtureAdapter.getEmail("m01");
    const emails: EmailDetail[] = Array.from({ length: 101 }, (_, index) => ({
      ...first, id: `export-${index}`, sender: index === 0 ? "=1+1" : first.sender, subject: index === 0 ? '\t@SUM(1,1)"' : first.subject,
      humanLabel: { category: index === 0 ? null : "Personal", priority: "Low", confirmedAt: "2026-10-05T01:00:00Z" },
    }));
    const listEmails = vi.fn<InboxAdapter["listEmails"]>(async (query = {}) => ({ items: emails.slice(query.offset ?? 0, (query.offset ?? 0) + 100), total: emails.length, limit: 100, offset: query.offset ?? 0 }));
    const { csv, count } = await confirmedLabelsCsv({ ...fixtureAdapter, listEmails });
    expect(count).toBe(101); expect(csv.split("\r\n")).toHaveLength(102);
    expect(csv).toContain('"\'=1+1"'); expect(csv).toContain('"\'\t@SUM(1,1)"""');
    expect(csv).toContain('"export-100"');
    expect(listEmails.mock.calls.map(([query]) => query)).toEqual([
      { hasHumanLabel: true, limit: 100, offset: 0 }, { hasHumanLabel: true, limit: 100, offset: 100 },
    ]);
  });

  it("fails instead of downloading an incomplete export", async () => {
    await expect(confirmedLabelsCsv({ ...fixtureAdapter, listEmails: async () => ({ items: [], total: 1, limit: 100, offset: 0 }) })).rejects.toMatchObject({ code: "export_incomplete" });
  });
});
