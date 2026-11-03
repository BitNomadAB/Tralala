import { describe, expect, it } from "vitest";
import { describeRunRepositories, runRepositories } from "@/lib/loopRuns";
import type { GenerationRun } from "@/lib/types";

function run(source_revisions: GenerationRun["source_revisions"]): GenerationRun {
  return {
    id: "run",
    loop_id: "loop",
    purpose: "analysis",
    status: "completed",
    phase: "generating",
    error_code: null,
    error_message: null,
    attempts: 1,
    output: {},
    source_revisions,
    created_at: "2026-11-02T20:00:00Z",
    started_at: null,
    finished_at: null,
    model: "m",
    agent_name: null,
    usage: {},
  };
}

describe("run repository provenance", () => {
  it("says nothing when the run was not based on a repository", () => {
    expect(runRepositories(run({ info: "abc" }))).toEqual([]);
    expect(describeRunRepositories(run({ info: "abc" }))).toBeNull();
  });

  it("names the repository, the short commit and the file count", () => {
    const entry = run({
      info: "abc",
      repositories: [
        {
          id: "r1",
          name: "acme app",
          branch: "main",
          commit_sha: "abc123def4567890",
          file_count: 12,
          truncated: false,
        },
      ],
    });
    expect(describeRunRepositories(entry)).toBe("acme app @ abc123de, 12 files");
  });

  it("says how much file text the repository sent of its budget", () => {
    const repository = {
      id: "r1",
      name: "acme app",
      branch: "main",
      commit_sha: "abc123def4567890",
      file_count: 32,
      truncated: false,
      budget_chars: 360_000,
      snapshot_chars_included: 200_704,
      content_omitted: false,
    };
    expect(describeRunRepositories(run({ repositories: [repository] }))).toBe(
      "acme app @ abc123de, 32 files, 196 KB",
    );
    const small = { ...repository, file_count: 1, snapshot_chars_included: 300 };
    expect(describeRunRepositories(run({ repositories: [small] }))).toBe(
      "acme app @ abc123de, 1 files, <1 KB",
    );
    const omitted = {
      ...repository,
      file_count: 0,
      truncated: true,
      snapshot_chars_included: 0,
      content_omitted: true,
    };
    expect(describeRunRepositories(run({ repositories: [omitted] }))).toBe(
      "acme app @ abc123de, 0 files, no room for file content, truncated",
    );
  });

  it("says when the snapshot was cut short", () => {
    const entry = run({
      repositories: [
        {
          id: "r1",
          name: "acme app",
          branch: "main",
          commit_sha: "abc123def4567890",
          file_count: 200,
          truncated: true,
        },
      ],
    });
    expect(describeRunRepositories(entry)).toContain("truncated");
  });

  it("keeps a repository that could not be read visible with its reason", () => {
    const entry = run({
      repositories: [
        {
          id: "r1",
          name: "acme app",
          branch: null,
          commit_sha: null,
          file_count: 0,
          truncated: false,
          error: "unauthorized",
        },
      ],
    });
    expect(describeRunRepositories(entry)).toBe("acme app (unavailable: unauthorized)");
  });

  it("says out loud when the board had no repository", () => {
    const entry = run({ info: "abc", repositories: [] });
    expect(describeRunRepositories(entry)).toBe("no enabled repository linked to this board");
  });
});
