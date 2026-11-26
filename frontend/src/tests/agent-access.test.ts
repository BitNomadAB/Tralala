import { describe, expect, it } from "vitest";
import {
  claudeCodeCommand,
  MCP_LEGACY_REVISION,
  MCP_REVISION,
  scopeChoicesFor,
} from "@/lib/agentAccess";
import type { ApiMeta } from "@/lib/types";

const meta: ApiMeta = {
  api_version: "v1",
  scopes: ["boards:read", "boards:write", "cards:read"],
  token_scopes: ["boards:read", "boards:write", "cards:read"],
  member_token_scopes: ["boards:read", "cards:read"],
  member_token_limits: { live: 10, default_days: 30, max_days: 365 },
  can_issue_tokens: true,
  editor_decisions: false,
  features: {},
};

describe("interaction agent access", () => {
  it("offers a member only the member vocabulary, an admin everything grantable", () => {
    expect(scopeChoicesFor(false, meta)).toEqual(["boards:read", "cards:read"]);
    expect(scopeChoicesFor(true, meta)).toEqual(["boards:read", "boards:write", "cards:read"]);
    expect(scopeChoicesFor(true, undefined)).toEqual([]);
  });

  it("builds the Claude Code command for this origin and key", () => {
    expect(claudeCodeCommand("https://tralala.example.com", "trl_abc")).toBe(
      'claude mcp add --transport http tralala https://tralala.example.com/mcp --header "Authorization: Bearer trl_abc"',
    );
  });

  it("names the two revisions the endpoint speaks", () => {
    expect(MCP_REVISION).toBe("2026-07-28");
    expect(MCP_LEGACY_REVISION).toBe("2025-06-18");
  });
});
