import { repositoryProblem } from "@/lib/runPhases";
import { describeRunReading } from "@/lib/runTrace";
import type { GenerationRun, GenerationRunRepository } from "@/lib/types";

/** The repositories a run was based on, from its recorded source revisions. */
export function runRepositories(run: GenerationRun): GenerationRunRepository[] {
  const value = run.source_revisions.repositories;
  return Array.isArray(value) ? value : [];
}

/**
 * One line saying which commit an analysis read, or why a repository was missing.
 *
 * The run record is the only place this lives: the prompt showed the model file contents, but the
 * person needs the commit and the count, not the files.
 */
/** How much a repository sent: what its files and its manifest took of the run's context. */
function sentSize(repository: GenerationRunRepository): string {
  if (repository.content_omitted) return ", no room for file content";
  const chars = repository.snapshot_chars_included;
  if (chars === undefined) return "";
  if (chars === 0) return ", 0 KB";
  return chars < 1024 ? ", <1 KB" : `, ${Math.round(chars / 1024)} KB`;
}

/** A mirror the run could not bring up to date, and how old the copy it read was. */
function staleness(repository: GenerationRunRepository): string {
  if (!repository.stale_mirror) return "";
  return ` (stale mirror from ${repository.fetched_at ?? "an earlier fetch"})`;
}

/**
 * "app @ 1a2b3c4d, 12 files", or for a run that could not read the code what it was written without
 * and why, in the server's sentence: "no code — written without the repository (The key cannot see
 * app: give it read access to the repository's contents)".
 */
export function describeRunRepositories(run: GenerationRun): string | null {
  const value = run.source_revisions.repositories;
  if (!Array.isArray(value)) return null;
  const repositories = value;
  if (repositories.length === 0) return "no enabled repository linked to this board";
  if (repositories.every((repository) => Boolean(repository.error))) {
    const problems = repositories.map(repositoryProblem).join("; ");
    return `no code — written without the repository (${problems})`;
  }
  const described = repositories.map((repository) =>
    repository.error
      ? `${repository.name} — not read (${repositoryProblem(repository)})`
      : `${repository.name} @ ${(repository.commit_sha ?? "").slice(0, 8)}, ${readSize(repository)}${staleness(repository)}`,
  );
  // A model that read through tools: what it actually read, not what it could have.
  const reading = describeRunReading(run);
  return described.join("; ") + (reading ? ` — ${reading}` : "");
}

/** What a repository offered the model: files sent in the snapshot, or files it could read. */
function readSize(repository: GenerationRunRepository): string {
  if (repository.reading === "tools") {
    const left = repository.left_out ? `, ${repository.left_out} too large to read` : "";
    return `${repository.file_count} files to read from${left}`;
  }
  return `${repository.file_count} files${sentSize(repository)}${repository.truncated ? ", truncated" : ""}`;
}

function count(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) && value >= 0 ? value : null;
}

/** "950" or "41 k". */
function tokens(value: number): string {
  return value < 1000 ? String(value) : `${Math.round(value / 1000)} k`;
}

/** "45 s", "2 min 21 s" or "1 h 3 min". */
function duration(ms: number): string {
  const seconds = Math.round(ms / 1000);
  if (seconds < 60) return `${seconds} s`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes} min ${seconds % 60} s`;
  return `${Math.floor(minutes / 60)} h ${minutes % 60} min`;
}

/**
 * What a finished run cost, as the provider reported it: "41 k tokens (3 k reasoning) · 2 min 21 s".
 * Tokens are the provider's total, else prompt plus completion; a run without usage shows its
 * duration only; a run that has not finished shows nothing.
 */
export function describeRunCost(run: GenerationRun): string | null {
  if (run.status === "queued" || run.status === "running") return null;
  const parts: string[] = [];
  const usage = run.usage;
  const prompt = count(usage.prompt_tokens);
  const completion = count(usage.completion_tokens);
  const total =
    count(usage.total_tokens) ??
    (prompt !== null || completion !== null ? (prompt ?? 0) + (completion ?? 0) : null);
  if (total !== null && total > 0) {
    const details = usage.completion_tokens_details;
    const reasoning =
      count(usage.reasoning_tokens) ??
      (typeof details === "object" && details !== null && "reasoning_tokens" in details
        ? count(details.reasoning_tokens)
        : null);
    parts.push(`${tokens(total)} tokens${reasoning ? ` (${tokens(reasoning)} reasoning)` : ""}`);
  }
  if (run.started_at && run.finished_at) {
    const ms = Date.parse(run.finished_at) - Date.parse(run.started_at);
    if (Number.isFinite(ms) && ms >= 0) parts.push(duration(ms));
  }
  return parts.length > 0 ? parts.join(" · ") : null;
}
