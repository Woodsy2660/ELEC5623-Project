import { existsSync, readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const webRoot = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const repoRoot = resolve(webRoot, "..");
let failed = false;

for (const name of ["tokens.css", "app.css"]) {
  const source = resolve(repoRoot, "design/styles", name);
  const copy = resolve(webRoot, "src/styles", name);
  if (!existsSync(copy)) {
    console.error(`${name} is missing from web/src/styles. Run npm run sync:ds.`);
    failed = true;
    continue;
  }
  if (!readFileSync(source).equals(readFileSync(copy))) {
    console.error(
      `${name} differs from design/styles/${name}. Run npm run sync:ds. Do not hand-edit the copy.`,
    );
    failed = true;
  }
}

if (failed) process.exit(1);
