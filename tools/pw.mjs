// Load Playwright from the project, or fall back to a globally installed copy.
import { createRequire } from "node:module";
import { execSync } from "node:child_process";
import path from "node:path";

export function loadPlaywright() {
  const require = createRequire(import.meta.url);
  try {
    return require("playwright");
  } catch {
    const globalRoot = execSync("npm root -g").toString().trim();
    return require(path.join(globalRoot, "playwright"));
  }
}
