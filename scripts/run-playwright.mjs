#!/usr/bin/env node
/**
 * Runs Playwright with whatever local installation is available, so the project does not
 * need to vendor a second copy:
 *
 *   1. PLAYWRIGHT_CLI (explicit override)
 *   2. frontend/node_modules (pnpm/npm install)
 *   3. global npm root
 *   4. npm/npx cache (_npx) — the common case when Playwright was only ever run via npx
 *
 * The chosen package directory is also exported as NODE_PATH so tests can `import` from
 * "playwright/test". Chromium is installed on demand if no browser build is present.
 */
import { execFileSync, spawn } from "node:child_process";
import { existsSync, readdirSync, readFileSync, realpathSync, symlinkSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

const scriptDir = path.dirname(fileURLToPath(import.meta.url));
const repoRoot = path.resolve(scriptDir, "..");
const frontendDir = path.join(repoRoot, "frontend");

function versionOf(cliPath) {
  try {
    const packageFile = path.join(path.dirname(cliPath), "package.json");
    return JSON.parse(readFileSync(packageFile, "utf8")).version ?? "0.0.0";
  } catch {
    return "0.0.0";
  }
}

function compareVersions(a, b) {
  const left = a.split(".").map(Number);
  const right = b.split(".").map(Number);
  for (let index = 0; index < Math.max(left.length, right.length); index += 1) {
    const diff = (left[index] ?? 0) - (right[index] ?? 0);
    if (diff !== 0) return diff;
  }
  return 0;
}

function collectCandidates() {
  const candidates = [];
  const push = (cliPath) => {
    if (cliPath && existsSync(cliPath)) candidates.push(path.resolve(cliPath));
  };

  push(process.env.PLAYWRIGHT_CLI);
  push(path.join(frontendDir, "node_modules", "playwright", "cli.js"));
  push(path.join(frontendDir, "node_modules", "@playwright", "test", "cli.js"));

  try {
    const npmRoot = execFileSync(
      process.platform === "win32" ? "npm.cmd" : "npm",
      ["root", "-g"],
      { encoding: "utf8", stdio: ["ignore", "pipe", "ignore"] },
    ).trim();
    push(path.join(npmRoot, "playwright", "cli.js"));
    push(path.join(npmRoot, "@playwright", "test", "cli.js"));
  } catch {
    // npm is optional; ignore.
  }

  const npxCaches =
    process.platform === "win32"
      ? [path.join(process.env.LOCALAPPDATA ?? "", "npm-cache", "_npx")]
      : [path.join(os.homedir(), ".npm", "_npx")];
  for (const cache of npxCaches) {
    if (!existsSync(cache)) continue;
    for (const entry of readdirSync(cache)) {
      push(path.join(cache, entry, "node_modules", "playwright", "cli.js"));
      push(path.join(cache, entry, "node_modules", "@playwright", "test", "cli.js"));
    }
  }

  return [...new Set(candidates)];
}

/** Prefer stable releases; never pick a nightly/alpha over an installed stable copy. */
function rankCandidates(candidates) {
  return candidates
    .map((cliPath) => {
      const version = versionOf(cliPath);
      return { cliPath, version, prerelease: version.includes("-") };
    })
    .sort((left, right) => {
      if (left.prerelease !== right.prerelease) return left.prerelease ? 1 : -1;
      return compareVersions(right.version, left.version);
    });
}

/**
 * Node's ESM resolver ignores NODE_PATH, and this package is `"type": "module"`, so the
 * Playwright test runner needs a real node_modules entry for `import ... from "playwright/test"`.
 * A junction to the discovered package reuses the local install without downloading anything.
 */
function ensureModuleLink(packageDir) {
  const linkPath = path.join(frontendDir, "node_modules", "playwright");
  try {
    if (existsSync(linkPath)) {
      const resolved = realpathSync(linkPath);
      if (resolved === realpathSync(packageDir)) return;
      return; // A real installation already wins; nothing to do.
    }
    if (!existsSync(path.dirname(linkPath))) return;
    symlinkSync(packageDir, linkPath, process.platform === "win32" ? "junction" : "dir");
    console.error(`[playwright] linked ${packageDir} -> ${linkPath}`);
  } catch (error) {
    console.error(`[playwright] could not link local install: ${error.message}`);
  }
}


function hasChromium() {
  const root =
    process.env.PLAYWRIGHT_BROWSERS_PATH ??
    (process.platform === "win32"
      ? path.join(process.env.LOCALAPPDATA ?? "", "ms-playwright")
      : process.platform === "darwin"
        ? path.join(os.homedir(), "Library", "Caches", "ms-playwright")
        : path.join(os.homedir(), ".cache", "ms-playwright"));
  if (!existsSync(root)) return false;
  return readdirSync(root).some((entry) => entry.startsWith("chromium"));
}

const candidates = collectCandidates();
if (candidates.length === 0) {
  console.error(
    "No local Playwright installation found.\n" +
      "Install one with `pnpm add -D playwright` in frontend/, or set PLAYWRIGHT_CLI.",
  );
  process.exit(1);
}

const ranked = rankCandidates(candidates);
const cli = ranked[0].cliPath;
const packageDir = path.dirname(cli);
const nodeModules = path.dirname(packageDir);
const version = ranked[0].version;

console.error(`[playwright] using ${version} from ${packageDir}`);
ensureModuleLink(packageDir);

if (!hasChromium()) {
  console.error("[playwright] no browser build found; installing chromium…");
  execFileSync(process.execPath, [cli, "install", "chromium"], { stdio: "inherit" });
}

const env = {
  ...process.env,
  NODE_PATH: [nodeModules, process.env.NODE_PATH].filter(Boolean).join(path.delimiter),
};

const child = spawn(process.execPath, [cli, ...process.argv.slice(2)], {
  stdio: "inherit",
  cwd: frontendDir,
  env,
});

child.on("exit", (code) => process.exit(code ?? 1));
