import type { RepositoryPaths } from "@/lib/types";

/**
 * What a person typed for one repository: one glob per line, kept as text while the dialog is open
 * so a new line can be started before it holds a glob.
 */
export interface RepositoryPathsDraft {
  focus: string;
  exclude: string;
}

/** The drafts of a board dialog, by repository id. */
export type RepositoryPathsDrafts = Record<string, RepositoryPathsDraft>;

export const EMPTY_PATHS_DRAFT: RepositoryPathsDraft = { focus: "", exclude: "" };

/** A board's stored globs as the text the dialog edits. */
export function pathsDrafts(paths: Record<string, RepositoryPaths>): RepositoryPathsDrafts {
  return Object.fromEntries(
    Object.entries(paths).map(([repositoryId, entry]) => [
      repositoryId,
      { focus: entry.focus_paths.join("\n"), exclude: entry.exclude_paths.join("\n") },
    ]),
  );
}

/** One glob per line; blank lines and the spaces around a glob are not part of it. */
export function globLines(text: string): string[] {
  return text
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter((line) => line !== "");
}

/**
 * The request's `repository_paths`: the globs of each selected repository that has any. A
 * repository left out is read whole, and the server checks every glob.
 */
export function pathsPayload(
  drafts: RepositoryPathsDrafts,
  selected: readonly string[],
): Record<string, RepositoryPaths> {
  const payload: Record<string, RepositoryPaths> = {};
  for (const repositoryId of selected) {
    const draft = drafts[repositoryId];
    if (draft === undefined) continue;
    const focus = globLines(draft.focus);
    const exclude = globLines(draft.exclude);
    if (focus.length > 0 || exclude.length > 0) {
      payload[repositoryId] = { focus_paths: focus, exclude_paths: exclude };
    }
  }
  return payload;
}
