import { screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ticketCard } from "./msw/cards";
import { kanbanHandlers, type KanbanServer } from "./msw/kanban";
import { LOOP_PATH } from "./msw/loops";
import { COLUMNS } from "./msw/ticketView";
import { renderLoopPage } from "./renderLoopPage";

async function renderBoard() {
  const server: KanbanServer = {
    lists: [...COLUMNS],
    cards: [ticketCard({ id: "card-1", title: "Rotate the signing key" })],
    writes: [],
  };
  const page = await renderLoopPage("", "in_progress", {}, kanbanHandlers(server));
  const backlog = await screen.findByRole("region", { name: "Column Backlog" });
  return { ...page, server, backlog };
}

describe("the focus after an inline form on the Kanban", () => {
  it("is back on Add card once a card is added, and after Escape or Cancel", async () => {
    const { user, server, backlog } = await renderBoard();
    const add = () => within(backlog).getByRole("button", { name: "Add card" });
    await user.click(add());
    await user.type(within(backlog).getByLabelText("New card in Backlog"), "Audit logins{Enter}");
    await waitFor(() => {
      expect(add()).toHaveFocus();
    });
    expect(server.writes).toContainEqual({
      route: `POST ${LOOP_PATH}/cards`,
      body: { list_id: "list-1", title: "Audit logins" },
    });

    await user.keyboard("{Enter}");
    await user.keyboard("{Escape}");
    expect(within(backlog).queryByLabelText("New card in Backlog")).not.toBeInTheDocument();
    expect(add()).toHaveFocus();

    await user.keyboard("{Enter}");
    await user.click(within(backlog).getByRole("button", { name: "Cancel" }));
    expect(add()).toHaveFocus();
  });

  it("is on the column's menu after a rename with Enter, or one cancelled with Escape", async () => {
    const { user, server, backlog } = await renderBoard();
    await user.click(within(backlog).getByRole("button", { name: "Column actions for Backlog" }));
    await user.click(screen.getByRole("menuitem", { name: "Rename column" }));
    await user.keyboard("{Escape}");
    expect(
      within(backlog).getByRole("button", { name: "Column actions for Backlog" }),
    ).toHaveFocus();
    expect(server.writes).toEqual([]);

    await user.keyboard("{Enter}");
    await user.click(screen.getByRole("menuitem", { name: "Rename column" }));
    const field = within(backlog).getByRole("textbox", { name: "Rename column Backlog" });
    await user.clear(field);
    await user.type(field, "Ideas{Enter}");
    const ideas = await screen.findByRole("region", { name: "Column Ideas" });
    expect(within(ideas).getByRole("button", { name: "Column actions for Ideas" })).toHaveFocus();
  });

  it("is on the next column's menu once a column is archived", async () => {
    const { user, backlog } = await renderBoard();
    await user.click(within(backlog).getByRole("button", { name: "Column actions for Backlog" }));
    await user.click(screen.getByRole("menuitem", { name: "Archive column" }));
    await waitFor(() => {
      expect(screen.queryByRole("region", { name: "Column Backlog" })).not.toBeInTheDocument();
    });
    await waitFor(() => {
      expect(screen.getByRole("button", { name: "Column actions for In Progress" })).toHaveFocus();
    });
  });

  it("is back on Add column once a column is added", async () => {
    const { user } = await renderBoard();
    await user.click(screen.getByRole("button", { name: "Add column" }));
    await user.type(screen.getByLabelText("New column name"), "Review{Enter}");
    expect(await screen.findByRole("region", { name: "Column Review" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Add column" })).toHaveFocus();
  });
});
