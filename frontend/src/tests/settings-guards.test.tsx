import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http } from "msw";
import type { ReactNode } from "react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { describe, expect, it } from "vitest";
import { ToastProvider } from "@/components/ui/toast";
import { InteractionAccessCard } from "@/features/settings/InteractionAccessCard";
import { RoleTemplateEditorPage } from "@/features/settings/RoleTemplateEditorPage";
import type { ApiMeta, Credential, RoleTemplate } from "@/lib/types";
import { apiPath, failure, ok, requestPath } from "./msw/envelope";
import { server } from "./msw/server";

const META: ApiMeta = {
  api_version: "1",
  scopes: ["boards:read"],
  token_scopes: ["boards:read"],
  member_token_scopes: ["boards:read"],
  member_token_limits: { live: 5, default_days: 30, max_days: 365 },
  can_issue_tokens: true,
  features: {},
};

const KEY: Credential = {
  id: "key-1",
  actor_id: "agent-1",
  actor_name: null,
  owner_actor_id: "user-1",
  owner_name: null,
  name: "laptop",
  scopes: ["boards:read"],
  created_at: "2026-11-01T09:00:00Z",
  expires_at: null,
  last_used_at: null,
  revoked_at: null,
};

const ROLE: RoleTemplate = {
  id: "role-1",
  name: "Lead Developer",
  description: "Leads.",
  system_prompt: "My own prompt.",
  built_in: true,
  builtin_key: "lead_developer",
  scope: "board",
  customized: true,
  agent_count: 0,
  created_at: "2026-11-01T09:00:00Z",
  updated_at: "2026-11-01T09:00:00Z",
};

/** Renders `children` with a fresh query client and the toasts. */
function renderWith(children: ReactNode) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  render(
    <QueryClientProvider client={queryClient}>
      <ToastProvider>{children}</ToastProvider>
    </QueryClientProvider>,
  );
  return userEvent.setup();
}

/** Every write sent, by its path. */
function recorder() {
  const writes: string[] = [];
  return { writes, record: (request: Request) => writes.push(requestPath(request)) };
}

/** A person's own access card over one key; revoking and rotating are recorded in `writes`. */
async function renderKeys() {
  const { writes, record } = recorder();
  server.use(
    http.get(apiPath("/meta"), () => ok(META)),
    http.get(apiPath("/credentials/mine"), () => ok([KEY])),
    http.post(apiPath("/credentials/:id/:action"), ({ request }) => {
      record(request);
      return ok({ ...KEY, id: "key-2", token: "trl_new_token_value_123456" });
    }),
  );
  const user = renderWith(<InteractionAccessCard isAdmin={false} currentUserId="user-1" />);
  await screen.findByText("laptop");
  return { user, writes };
}

describe("revoking and rotating an access key", () => {
  it("asks first, says what Revoke does, and Cancel sends nothing", async () => {
    const { user, writes } = await renderKeys();
    const revoke = screen.getByRole("button", { name: "Revoke laptop" });
    await user.click(revoke);

    const dialog = screen.getByRole("dialog", { name: "Revoke laptop?" });
    expect(dialog).toHaveAccessibleDescription(
      "Agents using this key lose access at once. This cannot be undone.",
    );
    // Focus starts on the choice that changes nothing.
    const cancel = within(dialog).getByRole("button", { name: "Cancel" });
    expect(cancel).toHaveFocus();
    await user.click(cancel);

    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    await waitFor(() => expect(revoke).toHaveFocus());
    expect(writes).toEqual([]);
  });

  it("revokes the key once it is confirmed", async () => {
    const { user, writes } = await renderKeys();
    await user.click(screen.getByRole("button", { name: "Revoke laptop" }));
    await user.click(screen.getByRole("button", { name: "Revoke key" }));

    expect(await screen.findByText("Agent access revoked")).toBeInTheDocument();
    expect(writes).toEqual(["/credentials/key-1/revoke"]);
  });

  it("says so when the server refuses the revoke", async () => {
    const { user } = await renderKeys();
    server.use(
      http.post(apiPath("/credentials/:id/revoke"), () =>
        failure(409, "conflict", "The key is in use by a running job"),
      ),
    );
    await user.click(screen.getByRole("button", { name: "Revoke laptop" }));
    await user.click(screen.getByRole("button", { name: "Revoke key" }));

    expect(await screen.findByText("Could not revoke the access")).toBeInTheDocument();
  });

  it("says that the old token stops working before it rotates, and shows the new one", async () => {
    const { user, writes } = await renderKeys();
    await user.click(screen.getByRole("button", { name: "Rotate laptop" }));

    const dialog = screen.getByRole("dialog", { name: "Rotate laptop?" });
    expect(dialog).toHaveAccessibleDescription(
      "The old token stops working at once, so agents using it lose access until they get the new one. You get the new token once.",
    );
    expect(writes).toEqual([]);
    await user.click(within(dialog).getByRole("button", { name: "Rotate key" }));

    expect(await screen.findByRole("dialog", { name: "Copy this token now" })).toBeInTheDocument();
    expect(writes).toEqual(["/credentials/key-1/rotate"]);
  });
});

