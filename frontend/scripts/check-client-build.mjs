#!/usr/bin/env node
/**
 * Client build guard for anti-reverse-engineering checks.
 *
 * Fails the build when the shipped browser bundle contains source maps or text that belongs to
 * the server only. Runs after `vite build` and has no dependencies, so it also works inside the
 * container image build, where only this package is present.
 */
import { readdirSync, readFileSync, statSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const scriptDir = path.dirname(fileURLToPath(import.meta.url));
const distDir = path.resolve(scriptDir, "..", "dist");

const FORBIDDEN = [
  { text: "dev-insecure-secret-change-me", reason: "published fallback session secret" },
  { text: "session-secret", reason: "server secret file name" },
  { text: "TRALALA_SECRET_KEY", reason: "server environment variable" },
  { text: "TRALALA_BOOTSTRAP_PASSWORD", reason: "server environment variable" },
  { text: "registry.sqlite", reason: "server database file" },
  { text: "board.sqlite", reason: "server database file" },
  { text: "sqlalchemy", reason: "server framework" },
];

function walk(directory) {
  const files = [];
  for (const entry of readdirSync(directory)) {
    const full = path.join(directory, entry);
    if (statSync(full).isDirectory()) files.push(...walk(full));
    else files.push(full);
  }
  return files;
}

if (!statSync(distDir, { throwIfNoEntry: false })?.isDirectory()) {
  console.error(`[client-build-guard] no build output at ${distDir}`);
  process.exit(1);
}

const files = walk(distDir);
const problems = [];

for (const file of files) {
  if (file.endsWith(".map")) {
    problems.push(`source map shipped: ${path.relative(distDir, file)}`);
  }
}

for (const file of files.filter((entry) => /\.(js|mjs|css|html)$/.test(entry))) {
  const content = readFileSync(file, "utf8").toLowerCase();
  for (const rule of FORBIDDEN) {
    if (content.includes(rule.text.toLowerCase())) {
      problems.push(`${rule.reason} ("${rule.text}") in ${path.relative(distDir, file)}`);
    }
  }
}

if (problems.length > 0) {
  console.error("[client-build-guard] FAIL");
  for (const problem of problems) console.error(`  - ${problem}`);
  process.exit(1);
}

console.log(
  `[client-build-guard] ok (${files.length} files scanned, no source maps or server-only strings)`,
);
