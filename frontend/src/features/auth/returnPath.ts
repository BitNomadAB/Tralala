/**
 * Where the sign-in goes once it went through: the address a signed-out person opened, kept whole,
 * so a link to a decision (`?dialog=completion`, `?focus=confirm`) still opens it after the sign-in.
 * `RequireAuth` keeps the address in the login page's location state as `from`.
 */

/** Where the sign-in goes when no address inside Tralala was kept. */
const HOME = "/";

/** The address of `location` inside Tralala: its path, its query and its fragment. */
export function addressOf(location: { pathname: string; search: string; hash: string }): string {
  return `${location.pathname}${location.search}${location.hash}`;
}

/**
 * `from` when it is an address inside Tralala, else "/", so the sign-in never sends anyone to
 * another site (an open redirect). Only a relative address that starts with one slash is followed:
 * `//host` and `/\host` (a browser reads the backslash as a slash) name another host, and a
 * scheme (`https:`, `javascript:`) is no relative address. A browser also drops tabs and line breaks
 * from an address, so any control character is refused; and the address, read against this
 * `origin` as the browser reads it, must stay on it.
 */
export function safeReturnPath(from: unknown, origin: string = window.location.origin): string {
  if (typeof from !== "string") return HOME;
  if (!from.startsWith("/") || from.startsWith("//") || from.startsWith("/\\")) return HOME;
  for (const char of from) {
    const code = char.charCodeAt(0);
    if (code < 0x20 || code === 0x7f) return HOME;
  }
  let url: URL;
  try {
    url = new URL(from, origin);
  } catch {
    return HOME;
  }
  return url.origin === origin ? from : HOME;
}

/** The address the sign-in goes to: the `from` `RequireAuth` kept in `state`, when it is safe. */
export function returnPath(state: unknown): string {
  if (typeof state !== "object" || state === null || !("from" in state)) return HOME;
  return safeReturnPath(state.from);
}