describe("the guide on the access card", () => {
  it("puts the command it shows on the clipboard and says so", async () => {
    const { user } = await renderKeys();
    await user.click(screen.getByText("How do I connect my computer?"));
    const command = screen.getByRole("group", { name: "Code block" });
    expect(command).toHaveTextContent(/^claude mcp add --transport http tralala /);

    await user.click(screen.getByRole("button", { name: "Copy this command" }));

    expect(await screen.findByText("Command copied")).toBeInTheDocument();
    expect(await navigator.clipboard.readText()).toBe(command.textContent);
  });
});

/** The editor of a built-in role whose prompt was customized; restoring is recorded. */
async function renderRole() {
  const { writes, record } = recorder();
  server.use(
    http.get(apiPath("/role-templates/role-1"), () => ok(ROLE)),
    http.post(apiPath("/role-templates/role-1/restore-defaults"), ({ request }) => {
      record(request);
      return ok({ ...ROLE, system_prompt: "You are the lead developer.", customized: false });
    }),
  );
  const user = renderWith(
    <MemoryRouter initialEntries={["/settings/roles/role-1"]}>
      <Routes>
        <Route path="/settings/roles/:roleId" element={<RoleTemplateEditorPage />} />
      </Routes>
    </MemoryRouter>,
  );
  const prompt = await screen.findByLabelText("System prompt");
  await user.type(prompt, " Unsaved words.");
  return { user, writes, prompt };
}

describe("restoring a role's factory prompt", () => {
  it("asks before it replaces the person's prompt, and Cancel keeps their words", async () => {
    const { user, writes, prompt } = await renderRole();
    const restore = screen.getByRole("button", { name: "Restore factory prompt" });
    await user.click(restore);

    const dialog = screen.getByRole("dialog", {
      name: "Replace your prompt with the factory text?",
    });
    expect(dialog).toHaveAccessibleDescription(
      "The factory prompt replaces yours and is saved at once. Your own prompt, and any changes to it you have not saved, are lost.",
    );
    await user.click(within(dialog).getByRole("button", { name: "Cancel" }));

    await waitFor(() => expect(restore).toHaveFocus());
    expect(prompt).toHaveValue("My own prompt. Unsaved words.");
    expect(writes).toEqual([]);
  });

  it("restores the factory prompt once it is confirmed", async () => {
    const { user, writes, prompt } = await renderRole();
    await user.click(screen.getByRole("button", { name: "Restore factory prompt" }));
    await user.click(screen.getByRole("button", { name: "Replace prompt" }));

    await waitFor(() => expect(prompt).toHaveValue("You are the lead developer."));
    expect(writes).toEqual(["/role-templates/role-1/restore-defaults"]);
    expect(await screen.findByText("Factory prompt restored")).toBeInTheDocument();
  });
});
