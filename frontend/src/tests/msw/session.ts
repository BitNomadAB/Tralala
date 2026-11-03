import { http } from "msw";
import type { Actor, ApiMeta, PageMeta } from "@/lib/types";
import { apiPath, failure, ok, requestPath } from "./envelope";

export const MEMBER: Actor = {
  id: "user-1",
  type: "user",
  name: "Ada Member",
  role: "member",
  scopes: [],
  preferences: null,
};

export const MEMBER_PASSWORD = "old-password-1";

const META: ApiMeta = {
  api_version: "v1",
  scopes: [],
  token_scopes: [],
  member_token_scopes: [],
  member_token_limits: { live: 5, default_days: 30, max_days: 365 },
  can_issue_tokens: true,
  features: {},
};

const EMPTY_PAGE: PageMeta = { total: 0, limit: 50, offset: 0, has_more: false };

/** A string field of the request's JSON body, or "" when the body has no such field. */
async function field(request: Request, name: string): Promise<string> {
  const body: unknown = await request.json().catch(() => null);
  if (typeof body !== "object" || body === null) return "";
  const value: unknown = (body as Record<string, unknown>)[name];
  return typeof value === "string" ? value : "";
}

/**
 * A member's session as the server keeps it, as MSW handlers for `server.use(...)`: the settings
 * page and the dashboard are answered, a password change and a logout end the session, and once it
 * has ended every request except a sign-in is a 401. A password change with the wrong current
 * password is refused with a 422 and the session goes on, as the server answers it. `state.requests` is everything the app sent,
 * as "METHOD /path"; a test may end the session itself with `state.signedIn = false`.
 */
export function memberSession() {
  const state = { signedIn: true, password: MEMBER_PASSWORD, requests: [] as string[] };

  const handlers = [
    // Answers nothing, so MSW moves on to the next handler: this one only records the request.
    http.all(apiPath("/*"), ({ request }) => {
      state.requests.push(`${request.method} ${requestPath(request)}`);
    }),
    http.post(apiPath("/auth/login"), async ({ request }) => {
      if ((await field(request, "password")) !== state.password) {
        return failure(401, "invalid_credentials", "Invalid username or password");
      }
      state.signedIn = true;
      return ok({ actor: MEMBER, csrf_token: "csrf-test" });
    }),
    http.all(apiPath("/*"), () =>
      state.signedIn ? undefined : failure(401, "unauthorized", "Authentication required"),
    ),
    http.get(apiPath("/auth/me"), () => ok(MEMBER)),
    http.get(apiPath("/meta"), () => ok(META)),
    http.get(apiPath("/templates"), () => ok({ items: [] })),
    http.get(apiPath("/role-templates"), () => ok([])),
    http.get(apiPath("/agents"), () => ok([])),
    http.get(apiPath("/credentials/mine"), () => ok([])),
    http.get(apiPath("/boards"), () => ok([], EMPTY_PAGE)),
    http.post(apiPath("/auth/password"), async ({ request }) => {
      if ((await field(request.clone(), "current_password")) !== state.password) {
        return failure(422, "invalid_credentials", "Current password is incorrect");
      }
      state.password = await field(request, "new_password");
      state.signedIn = false;
      return ok({ changed: true, revoked_sessions: 1 });
    }),
    http.post(apiPath("/auth/logout"), () => {
      state.signedIn = false;
      return ok({ logged_out: true });
    }),
  ];

  return { state, handlers };
}
