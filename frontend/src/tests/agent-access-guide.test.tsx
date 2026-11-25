import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { AgentAccessGuide } from "@/features/settings/AgentAccessGuide";

/** The guide opened, as a person reads it after pressing its summary. */
async function openGuide(token?: string) {
  const onCopy = vi.fn<(command: string) => void>();
  render(<AgentAccessGuide token={token} onCopy={onCopy} />);
  const user = userEvent.setup();
  const summary = screen.getByText("How do I connect my computer?");
  await user.click(summary);
  return {
    user,
    onCopy,
    guide: summary.closest("details"),
    command: screen.getByRole("group", { name: "Code block" }),
  };
}

/** The numbered step that opens with `title`. */
function step(title: string) {
  return screen.getByText(title).closest("li");
}

describe("the guide for connecting a computer", () => {
  it("shows the Claude Code command with the address and the key as placeholders", async () => {
    const { command } = await openGuide();
    expect(command).toHaveTextContent(
      'claude mcp add --transport http tralala https://<Your URL>/mcp --header "Authorization: Bearer <your-token>"',
    );
    expect(step("Add Tralala to Claude Code.")).toHaveTextContent(
      "run this command with https://<Your URL> replaced by the address you use to open Tralala and <your-token> by the token:",
    );
  });

  it("copies exactly the command it shows", async () => {
    const { user, onCopy, command } = await openGuide();
    await user.click(screen.getByRole("button", { name: "Copy this command" }));
    expect(onCopy).toHaveBeenCalledTimes(1);
    expect(onCopy).toHaveBeenCalledWith(command.textContent);
  });

  it("fills in a token it was given, and copies that", async () => {
    const { user, onCopy, command } = await openGuide("trl_issued_123");
    expect(command).toHaveTextContent('--header "Authorization: Bearer trl_issued_123"');
    expect(step("Add Tralala to Claude Code.")).not.toHaveTextContent("<your-token>");
    await user.click(screen.getByRole("button", { name: "Copy this command" }));
    expect(onCopy).toHaveBeenCalledWith(command.textContent);
  });

  it("says which revision a client must speak and no longer points at VS Code", async () => {
    const { guide } = await openGuide();
    expect(step("Add Tralala to Claude Code.")).toHaveTextContent(
      "Your agent must speak MCP 2026-07-28: Tralala speaks that revision of the Model Context Protocol and no older one.",
    );
    expect(guide).toHaveTextContent(
      "The endpoint is <Your URL>/mcp and speaks MCP 2026-07-28 alone",
    );
    expect(guide).not.toHaveTextContent(/VS Code|mcp\.json|"servers"/);
  });

  it("says what 401 and 403 mean, and that a missing scope is an error in the answer", async () => {
    await openGuide();
    const check = step("Check that it works.");
    expect(check).toHaveTextContent("401 means the token is wrong, revoked or expired;");
    expect(check).toHaveTextContent(
      "403 means the request carried an Origin header that Tralala does not trust.",
    );
    expect(check).toHaveTextContent(
      "a call to one comes back with the error Missing required scope: … in its answer, not with a 403.",
    );
    expect(check).not.toHaveTextContent("missing a scope");
  });
});
