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
