import type { ApiMeta, Credential } from "@/lib/types";

/** The right to decide in the editor: a scope a person gives a key of their own, never alone. */
export const DECIDE_SCOPE = "loops:decide";

/** What the create form and the list of keys call the right. */
export const DECIDE_LABEL = "Decide in the editor";

/** What the form says beside the right before a person gives it. */
export const DECIDE_WARNING =
  "Anyone who holds this key can then approve, clear a wait or confirm in your name.";

/** The scopes this role may grant, from the server's list for it. */
function grantable(isAdmin: boolean, meta: ApiMeta): string[] {
  return isAdmin ? meta.token_scopes : meta.member_token_scopes;
}

/**
 * Which scopes the create form offers as plain checkboxes.
 *
 * The server owns both lists; this only decides which one applies. Keeping it here (rather than
 * inside the card) makes the rule testable and impossible to bypass by accident in the UI. The
 * right to decide in the editor is never among them: the form offers it on its own, with its
 * warning, and only when `offersDecide` says so.
 */
export function scopeChoicesFor(isAdmin: boolean, meta: ApiMeta | undefined): string[] {
  if (!meta) return [];
  return grantable(isAdmin, meta).filter((scope) => scope !== DECIDE_SCOPE);
}

/** Whether the create form offers the right to decide in the editor: only while /meta says the
 * installation allows it and the right is one this role may grant. */
export function offersDecide(isAdmin: boolean, meta: ApiMeta | undefined): boolean {
  if (!meta) return false;
  return meta.editor_decisions && grantable(isAdmin, meta).includes(DECIDE_SCOPE);
}

/** Whether a key holds the right to decide in the editor. */
export function holdsDecide(credential: Credential): boolean {
  return credential.scopes.includes(DECIDE_SCOPE);
}

/** The newer of the two MCP revisions `/mcp` speaks on one address. */
export const MCP_REVISION = "2026-07-28";

/** The older MCP revision `/mcp` speaks beside it, which opens with `initialize`. */
export const MCP_LEGACY_REVISION = "2025-06-18";

/** The command that adds this installation to Claude Code, the one the agent guide gives. */
export function claudeCodeCommand(origin: string, token: string): string {
  return `claude mcp add --transport http tralala ${origin}/mcp --header "Authorization: Bearer ${token}"`;
}
