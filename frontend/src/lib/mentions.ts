export interface MentionToken {
  /** Index of the `@` that starts the token. */
  start: number;
  /** Caret index where the query ends. */
  end: number;
  query: string;
}

/**
 * Find the agent mention being typed at `caret`, if any.
 *
 * `@` inside a word (an e-mail address) is not a mention, and a closed `@[Name]` no longer
 * searches.
 */
export function activeMention(text: string, caret: number): MentionToken | null {
  const before = text.slice(0, caret);
  const at = before.lastIndexOf("@");
  if (at < 0) return null;
  const previous = at > 0 ? before[at - 1] : "";
  if (previous && /[A-Za-z0-9._-]/.test(previous)) return null;
  const query = before.slice(at + 1);
  if (query.includes("]") || query.includes("\n") || query.length > 60) return null;
  if (query.startsWith("[")) {
    return { start: at, end: caret, query: query.slice(1) };
  }
  return { start: at, end: caret, query };
}

/** Replace the typed token with the unambiguous `@[Name]` form the backend parses. */
export function applyMention(
  text: string,
  token: MentionToken,
  name: string,
): { text: string; caret: number } {
  const after = text.slice(token.end);
  const separator = /^[\s.,;:!?]/.test(after) ? "" : " ";
  const insertion = `@[${name}]${separator}`;
  return {
    text: `${text.slice(0, token.start)}${insertion}${after}`,
    caret: token.start + insertion.length,
  };
}

export function matchingAgents<T extends { name: string }>(agents: T[], query: string): T[] {
  const needle = query.trim().toLowerCase();
  if (!needle) return agents;
  return agents.filter((agent) => agent.name.toLowerCase().includes(needle));
}
