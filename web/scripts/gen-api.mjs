import { spawn } from "node:child_process";
import { existsSync } from "node:fs";
import { createServer } from "node:net";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const webRoot = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const repoRoot = resolve(webRoot, "..");
const output = resolve(webRoot, "src/api/schema.d.ts");

function pythonCommand() {
  const windows = resolve(repoRoot, ".venv/Scripts/python.exe");
  const unix = resolve(repoRoot, ".venv/bin/python");
  if (existsSync(windows)) return windows;
  if (existsSync(unix)) return unix;
  return "python";
}

function freePort() {
  return new Promise((resolvePort, reject) => {
    const server = createServer();
    server.once("error", reject);
    server.listen(0, "127.0.0.1", () => {
      const address = server.address();
      if (address == null || typeof address === "string") {
        reject(new Error("Could not bind a local port"));
        return;
      }
      const { port } = address;
      server.close(() => resolvePort(port));
    });
  });
}

function run(command, args, options) {
  return new Promise((resolveExit, reject) => {
    const child = spawn(command, args, options);
    child.once("error", reject);
    child.once("exit", (code) => resolveExit(code ?? 1));
  });
}

const port = await freePort();
const logs = [];
const api = spawn(
  pythonCommand(),
  ["-m", "uvicorn", "src.api.app:app", "--host", "127.0.0.1", "--port", String(port)],
  { cwd: repoRoot, stdio: ["ignore", "pipe", "pipe"] },
);
api.stdout.on("data", (chunk) => logs.push(chunk.toString()));
api.stderr.on("data", (chunk) => logs.push(chunk.toString()));

async function waitForOpenApi() {
  const url = `http://127.0.0.1:${port}/openapi.json`;
  for (let attempt = 0; attempt < 50; attempt += 1) {
    if (api.exitCode != null) break;
    try {
      const response = await fetch(url);
      if (response.ok) return url;
    } catch {
      // The server is still starting.
    }
    await new Promise((resolveDelay) => setTimeout(resolveDelay, 200));
  }
  throw new Error(`API did not start.\n${logs.join("")}`);
}

let exitCode = 1;
try {
  const url = await waitForOpenApi();
  const cli = resolve(webRoot, "node_modules/openapi-typescript/bin/cli.js");
  exitCode = await run(process.execPath, [cli, url, "-o", output], {
    cwd: webRoot,
    stdio: "inherit",
  });
} catch (error) {
  console.error(error instanceof Error ? error.message : error);
  exitCode = 1;
} finally {
  api.kill();
}

process.exit(exitCode);
