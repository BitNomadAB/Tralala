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
/** How much file text a repository sent: what its files took of the run's context. */
function sentSize(repository: GenerationRunRepository): string {
  if (repository.content_omitted) return ", no room for file content";
  const chars = repository.snapshot_chars_included;
  if (chars === undefined) return "";
  if (chars === 0) return ", 0 KB";
  return chars < 1024 ? ", <1 KB" : `, ${Math.round(chars / 1024)} KB`;
}

export function describeRunRepositories(run: GenerationRun): string | null {
  const value = run.source_revisions.repositories;
  if (!Array.isArray(value)) return null;
  const repositories = value;
  if (repositories.length === 0) return "no enabled repository linked to this board";
  return repositories
    .map((repository) =>
      repository.error
        ? `${repository.name} (unavailable: ${repository.error})`
        : `${repository.name} @ ${(repository.commit_sha ?? "").slice(0, 8)}, ${repository.file_count} files${sentSize(repository)}${repository.truncated ? ", truncated" : ""}`,
    )
    .join("; ");
}
