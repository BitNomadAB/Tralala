import { screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { renderLoopPage, TITLE } from "./renderLoopPage";

/** The card's title button on the Kanban: the button that opens the Ticket. */
async function cardTitle() {
  const backlog = await screen.findByRole("region", { name: "Column Backlog" });
  return within(backlog).findByRole("button", { name: TITLE });
}

describe("the focus around the Ticket dialog", () => {
  it("opens the Ticket with Enter on its card and gives the focus back to the card on Escape", async () => {
    const { user } = await renderLoopPage("", "in_progress", {});
    const title = await cardTitle();
    title.focus();
    await user.keyboard("{Enter}");
    const dialog = await screen.findByRole("dialog", { name: TITLE });
    await within(dialog).findByRole("button", { name: "Close dialog" });

    await user.keyboard("{Escape}");
    await waitFor(() => {
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    });
    await waitFor(() => {
      expect(title).toHaveFocus();
    });
  });

  it("puts the focus on the Ticket's card when a link opened the dialog", async () => {
    const { user } = await renderLoopPage("?card=card-1", "in_progress", {});
    const dialog = await screen.findByRole("dialog", { name: TITLE });
    await user.click(within(dialog).getByRole("button", { name: "Close dialog" }));
    await waitFor(() => {
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    });
    const title = await cardTitle();
    await waitFor(() => {
      expect(title).toHaveFocus();
    });
  });
});

describe("the board's activity panel", () => {
  it("takes the focus when it opens, closes on Escape and gives the focus back", async () => {
    const { header, user } = await renderLoopPage("", "in_progress", {});
    const actions = within(header).getByRole("button", { name: "Loop actions" });
    await user.click(actions);
    await user.click(screen.getByRole("menuitem", { name: "Board activity" }));

    const panel = screen.getByRole("complementary", { name: "Board activity" });
    // Beside the page, not fixed over it, so nothing the keyboard reaches hides behind it.
    expect(panel).not.toHaveClass("fixed");
    expect(within(panel).getByRole("heading", { name: "Activity" })).toHaveFocus();
    expect(await within(panel).findByText("No activity yet.")).toBeInTheDocument();

    await user.keyboard("{Escape}");
    expect(screen.queryByRole("complementary", { name: "Board activity" })).not.toBeInTheDocument();
    expect(actions).toHaveFocus();
  });

  it("gives the focus back from its close button too", async () => {
    const { header, user } = await renderLoopPage("", "in_progress", {});
    const actions = within(header).getByRole("button", { name: "Loop actions" });
    await user.click(actions);
    await user.click(screen.getByRole("menuitem", { name: "Board activity" }));
    await user.click(screen.getByRole("button", { name: "Close activity" }));
    expect(screen.queryByRole("complementary", { name: "Board activity" })).not.toBeInTheDocument();
    expect(actions).toHaveFocus();
  });
});
