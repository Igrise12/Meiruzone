import { spawn, type ChildProcess } from "node:child_process";
import { once } from "node:events";
import { mkdtemp, rm } from "node:fs/promises";
import { createServer } from "node:net";
import { tmpdir } from "node:os";
import { resolve } from "node:path";
import process from "node:process";
import { setTimeout as delay } from "node:timers/promises";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterAll, beforeAll, describe, expect, it } from "vitest";
import App from "../src/App";
import { confirmedLabelsCsv, createHttpAdapter } from "../src/api";

const suite = process.env.MEIRUZONE_INTEGRATION === "1" ? describe : describe.skip;
suite("Smart Inbox against a real loopback API", () => {
  let directory: string;
  let child: ChildProcess | undefined;
  let port: number;
  const origin = "http://localhost:5173";
  const api = createHttpAdapter("http://127.0.0.1:0/api/v1", async (url, options) => {
    const headers = new Headers(options?.headers);
    headers.set("Origin", origin);
    return fetch(String(url).replace(":0/", `:${port}/`), { ...options, headers });
  });

  async function start() {
    const env = Object.fromEntries(Object.entries(process.env).filter(([key]) => !key.startsWith("MEIRUZONE_")));
    child = spawn(resolve("../.venv/bin/python"), ["tests/http_fixture.py", resolve(directory, "inbox.sqlite3"), String(port)], {
      cwd: resolve(".."), env: { ...env, PYTHONPATH: `${resolve("..")}:${resolve("../tests")}` }, stdio: "ignore",
    });
    for (let attempt = 0; attempt < 100; attempt++) {
      if (child.exitCode !== null) throw new Error("Synthetic integration backend exited during startup.");
      try { await api.getSyncStatus(); return; } catch { await delay(50); }
    }
    throw new Error("Synthetic integration backend did not become ready.");
  }
  async function stop() {
    if (!child || child.exitCode !== null) return;
    const stopped = once(child, "exit");
    child.kill("SIGTERM");
    const timer = globalThis.setTimeout(() => child?.kill("SIGKILL"), 3000);
    try { await stopped; } finally { globalThis.clearTimeout(timer); child = undefined; }
  }

  beforeAll(async () => {
    directory = await mkdtemp(resolve(tmpdir(), "meiruzone-integration-"));
    const reservation = createServer();
    reservation.listen(0, "127.0.0.1"); await once(reservation, "listening");
    const address = reservation.address();
    if (!address || typeof address === "string") throw new Error("A loopback test port is required.");
    port = address.port;
    await new Promise<void>((done) => reservation.close(() => done()));
    await start();
  }, 15000);
  afterAll(async () => { cleanup(); await stop(); if (directory) await rm(directory, { recursive: true, force: true }); });

  it("ingests safely, corrects a prediction, refreshes aggregates and retains labels across reload/restart", async () => {
    const synced = await api.sync("recent"); expect(synced.imported).toBe(1);
    const model = await api.getModelStatus(); expect(model.state).toBe("ready");
    expect(model.supportedCategories).toEqual(["Recruitment", "Spam"]);
    const before = await api.getCategoryStats(); expect(before.total).toBe(11);
    const ingested = (await api.listEmails({ q: "Synthetic message" })).items[0];
    expect(ingested.prediction).toMatchObject({ modelVersion: model.modelVersion, categoryError: null, priority: "Medium" });
    expect(model.supportedCategories).toContain(ingested.prediction?.category);
    expect(ingested.prediction?.confidence).toBeGreaterThanOrEqual(0);
    expect(ingested.prediction?.reviewThreshold).toBe(model.reviewThreshold);
    expect(ingested).not.toHaveProperty("body");
    expect(Object.keys(ingested).sort()).toEqual(["address", "hasAttachments", "humanLabel", "id", "needsReview", "prediction", "read", "received", "receivedAt", "sender", "subject"].sort());
    const view = render(<App adapter={api} />);
    fireEvent.click(await screen.findByRole("button", { name: /Example.*Synthetic message/ }));
    const detail = () => within(screen.getByRole("article", { name: "Selected email" }));
    expect(await detail().findByText('<img src="https://tracker.invalid/pixel" onerror="alert(1)">')).toBeInTheDocument();
    expect(document.querySelector(".detail-body img")).toBeNull();
    fireEvent.change(detail().getByLabelText("Category"), { target: { value: "Personal" } });
    fireEvent.click(screen.getByRole("button", { name: "Confirm labels" }));
    await waitFor(async () => expect((await api.getEmail(ingested.id)).humanLabel?.category).toBe("Personal"));
    await waitFor(() => expect(within(screen.getByLabelText("Category counts")).getByRole("button", { name: /Personal 3 27%/ })).toBeInTheDocument());
    expect((await api.getEmail(ingested.id)).prediction).toEqual(ingested.prediction);
    fireEvent.change(screen.getByRole("searchbox"), { target: { value: "Recruitment" } });
    fireEvent.click(await screen.findByRole("button", { name: /Example Recruitment.*Synthetic Recruitment/ }));
    fireEvent.change(await detail().findByLabelText("Category"), { target: { value: "Personal" } });
    fireEvent.click(screen.getByRole("button", { name: "Confirm labels" }));
    await screen.findByText("Your labels are saved on this device.");
    await waitFor(() => expect(within(screen.getByLabelText("Category counts")).getByRole("button", { name: /Personal 4 36%/ })).toBeInTheDocument());
    const corrected = await api.getEmail("demo-01");
    expect(corrected.humanLabel).toMatchObject({ category: "Personal", priority: null, source: "correction" });
    expect(corrected.prediction?.category).toBe("Recruitment"); expect(corrected.needsReview).toBe(false);
    expect((await api.getCategoryStats()).total).toBe(before.total);
    view.unmount(); await stop(); await start();
    expect((await api.getEmail("demo-01")).humanLabel).toEqual(corrected.humanLabel);
    expect((await api.getEmail(ingested.id)).humanLabel?.category).toBe("Personal");
    expect((await api.getModelStatus()).modelVersion).toBe(model.modelVersion);
    render(<App adapter={api} />);
    fireEvent.click(await screen.findByRole("button", { name: /Example Recruitment.*Synthetic Recruitment/ }));
    expect(await detail().findByLabelText("Category")).toHaveValue("Personal");
    expect(detail().getByLabelText("Priority")).toHaveValue("");
    const exported = await confirmedLabelsCsv(api); expect(exported.count).toBe(3);
    expect(exported.csv).toContain('"Recruitment","High","61","Personal",""');
    const forbidden = await fetch(`http://127.0.0.1:${port}/api/v1/emails/demo-01/labels`, {
      method: "PATCH", headers: { Origin: "https://untrusted.invalid", "Content-Type": "application/json", "X-Meiruzone-Request": "1" }, body: JSON.stringify({ category: "Spam" }),
    });
    expect(forbidden.status).toBe(403);
    expect((await api.getEmail("demo-01")).humanLabel).toEqual(corrected.humanLabel);
  }, 20000);
});
