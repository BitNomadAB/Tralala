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

/** The newer of the two MCP revisions `/mcp` speaks on one address. */
export const MCP_REVISION = "2026-07-28";

/** The older MCP revision `/mcp` speaks beside it, which opens with `initialize`. */
export const MCP_LEGACY_REVISION = "2025-06-18";

/** The command that adds this installation to Claude Code, the one the agent guide gives. */
export function claudeCodeCommand(origin: string, token: string): string {
  return `claude mcp add --transport http tralala ${origin}/mcp --header "Authorization: Bearer ${token}"`;
}
