import { copyFileSync, mkdirSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const webRoot = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const repoRoot = resolve(webRoot, "..");
const destination = resolve(webRoot, "src/styles");
mkdirSync(destination, { recursive: true });

for (const name of ["tokens.css", "app.css"]) {
  copyFileSync(resolve(repoRoot, "design/styles", name), resolve(destination, name));
}
