import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";
import { ToastProvider } from "@/components/ui/toast";
import { invitationLink } from "@/features/settings/invitation";
import { InvitationDialog } from "@/features/settings/InvitationDialog";
import { IssuedTokenDialog } from "@/features/settings/IssuedTokenDialog";
import type { Credential, InviteCreated } from "@/lib/types";

const TOKEN = "trl_issued-once-0123456789";

const ISSUED: Credential = {
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
  token: TOKEN,
};

const INVITE: InviteCreated = {
  user_id: "user-2",
  user_name: "ada member",
  token: "invite-token",
  path: "/enrol?token=invite-token",
  expires_at: "2026-11-20T09:00:00Z",
  warning: "",
};

/** The token dialog as a page holds it: open until it closes itself. */
function TokenHost() {
  const [issued, setIssued] = useState<Credential | null>(ISSUED);
  return (
    <>
      <IssuedTokenDialog issued={issued} onClose={() => setIssued(null)} />
      {issued ? null : <p>Closed</p>}
    </>
  );
}

function renderToken() {
  const user = userEvent.setup();
  render(
    <ToastProvider>
      <TokenHost />
    </ToastProvider>,
  );
  const dialog = screen.getByRole("dialog", { name: "Copy this token now" });
  return { user, dialog, field: within(dialog).getByLabelText("New API token") };
}

describe("the dialog that shows a new token once", () => {
  it("opens on the token with all of it selected, not on Close", () => {
    const { field } = renderToken();

    expect(field).toHaveFocus();
    expect(field).toHaveValue(TOKEN);
    if (!(field instanceof HTMLInputElement)) throw new Error("the token is not in an input");
    expect([field.selectionStart, field.selectionEnd]).toEqual([0, TOKEN.length]);
  });

  it("asks before Escape closes a token that was not copied, and keeps it open on request", async () => {
    const { user, dialog, field } = renderToken();

    await user.keyboard("{Escape}");
    const question = within(dialog).getByRole("group", {
      name: "You have not copied the token. Close anyway?",
    });
    expect(within(question).getByRole("button", { name: "Keep open" })).toHaveFocus();

    await user.click(within(question).getByRole("button", { name: "Keep open" }));
    expect(within(dialog).queryByRole("group", { name: /Close anyway/ })).toBeNull();
    expect(field).toHaveFocus();

    // Done asks too, and Close anyway closes for good.
    await user.click(within(dialog).getByRole("button", { name: "Done" }));
    await user.click(within(dialog).getByRole("button", { name: "Close anyway" }));
    expect(await screen.findByText("Closed")).toBeInTheDocument();
  });

  it("asks when the header's Close is pressed too", async () => {
    const { user, dialog } = renderToken();

    await user.click(within(dialog).getByRole("button", { name: "Close dialog" }));
    expect(within(dialog).getByText("You have not copied the token. Close anyway?")).toBeVisible();
  });

  it("closes without asking once the token was copied", async () => {
    const { user, dialog } = renderToken();

    await user.click(within(dialog).getByRole("button", { name: "Copy token" }));
    expect(await screen.findByText("Token copied")).toBeInTheDocument();
    expect(await navigator.clipboard.readText()).toBe(TOKEN);

    await user.click(within(dialog).getByRole("button", { name: "Done" }));
    expect(await screen.findByText("Closed")).toBeInTheDocument();
  });

  it("counts a copy the person made themselves", async () => {
    const { user, field } = renderToken();

    fireEvent.copy(field);
    await user.keyboard("{Escape}");
    expect(await screen.findByText("Closed")).toBeInTheDocument();
  });

  it("says when the browser did not copy, and selects the token to copy by hand", async () => {
    const { user, dialog, field } = renderToken();
    vi.spyOn(navigator.clipboard, "writeText").mockRejectedValue(new Error("not allowed"));

    await user.click(within(dialog).getByRole("button", { name: "Copy token" }));

    await waitFor(() =>
      expect(field).toHaveAccessibleDescription(
        "The browser did not copy the token. Select the text and press Ctrl+C.",
      ),
    );
    expect(field).toHaveFocus();
    expect(screen.queryByText("Token copied")).not.toBeInTheDocument();
    // Still not copied, so closing still asks.
    await user.click(within(dialog).getByRole("button", { name: "Done" }));
    expect(within(dialog).getByRole("button", { name: "Close anyway" })).toBeInTheDocument();
  });
});

describe("the invitation link dialog", () => {
  it("names the account in the link and says Link copied only when it was", async () => {
    const user = userEvent.setup();
    render(
      <ToastProvider>
        <InvitationDialog invited={INVITE} onClose={() => undefined} />
      </ToastProvider>,
    );
    const dialog = screen.getByRole("dialog", { name: "Invitation link for ada member" });
    const field = within(dialog).getByLabelText("Link");
    expect(field).toHaveFocus();
    expect(field).toHaveValue(
      `${window.location.origin}/enrol?token=invite-token&user=ada%20member`,
    );

    vi.spyOn(navigator.clipboard, "writeText").mockRejectedValueOnce(new Error("not allowed"));
    await user.click(within(dialog).getByRole("button", { name: "Copy link" }));
    await waitFor(() =>
      expect(field).toHaveAccessibleDescription(
        "The browser did not copy the link. Select the text and press Ctrl+C.",
      ),
    );
    expect(screen.queryByText("Link copied")).not.toBeInTheDocument();

    await user.click(within(dialog).getByRole("button", { name: "Copy link" }));
    expect(await screen.findByText("Link copied")).toBeInTheDocument();
    expect(field).toHaveAccessibleDescription("Shown once; a new link replaces it.");
  });

  it("builds the link from the server's path and the account's name", () => {
    expect(invitationLink("https://tralala.example", INVITE)).toBe(
      "https://tralala.example/enrol?token=invite-token&user=ada%20member",
    );
    expect(invitationLink("https://tralala.example", { ...INVITE, path: "/enrol" })).toBe(
      "https://tralala.example/enrol?user=ada%20member",
    );
  });
});
