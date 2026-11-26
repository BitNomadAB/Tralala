import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http } from "msw";
import type { ReactNode } from "react";
import { describe, expect, it } from "vitest";
import { ToastProvider } from "@/components/ui/toast";
import { NewAccessDialog } from "@/features/settings/NewAccessDialog";
import { NewUserDialog } from "@/features/settings/NewUserDialog";
import { apiPath, failure } from "./msw/envelope";
import { server } from "./msw/server";

function renderWithClient(ui: ReactNode) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  render(
    <QueryClientProvider client={client}>
      <ToastProvider>{ui}</ToastProvider>
    </QueryClientProvider>,
  );
  return userEvent.setup();
}

const renderNewUser = () => renderWithClient(<NewUserDialog open onOpenChange={() => undefined} />);

const renderNewAccess = () =>
  renderWithClient(
    <NewAccessDialog
      open
      onOpenChange={() => undefined}
      isAdmin={false}
      scopeChoices={["boards:read", "cards:read"]}
      offerDecide={false}
      defaultExpiry="30"
      expiryHint="Expires after 30 days."
      onIssued={() => undefined}
    />,
  );

describe("the new user form", () => {
  it("keeps Create user enabled and says what is missing under each field", async () => {
    const user = renderNewUser();

    const button = screen.getByRole("button", { name: "Create user" });
    expect(button).toBeEnabled();
    await user.click(button);

    const name = screen.getByLabelText("Username");
    await waitFor(() => expect(name).toHaveFocus());
    expect(name).toHaveAccessibleDescription("Error: Enter a username.");
    expect(screen.getByLabelText("Initial password")).toHaveAccessibleDescription(
      "Error: Use at least 8 characters. At least 8 characters.",
    );
  });

  it("says a taken name under the username", async () => {
    server.use(
      http.post(apiPath("/users"), () =>
        failure(409, "conflict", "A user with this name already exists", { name: "ada" }),
      ),
    );
    const user = renderNewUser();

    await user.type(screen.getByLabelText("Username"), "ada");
    await user.type(screen.getByLabelText("Initial password"), "placeholder-123");
    await user.click(screen.getByRole("button", { name: "Create user" }));

    const name = screen.getByLabelText("Username");
    await waitFor(() => expect(name).toHaveFocus());
    expect(name).toHaveAttribute("aria-invalid", "true");
    expect(name).toHaveAccessibleDescription("Error: A user with this name already exists.");
    expect(screen.queryByText("Could not create the user")).not.toBeInTheDocument();
  });
});

describe("the new agent access form", () => {
  it("says a missing name and an empty scope list, and focuses the name first", async () => {
    const user = renderNewAccess();

    await user.click(screen.getByRole("checkbox", { name: "boards:read" }));
    await user.click(screen.getByRole("checkbox", { name: "cards:read" }));
    await user.click(screen.getByRole("button", { name: "Create access" }));

    const name = screen.getByLabelText("Agent name");
    await waitFor(() => expect(name).toHaveFocus());
    expect(name).toHaveAccessibleDescription(
      "Error: Name the agent access. Name it after the machine that will hold the key.",
    );
    expect(screen.getByRole("group", { name: "Scopes" })).toHaveAccessibleDescription(
      "Error: Choose at least one scope.",
    );

    await user.type(name, "laptop");
    await user.click(screen.getByRole("button", { name: "Create access" }));
    await waitFor(() =>
      expect(screen.getByRole("checkbox", { name: "boards:read" })).toHaveFocus(),
    );
  });

  it("says a refused expiry under the expiry field", async () => {
    server.use(
      http.post(apiPath("/credentials"), () =>
        failure(422, "expiry_required", "A personal agent access needs an expiry date", {
          max_days: 365,
        }),
      ),
    );
    const user = renderNewAccess();

    await user.type(screen.getByLabelText("Agent name"), "laptop");
    await user.clear(screen.getByLabelText("Expires in days"));
    await user.click(screen.getByRole("button", { name: "Create access" }));

    const expiry = screen.getByLabelText("Expires in days");
    await waitFor(() => expect(expiry).toHaveFocus());
    expect(expiry).toHaveAccessibleDescription(
      "Error: A personal agent access needs an expiry date. Expires after 30 days.",
    );
  });
});
