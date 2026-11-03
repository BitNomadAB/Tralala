import { describe, expect, it } from "vitest";
import { mcpConfigSnippet, scopeChoicesFor } from "@/lib/agentAccess";
import type { ApiMeta } from "@/lib/types";

const meta: ApiMeta = {
  api_version: "v1",
  scopes: ["boards:read", "boards:write", "cards:read"],
  token_scopes: ["boards:read", "boards:write", "cards:read"],
  member_token_scopes: ["boards:read", "cards:read"],
  member_token_limits: { live: 10, default_days: 30, max_days: 365 },
  can_issue_tokens: true,
  features: {},
};

describe("interaction agent access", () => {
  it("offers a member only the member vocabulary, an admin everything grantable", () => {
    expect(scopeChoicesFor(false, meta)).toEqual(["boards:read", "cards:read"]);
    expect(scopeChoicesFor(true, meta)).toEqual(["boards:read", "boards:write", "cards:read"]);
    expect(scopeChoicesFor(true, undefined)).toEqual([]);
  });

  it("builds a paste-ready MCP client entry for this origin", () => {
    const snippet = mcpConfigSnippet("https://tralala.example.com", "trl_abc");
    expect(snippet).toContain('"url": "https://tralala.example.com/mcp"');
    expect(snippet).toContain('"Authorization": "Bearer trl_abc"');
    expect((): unknown => JSON.parse(snippet)).not.toThrow();
  });
});
