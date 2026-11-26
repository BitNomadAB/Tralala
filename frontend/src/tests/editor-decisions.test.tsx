import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http } from "msw";
import { describe, expect, it } from "vitest";
import { ToastProvider } from "@/components/ui/toast";
import { InteractionAccessCard } from "@/features/settings/InteractionAccessCard";
import {
  DECIDE_LABEL,
  DECIDE_SCOPE,
  DECIDE_WARNING,
  offersDecide,
  scopeChoicesFor,
} from "@/lib/agentAccess";
import type { ApiMeta, Credential } from "@/lib/types";
import { apiPath, failure, ok } from "./msw/envelope";
import { server } from "./msw/server";

const META: ApiMeta = {
  api_version: "v1",
  scopes: ["boards:read", "cards:read", DECIDE_SCOPE],
  token_scopes: ["boards:read", "boards:write", "cards:read", DECIDE_SCOPE],
  member_token_scopes: ["boards:read", "cards:read", DECIDE_SCOPE],
  member_token_limits: { live: 10, default_days: 30, max_days: 365 },
  can_issue_tokens: true,
  editor_decisions: true,
  features: {},
};

/** One of a person's keys, holding `scopes`. */
function key(id: string, name: string, scopes: string[]): Credential {
  return {
    id,
    actor_id: `agent-${id}`,
    actor_name: name,
    owner_actor_id: "user-1",
    owner_name: "Ada",
    name,
    scopes,
    created_at: "2026-11-01T09:00:00Z",
    expires_at: null,
    last_used_at: null,
    revoked_at: null,
  };
}

/** A person with three keys, two of which hold the right, on an installation that allows it. */
const KEYS = [
  key("k-1", "Claude Code", ["boards:read", "cards:read", DECIDE_SCOPE]),
  key("k-2", "Codex", ["boards:read", DECIDE_SCOPE]),
  key("k-3", "Laptop", ["boards:read"]),
];

/** The person's own access card; every body sent to POST /credentials lands in `sent`. */
async function renderCard(meta: ApiMeta = META) {
  const sent: unknown[] = [];
  server.use(
    http.get(apiPath("/meta"), () => ok(meta)),
    http.get(apiPath("/credentials/mine"), () => ok(KEYS)),
    http.post(apiPath("/credentials"), async ({ request }) => {
      const body: unknown = await request.json();
      sent.push(body);
      return ok({ ...key("k-4", "Desktop", [DECIDE_SCOPE]), token: "trl_new_token_value_123" });
    }),
  );
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  render(
    <QueryClientProvider client={client}>
      <ToastProvider>
        <InteractionAccessCard isAdmin={false} currentUserId="user-1" />
      </ToastProvider>
    </QueryClientProvider>,
  );
  await screen.findByText("Laptop");
  return { user: userEvent.setup(), sent };
}

/** The open New access key dialog, once the scope list from /meta has arrived. */
async function openForm(user: ReturnType<typeof userEvent.setup>) {
  await user.click(screen.getByRole("button", { name: "New access key" }));
  const dialog = screen.getByRole("dialog", { name: "New interaction agent access" });
  await within(dialog).findByRole("checkbox", { name: "cards:read" });
  return dialog;
}

describe("the right to decide in the editor", () => {
  it("is offered apart from the scopes, only while the installation allows it", () => {
    expect(scopeChoicesFor(false, META)).toEqual(["boards:read", "cards:read"]);
    expect(scopeChoicesFor(true, META)).toEqual(["boards:read", "boards:write", "cards:read"]);
    expect(offersDecide(false, META)).toBe(true);
    expect(offersDecide(true, META)).toBe(true);
    expect(offersDecide(false, { ...META, editor_decisions: false })).toBe(false);
    expect(offersDecide(false, { ...META, member_token_scopes: ["boards:read"] })).toBe(false);
    expect(offersDecide(false, undefined)).toBe(false);
  });

  it("is offered with its warning, unticked, and sent only when the person ticks it", async () => {
    const { user, sent } = await renderCard();
    const dialog = await openForm(user);

    const right = within(dialog).getByRole("checkbox", { name: DECIDE_LABEL });
    expect(right).not.toBeChecked();
    expect(right).toHaveAccessibleDescription(DECIDE_WARNING);
    expect(DECIDE_WARNING).toBe(
      "Anyone who holds this key can then approve, clear a wait or confirm in your name.",
    );
    expect(within(dialog).queryByRole("checkbox", { name: DECIDE_SCOPE })).not.toBeInTheDocument();

    await user.type(within(dialog).getByLabelText("Agent name"), "Desktop");
    await user.click(right);
    await user.click(within(dialog).getByRole("button", { name: "Create access" }));

    await screen.findByRole("dialog", { name: "Copy this token now" });
    expect(sent).toEqual([
      { name: "Desktop", scopes: ["boards:read", "cards:read", DECIDE_SCOPE], expires_in_days: 30 },
    ]);
  });

  it("leaves the right out of a key the person did not tick it for", async () => {
    const { user, sent } = await renderCard();
    const dialog = await openForm(user);

    await user.type(within(dialog).getByLabelText("Agent name"), "Desktop");
    await user.click(within(dialog).getByRole("button", { name: "Create access" }));

    await screen.findByRole("dialog", { name: "Copy this token now" });
    expect(sent).toEqual([
      { name: "Desktop", scopes: ["boards:read", "cards:read"], expires_in_days: 30 },
    ]);
  });

  it("is not offered while the installation has it off", async () => {
    const { user } = await renderCard({ ...META, editor_decisions: false });
    const dialog = await openForm(user);

    expect(within(dialog).queryByRole("checkbox", { name: DECIDE_LABEL })).not.toBeInTheDocument();
    expect(within(dialog).queryByText(DECIDE_WARNING)).not.toBeInTheDocument();
    expect(within(dialog).getAllByRole("checkbox")).toHaveLength(2);
  });

  it("says a refusal of the right under it", async () => {
    const { user } = await renderCard();
    server.use(
      http.post(apiPath("/credentials"), () =>
        failure(422, "editor_decisions_off", "Deciding in the editor is switched off", {
          scope: DECIDE_SCOPE,
        }),
      ),
    );
    const dialog = await openForm(user);

    await user.type(within(dialog).getByLabelText("Agent name"), "Desktop");
    const right = within(dialog).getByRole("checkbox", { name: DECIDE_LABEL });
    await user.click(right);
    await user.click(within(dialog).getByRole("button", { name: "Create access" }));

    await waitFor(() => expect(right).toHaveFocus());
    expect(right).toHaveAccessibleDescription(
      `Error: Deciding in the editor is switched off. ${DECIDE_WARNING}`,
    );
  });

  it("is shown on each key in the list that holds it", async () => {
    await renderCard();

    for (const [name, holds] of [
      ["Claude Code", true],
      ["Codex", true],
      ["Laptop", false],
    ] as const) {
      const row = screen.getByText(name).closest("li");
      expect(row).not.toBeNull();
      if (!row) continue;
      const badge = within(row).queryByText(DECIDE_LABEL);
      if (holds) expect(badge).toBeInTheDocument();
      else expect(badge).not.toBeInTheDocument();
    }
  });
});
