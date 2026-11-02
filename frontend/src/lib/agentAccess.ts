import type { ApiMeta } from "@/lib/types";

/**
 * Which scopes the create form may offer.
 *
 * The server owns both lists; this only decides which one applies. Keeping it here (rather than
 * inside the card) makes the rule testable and impossible to bypass by accident in the UI.
 */
export function scopeChoicesFor(isAdmin: boolean, meta: ApiMeta | undefined): string[] {
  if (!meta) return [];
  return isAdmin ? meta.token_scopes : meta.member_token_scopes;
}

/** A ready-to-paste MCP client entry for this installation. */
export function mcpConfigSnippet(origin: string, token: string): string {
  return [
    "{",
    '  "servers": {',
    '    "tralala": {',
    '      "type": "http",',
    `      "url": "${origin}/mcp",`,
    `      "headers": { "Authorization": "Bearer ${token}" }`,
    "    }",
    "  }",
    "}",
  ].join("\n");
}
