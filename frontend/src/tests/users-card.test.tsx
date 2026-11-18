import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http } from "msw";
import { describe, expect, it } from "vitest";
import { ToastProvider } from "@/components/ui/toast";
import { UsersCard } from "@/features/settings/UsersCard";
import { ROLES, type UserAccount } from "@/lib/types";
import { isRecord } from "./msw/cards";
import { apiPath, ok } from "./msw/envelope";
import { server } from "./msw/server";

function account(id: string, name: string, overrides: Partial<UserAccount> = {}): UserAccount {
  return {
    id,
    name,
    role: "member",
    created_at: "2026-11-01T09:00:00Z",
    disabled: false,
    agent_access_count: 0,
    agent_access_last_used_at: null,
    ...overrides,
  };
}

/**
 * The Users card for the administrator `ada` over the accounts the server keeps; every PATCH is
 * recorded in `writes` and changes the account, as the server does.
 */
async function renderUsers() {
  const users = [
    account("admin-1", "ada", { role: "admin" }),
    account("user-2", "bob"),
    account("user-3", "carl", { disabled: true }),
  ];
  const writes: { userId: string; body: unknown }[] = [];
  server.use(
    http.get(apiPath("/users"), () => ok(users)),
    http.patch(apiPath("/users/:id"), async ({ request, params }) => {
      const body: unknown = await request.json();
      writes.push({ userId: String(params.id), body });
      const index = users.findIndex((entry) => entry.id === params.id);
      const current = users[index];
      if (!current || !isRecord(body)) return ok(null);
      const role = ROLES.find((value) => value === body.role) ?? current.role;
      const disabled = typeof body.disabled === "boolean" ? body.disabled : current.disabled;
      const next = { ...current, role, disabled };
      users[index] = next;
      return ok(next);
    }),
  );
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  render(
    <QueryClientProvider client={queryClient}>
      <ToastProvider>
        <UsersCard currentUserId="admin-1" />
      </ToastProvider>
    </QueryClientProvider>,
  );
  await screen.findByText("bob");
  return { user: userEvent.setup(), writes };
}

describe("changing a person's role", () => {
  it("sends nothing while the person browses the roles, and saves the one chosen with Save role", async () => {
    const { user, writes } = await renderUsers();
    const role = screen.getByRole("combobox", { name: "Role of bob" });
    expect(role).toHaveAccessibleDescription(
      "A new role takes effect when you press Save role beside it.",
    );
    expect(screen.queryByRole("button", { name: "Save role of bob" })).not.toBeInTheDocument();

    // Every step through the options is a change event; none of them reaches the server.
    await user.selectOptions(role, "admin");
    await user.selectOptions(role, "member");
    expect(screen.queryByRole("button", { name: "Save role of bob" })).not.toBeInTheDocument();
    await user.selectOptions(role, "admin");
    expect(writes).toEqual([]);

    await user.click(screen.getByRole("button", { name: "Save role of bob" }));
    expect(await screen.findByText("bob is now an administrator")).toBeInTheDocument();
    expect(writes).toEqual([{ userId: "user-2", body: { role: "admin" } }]);
    // The button goes with the change it saved, and focus is back on the select.
    expect(screen.queryByRole("button", { name: "Save role of bob" })).not.toBeInTheDocument();
    expect(role).toHaveValue("admin");
    expect(role).toHaveFocus();
  });
});

describe("disabling and enabling a person", () => {
  it("asks first, with what disabling does, and Cancel keeps the account as it is", async () => {
    const { user, writes } = await renderUsers();
    const disable = screen.getByRole("button", { name: "Disable bob" });
    await user.click(disable);

    const dialog = screen.getByRole("dialog", { name: "Disable bob?" });
    expect(dialog).toHaveAccessibleDescription(
      "This signs bob out at once and revokes the agent access they issued. Enabling the account later does not bring that access back.",
    );
    await user.click(within(dialog).getByRole("button", { name: "Cancel" }));

    await waitFor(() => expect(disable).toHaveFocus());
    expect(writes).toEqual([]);
  });

  it("disables the account once it is confirmed", async () => {
    const { user, writes } = await renderUsers();
    await user.click(screen.getByRole("button", { name: "Disable bob" }));
    await user.click(screen.getByRole("button", { name: "Disable account" }));

    expect(await screen.findByText("bob is disabled")).toBeInTheDocument();
    expect(writes).toEqual([{ userId: "user-2", body: { disabled: true } }]);
  });

  it("tells a person who disables their own account that it signs them out", async () => {
    const { user, writes } = await renderUsers();
    await user.click(screen.getByRole("button", { name: "Disable ada" }));

    expect(
      screen.getByRole("dialog", { name: "Disable your own account?" }),
    ).toHaveAccessibleDescription(
      "This signs you out at once and revokes the agent access you issued. Enabling the account later does not bring that access back.",
    );
    expect(writes).toEqual([]);
  });

  it("enables an account at once, as disabling it again undoes that", async () => {
    const { user, writes } = await renderUsers();
    await user.click(screen.getByRole("button", { name: "Enable carl" }));

    expect(await screen.findByText("carl is enabled")).toBeInTheDocument();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(writes).toEqual([{ userId: "user-3", body: { disabled: false } }]);
  });
});
