import { execFile, spawn, type ChildProcess } from "node:child_process";
import { once } from "node:events";
import { mkdir, mkdtemp, readFile, readdir, rm } from "node:fs/promises";
import { createServer } from "node:net";
import { tmpdir } from "node:os";
import { resolve } from "node:path";
import process from "node:process";
import { setTimeout as delay } from "node:timers/promises";
import { promisify } from "node:util";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterAll, beforeAll, describe, expect, it } from "vitest";
import App from "../src/App";
import { confirmedLabelsCsv, createHttpAdapter } from "../src/api";

const suite = process.env.MEIRUZONE_INTEGRATION === "1" ? describe : describe.skip;
const execute = promisify(execFile);
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

  async function start(database = "inbox.sqlite3", phase?: string, modelDirectory?: string) {
    const env = Object.fromEntries(Object.entries(process.env).filter(([key]) => !key.startsWith("MEIRUZONE_")));
    const args = ["tests/http_fixture.py", resolve(directory, database), String(port)];
    if (phase) args.push("--phase", phase);
    if (modelDirectory) args.push("--model-directory", modelDirectory);
    child = spawn(resolve("../.venv/bin/python"), args, {
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
    expect(detail().getByRole("region", { name: "Original prediction" })).toHaveTextContent("Category confidence");
    expect(detail().getByText(`Model: ${model.modelVersion}`, { exact: false })).toBeInTheDocument();
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

  it("trains only HTTP-confirmed labels, explicitly activates replacements, and retains original predictions", async () => {
    cleanup(); await stop();
    await start("workflow.sqlite3", "training");
    const database = resolve(directory, "workflow.sqlite3");
    const models = resolve(directory, "workflow-models");
    await mkdir(models, { mode: 0o700 });
    expect((await api.getModelStatus()).state).toBe("unconfigured");
    expect((await api.sync("recent")).imported).toBe(40);
    const rows = (await api.listEmails()).items;
    expect(rows).toHaveLength(40);
    expect(rows.every((row) => row.prediction?.category === null && row.prediction?.categoryError === "model_unavailable")).toBe(true);
    expect((await api.getCategoryStats()).categories.find((row) => row.category === "Unclassified")?.count).toBe(40);
    expect((await api.sync("unread"))).toMatchObject({ imported: 0, processed: 20 });
    expect((await api.listEmails()).items.map((row) => [row.id, row.read])).toEqual(rows.map((row) => [row.id, row.read]));
    for (const row of rows) {
      await api.saveLabel(row.id, { category: row.subject.startsWith("Recruitment") ? "Recruitment" : "Spam", source: "manual" });
    }
    const env = Object.fromEntries(Object.entries(process.env).filter(([key]) => !key.startsWith("MEIRUZONE_")));
    async function train() {
      const before = await readFile(database);
      const previous = await readdir(models);
      await execute(resolve("../.venv/bin/python"), ["-m", "app.train", "--database", database, "--output-dir", models], { cwd: resolve(".."), env });
      expect(await readFile(database)).toEqual(before);
      const runs = (await readdir(models)).filter((run) => !previous.includes(run));
      expect(runs).toHaveLength(1);
      const [run] = runs;
      return { path: resolve(models, run), report: JSON.parse(await readFile(resolve(models, run, "evaluation.json"), "utf8")) };
    }
    async function checkTotals() {
      const { stdout } = await execute(resolve("../.venv/bin/python"), ["-c", [
        "import json, sqlite3, sys",
        "connection = sqlite3.connect('file:' + sys.argv[1] + '?mode=ro', uri=True)",
        "print(json.dumps(dict(connection.execute(\"SELECT COALESCE(h.category, p.category, 'Unclassified'), COUNT(*) FROM emails e LEFT JOIN human_labels h ON h.email_id = e.id LEFT JOIN predictions p ON p.email_id = e.id GROUP BY 1\"))))",
      ].join("\n"), database], { env });
      const stats = await api.getCategoryStats();
      expect(Object.fromEntries(stats.categories.filter((row) => row.count).map((row) => [row.category, row.count]))).toEqual(JSON.parse(stdout));
      expect(stats.categories.reduce((total, row) => total + row.count, 0)).toBe(stats.total);
      const filtered = await api.listEmails({ category: "Spam", limit: 1, offset: 1 });
      expect(filtered.items).toHaveLength(1);
      expect(await api.getCategoryStats()).toEqual(stats);
    }
    await checkTotals();
    const first = await train();
    expect(first.report.supported_classes).toEqual(["Recruitment", "Spam"]);
    expect(first.report.data.raw_examples).toBe(40);
    expect(first.report.test.confusion_matrix).toHaveLength(2);
    expect(first.report.test.macro_f1).toBeGreaterThanOrEqual(0);
    expect(first.report.test.macro_f1).toBeLessThanOrEqual(1);
    expect((await api.getModelStatus()).state).toBe("unconfigured");
    const artifact = await readFile(resolve(first.path, "model.joblib"));
    await stop(); await start("workflow.sqlite3", "prediction", first.path);
    const active = await api.getModelStatus();
    expect(active.modelVersion).toBe(first.report.model_version);
    expect(active.evaluation?.macroF1).toBe(first.report.test.macro_f1);
    expect(active.evaluation?.confusionMatrix).toEqual(first.report.test.confusion_matrix);
    expect(active.evaluation?.perClass.map((row) => row.category)).toEqual(first.report.supported_classes);
    expect((await api.sync("recent")).imported).toBe(2);
    const predicted = (await api.listEmails({ q: "Synthetic message" })).items;
    const recruitment = predicted.find((row) => row.prediction?.category === "Recruitment")!;
    expect(recruitment.prediction).toMatchObject({ modelVersion: first.report.model_version, priority: "Medium", categoryError: null });
    const view = render(<App adapter={api} />);
    fireEvent.click(await screen.findByRole("button", { name: /Recruitment 21 50%/ }));
    fireEvent.click(await screen.findByRole("button", { name: /Example.*Synthetic message/ }));
    const detail = within(screen.getByRole("article", { name: "Selected email" }));
    expect(await detail.findByText(/Recruitment Recruitment <img/)).toBeInTheDocument();
    expect(document.querySelector(".detail-body img")).toBeNull();
    fireEvent.change(detail.getByLabelText("Category"), { target: { value: "Spam" } });
    fireEvent.change(detail.getByLabelText("Priority"), { target: { value: "Low" } });
    fireEvent.click(detail.getByRole("button", { name: "Confirm labels" }));
    await waitFor(() => expect(within(screen.getByLabelText("Category counts")).getByRole("button", { name: /Spam 22 52%/ })).toBeInTheDocument());
    const corrected = await api.getEmail(recruitment.id);
    expect(corrected.humanLabel).toMatchObject({ category: "Spam", priority: "Low", source: "correction" });
    expect(corrected.prediction).toEqual(recruitment.prediction);
    expect(corrected.needsReview).toBe(false);
    await checkTotals();
    view.unmount();
    const replacement = await train();
    expect(replacement.report.data.raw_examples).toBe(41);
    expect(replacement.path).not.toBe(first.path);
    expect(await readFile(resolve(first.path, "model.joblib"))).toEqual(artifact);
    expect((await api.getModelStatus()).modelVersion).toBe(first.report.model_version);
    await stop(); await start("workflow.sqlite3", "replacement", replacement.path);
    expect((await api.getModelStatus()).modelVersion).toBe(replacement.report.model_version);
    expect((await api.sync("recent")).imported).toBe(1);
    expect((await api.getEmail(recruitment.id)).humanLabel).toEqual(corrected.humanLabel);
    expect((await api.getEmail(recruitment.id)).prediction).toEqual(recruitment.prediction);
    expect((await api.listEmails()).items.filter((row) => row.prediction?.modelVersion === replacement.report.model_version)).toHaveLength(1);
    expect((await api.listEmails({ hasHumanLabel: true })).total).toBe(41);
    console.info(`Synthetic acceptance: ${first.report.data.raw_examples} labels → ${replacement.report.data.raw_examples} labels; Recruitment/Spam macro F1 ${first.report.test.macro_f1} → ${replacement.report.test.macro_f1}.`);
    await checkTotals();
  }, 30000);
});
