import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http } from "msw";
import type { ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";
import { ToastProvider } from "@/components/ui/toast";
import { LoopCompletionDialog } from "@/features/loops/LoopCompletionDialog";
import { LoopEditDialog } from "@/features/loops/LoopEditDialog";
import { ResetPasswordDialog } from "@/features/settings/ResetPasswordDialog";
import type { UserAccount } from "@/lib/types";
import { apiPath, failure, ok } from "./msw/envelope";
import { BOARD_ID, LOOP, LOOP_PATH } from "./msw/loops";
import { server } from "./msw/server";
import { READINESS } from "./msw/ticketView";

function renderWith(node: ReactNode) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  render(
    <QueryClientProvider client={client}>
      <ToastProvider>{node}</ToastProvider>
    </QueryClientProvider>,
  );
  return userEvent.setup();
}

/** Holds the answer to `method path` until the returned function is called. */
function hold(method: "post" | "patch", path: string, body: unknown = {}) {
  let release: () => void = () => undefined;
  const held = new Promise<void>((resolve) => {
    release = resolve;
  });
  server.use(
    http[method](apiPath(path), async () => {
      await held;
      return ok(body);
    }),
  );
  return () => {
    release();
  };
}

/** The button keeps the focus and reads as unavailable while its request runs (WCAG 2.4.3). */
function expectHeld(button: HTMLElement) {
  expect(button).toHaveFocus();
  expect(button).toHaveAttribute("aria-disabled", "true");
  expect(button).not.toBeDisabled();
}

const ADA: UserAccount = {
  id: "user-ada",
  name: "Ada Lovelace",
  role: "member",
  created_at: "2026-11-01T09:00:00Z",
  disabled: false,
  agent_access_count: 0,
  agent_access_last_used_at: null,
};

describe("a dialog's button while its request runs", () => {
  it("keeps the focus on Save in Edit Loop", async () => {
    const release = hold("patch", LOOP_PATH, LOOP);
    const onClose = vi.fn<() => void>();
    const user = renderWith(
      <LoopEditDialog
        boardId={BOARD_ID}
        loop={LOOP}
        onClose={onClose}
        onChanged={() => undefined}
      />,
    );
    await user.click(screen.getByRole("button", { name: "Save" }));
    expectHeld(screen.getByRole("button", { name: "Saving…" }));
    release();
    await waitFor(() => expect(onClose).toHaveBeenCalled());
  });

  it("keeps the focus on Accept implementation", async () => {
    server.use(http.get(apiPath(`${LOOP_PATH}/readiness`), () => ok(READINESS)));
    const release = hold("post", `${LOOP_PATH}/completion`);
    const user = renderWith(
      <LoopCompletionDialog
        boardId={BOARD_ID}
        loop={{ ...LOOP, stage: "in_progress" }}
        open
        isHuman
        onClose={() => undefined}
        onChanged={() => undefined}
      />,
    );
    const accept = screen.getByRole("button", { name: "Accept implementation" });
    await user.click(accept);
    expectHeld(accept);
    release();
    expect(await screen.findByText("Implementation accepted")).toBeInTheDocument();
  });
});

describe("resetting someone's password", () => {
  function renderReset() {
    const onClose = vi.fn<() => void>();
    const user = renderWith(<ResetPasswordDialog user={ADA} onClose={onClose} />);
    const field = screen.getByLabelText(/New password/);
    return { user, onClose, field };
  }

  it("says what a short password needs without sending it", async () => {
    const { user, field } = renderReset();
    await user.type(field, "short");
    await user.click(screen.getByRole("button", { name: "Reset password" }));
    expect(field).toHaveAttribute("aria-invalid", "true");
    expect(field).toHaveFocus();
  });

  it("keeps the focus on Reset password while it is saved, then closes and says so", async () => {
    const release = hold("post", `/users/${ADA.id}/password`);
    const { user, onClose, field } = renderReset();
    await user.type(field, "a long enough password");
    const reset = screen.getByRole("button", { name: "Reset password" });
    await user.click(reset);
    expectHeld(reset);
    release();
    expect(await screen.findByText("Password reset")).toBeInTheDocument();
    expect(onClose).toHaveBeenCalled();
  });

  it("shows the server's password rule at the field, and any other refusal as a toast", async () => {
    let answer = failure(422, "validation_failed", "The password is too common.");
    server.use(http.post(apiPath(`/users/${ADA.id}/password`), () => answer));
    const { user, onClose, field } = renderReset();
    await user.type(field, "password1234");
    await user.click(screen.getByRole("button", { name: "Reset password" }));
    expect(await screen.findByText("The password is too common.")).toBeInTheDocument();
    expect(field).toHaveAttribute("aria-invalid", "true");

    answer = failure(403, "forbidden", "Only an administrator may do this.");
    await user.click(screen.getByRole("button", { name: "Reset password" }));
    expect(await screen.findByText("Could not reset the password")).toBeInTheDocument();
    expect(onClose).not.toHaveBeenCalled();
  });
});
