import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it } from "vitest";
import { ToastProvider } from "@/components/ui/toast";
import { AuthProvider } from "@/features/auth/AuthProvider";
import { SecurityCard } from "@/features/settings/SecurityCard";
import { server } from "./msw/server";
import { MEMBER_PASSWORD, memberSession } from "./msw/session";

let session: ReturnType<typeof memberSession>["state"];

beforeEach(() => {
  const member = memberSession();
  session = member.state;
  server.use(...member.handlers);
});

function renderCard() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  render(
    <QueryClientProvider client={client}>
      <ToastProvider>
        <AuthProvider>
          <SecurityCard />
        </AuthProvider>
      </ToastProvider>
    </QueryClientProvider>,
  );
  return userEvent.setup();
}

const changes = () => session.requests.filter((entry) => entry === "POST /auth/password");

describe("changing your password", () => {
  it("keeps the button enabled, checks on submit and moves focus to the first problem", async () => {
    const user = renderCard();

    await user.type(screen.getByLabelText("Current password"), MEMBER_PASSWORD);
    await user.type(screen.getByLabelText("New password"), "short");
    const button = screen.getByRole("button", { name: "Change password" });
    expect(button).toBeEnabled();
    await user.click(button);

    const next = screen.getByLabelText("New password");
    await waitFor(() => expect(next).toHaveFocus());
    expect(next).toHaveAttribute("aria-invalid", "true");
    expect(next).toHaveAccessibleDescription(
      "Error: Use at least 8 characters. At least 8 characters.",
    );
    expect(screen.getByLabelText("Repeat new password")).toHaveAccessibleDescription(
      "Error: Repeat the password.",
    );
    expect(screen.getByLabelText("Current password")).not.toHaveAttribute("aria-invalid");
    expect(changes()).toEqual([]);
  });

  it("says a mismatch only once the repeat field is left, and drops it when they match", async () => {
    const user = renderCard();

    await user.type(screen.getByLabelText("New password"), "new-password-2");
    const repeat = screen.getByLabelText("Repeat new password");
    await user.type(repeat, "new-pass");
    expect(repeat).not.toHaveAttribute("aria-invalid");

    await user.tab();
    expect(repeat).toHaveAccessibleDescription("Error: The two passwords do not match.");

    await user.type(repeat, "word-2");
    expect(repeat).not.toHaveAttribute("aria-invalid");
    expect(repeat).not.toHaveAccessibleDescription();
  });

  it("says a wrong current password under that field and moves focus there", async () => {
    const user = renderCard();

    await user.type(screen.getByLabelText("Current password"), "not-my-password");
    await user.type(screen.getByLabelText("New password"), "new-password-2");
    await user.type(screen.getByLabelText("Repeat new password"), "new-password-2");
    await user.click(screen.getByRole("button", { name: "Change password" }));

    const current = screen.getByLabelText("Current password");
    await waitFor(() => expect(current).toHaveFocus());
    expect(current).toHaveAttribute("aria-invalid", "true");
    expect(current).toHaveAccessibleDescription("Error: Current password is incorrect.");
    // Said at the field, so not once more in a toast.
    expect(screen.queryByText("Could not change the password")).not.toBeInTheDocument();
    expect(changes()).toHaveLength(1);
    expect(session.signedIn).toBe(true);
  });
});
