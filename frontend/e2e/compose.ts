import { execFile } from "node:child_process";
import { mkdtemp, mkdir, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { createServer } from "node:net";
import { resolve } from "node:path";
import process from "node:process";
import { promisify } from "node:util";
import { expect, test } from "@playwright/test";

const execute = promisify(execFile);
const root = resolve(import.meta.dirname, "../..");
let directory: string;
let environment: NodeJS.ProcessEnv;
let configuration: string;
let apiPort: number;
let frontendPort: number;

async function freePort() {
  const server = createServer();
  await new Promise<void>((done) => server.listen(0, "127.0.0.1", done));
  const address = server.address();
  if (!address || typeof address === "string") throw new Error("A loopback port is required.");
  await new Promise<void>((done, reject) => server.close((error) => error ? reject(error) : done()));
  return address.port;
}

async function compose(...args: string[]) {
  const { stdout } = await execute("docker", [
    "compose", "--env-file", configuration, "--project-name", `meiruzone-test-${process.pid}`,
    "--file", resolve(root, "compose.yaml"), ...args,
  ], { cwd: root, env: environment, maxBuffer: 16 * 1024 * 1024 });
  return stdout.trim();
}

test.beforeAll(async () => {
  test.setTimeout(300_000);
  [apiPort, frontendPort] = await Promise.all([freePort(), freePort()]);
  directory = await mkdtemp(resolve(tmpdir(), "meiruzone-compose-"));
  await mkdir(resolve(directory, "data"), { mode: 0o700 });
  await mkdir(resolve(directory, "models"), { mode: 0o700 });
  configuration = resolve(directory, "backend.env");
  await writeFile(configuration, `MEIRUZONE_DEMO=false\nMEIRUZONE_FRONTEND_ORIGINS=http://localhost:${frontendPort},http://127.0.0.1:${frontendPort}\n`, { mode: 0o600 });
  environment = {
    ...Object.fromEntries(Object.entries(process.env).filter(([key]) => !key.startsWith("MEIRUZONE_"))),
    MEIRUZONE_ENV_FILE: configuration,
    MEIRUZONE_DATA_DIRECTORY: resolve(directory, "data"),
    MEIRUZONE_MODELS_DIRECTORY: resolve(directory, "models"),
    MEIRUZONE_UID: String(process.getuid!()),
    MEIRUZONE_GID: String(process.getgid!()),
    MEIRUZONE_API_PORT: String(apiPort),
    MEIRUZONE_FRONTEND_PORT: String(frontendPort),
  };
  await compose("config", "--quiet");
  await compose("build", "--pull");
  await compose("up", "--detach", "--wait", "--wait-timeout", "90");
});

test.afterAll(async () => {
  try { if (configuration) await compose("down", "--volumes", "--remove-orphans"); }
  finally { if (directory) await rm(directory, { recursive: true, force: true }); }
});

test("built app retains corrections and predictions after container recreation", async ({ page, request }) => {
  const api = `http://127.0.0.1:${apiPort}/api/v1`;
  expect((await request.get(`${api}/emails`)).ok()).toBe(true);
  expect((await (await request.get(`${api}/emails`)).json()).total).toBe(0);
  expect((await (await request.get(`${api}/sync`)).json()).available).toBe(false);
  await page.goto(`http://127.0.0.1:${frontendPort}`);
  await expect(page.getByText("Your inbox is empty")).toBeVisible();

  for (const [service, port] of [["backend", "8000/tcp"], ["frontend", "8080/tcp"]]) {
    const id = await compose("ps", "--quiet", service);
    const { stdout } = await execute("docker", ["inspect", id], { env: environment });
    const [container] = JSON.parse(stdout);
    expect(container.HostConfig.PortBindings[port][0].HostIp).toBe("127.0.0.1");
    expect(container.HostConfig.PortBindings[port][0].HostPort).toBe(String(service === "backend" ? apiPort : frontendPort));
    expect(container.Config.User).not.toMatch(/^0(?::|$)|^root(?::|$)/);
    if (service === "backend") {
      expect(container.Mounts.find((mount: { Destination: string }) => mount.Destination === "/app/models").RW).toBe(false);
    }
  }
  await compose("exec", "-T", "backend", "python", "-c", [
    "import errno, importlib.util, os; from pathlib import Path",
    `assert os.getuid() == ${process.getuid!()} != 0`,
    "assert Path('/app/data/meiruzone.sqlite3').stat().st_mode & 0o777 == 0o600",
    "assert all(p.suffix == '.py' for p in Path('/app').rglob('*') if p.is_file() and '/data/' not in str(p))",
    "assert all(importlib.util.find_spec(name) is None for name in ('ruff', 'mypy', 'pip_audit', 'ipykernel'))",
    "try:\n Path('/app/models/write-probe').write_text('synthetic')\nexcept OSError as error:\n assert error.errno == errno.EROFS\nelse:\n raise AssertionError('Models must be read-only')",
  ].join("\n"));

  await writeFile(configuration, `MEIRUZONE_DEMO=true\nMEIRUZONE_FRONTEND_ORIGINS=http://localhost:${frontendPort},http://127.0.0.1:${frontendPort}\n`, { mode: 0o600 });
  await compose("up", "--detach", "--force-recreate", "--wait", "--wait-timeout", "90");
  await page.reload();
  await page.getByRole("button", { name: /Example Recruitment.*Synthetic Recruitment/ }).click();
  const detail = page.getByRole("article", { name: "Selected email" });
  await expect(detail.getByRole("region", { name: "Original prediction" })).toContainText("Recruitment");
  await expect(detail.getByRole("region", { name: "Original prediction" })).toContainText("Category confidence 61%");
  const original = (await (await request.get(`${api}/emails/demo-01`)).json()).prediction;
  await detail.getByLabel("Category", { exact: true }).selectOption("Personal");
  await detail.getByRole("button", { name: "Confirm labels" }).click();
  await expect(page.getByText("Your labels are saved on this device.")).toBeVisible();

  // Exercise the documented writable one-off model mount using synthetic labels.
  await compose("run", "--rm", "--no-deps", "--volume", `${environment.MEIRUZONE_MODELS_DIRECTORY}:/app/models:rw`,
    "backend", "python", "-c", [
      "from pathlib import Path; from app.database import Repository; from app.train import main",
      "repository = Repository(Path('data/meiruzone.sqlite3'))",
      "rows = [(f'delivery-{category}-{index}', category, f'{category.lower()}@example.test', f'{category} unique{index}', f'{category} {category} content{index}', '2026-01-01T00:00:00Z', 0, 0) for category in ('Recruitment', 'Spam') for index in range(20)]",
      "with repository.connect() as connection:\n connection.executemany('INSERT INTO emails VALUES (?, ?, ?, ?, ?, ?, ?, ?)', rows)\n connection.executemany('INSERT INTO human_labels VALUES (?, ?, ?, ?, ?)', [(row[0], row[1], None, row[5], 'manual') for row in rows])",
      "assert main([]) == 0",
    ].join("\n"));

  await compose("up", "--detach", "--force-recreate", "--wait", "--wait-timeout", "90");
  await page.reload();
  await page.getByRole("button", { name: /Example Recruitment.*Synthetic Recruitment/ }).click();
  await expect(detail.getByLabel("Category", { exact: true })).toHaveValue("Personal");
  const saved = await (await request.get(`${api}/emails/demo-01`)).json();
  expect(saved.humanLabel).toMatchObject({ category: "Personal", source: "correction" });
  expect(saved.prediction).toEqual(original);
  await compose("exec", "-T", "backend", "python", "-c", [
    "from pathlib import Path; from app.ml import load_model, predict_category",
    "runs = list(Path('models').glob('category-*')); assert len(runs) == 1",
    "assert runs[0].stat().st_mode & 0o777 == 0o700",
    "assert all((runs[0] / name).stat().st_mode & 0o777 == 0o600 for name in ('model.joblib', 'evaluation.json'))",
    "prediction = predict_category(load_model(runs[0]), {'subject': 'Recruitment synthetic interview'})",
    "assert prediction.category in ('Recruitment', 'Spam') and 0 <= prediction.confidence <= 100",
  ].join("\n"));
  expect((await request.get(`${api}/emails`, { headers: { Origin: "https://untrusted.invalid" } })).status()).toBe(403);
});
