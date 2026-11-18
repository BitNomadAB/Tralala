import { screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { announcer } from "./announcer";
import { ticketCard } from "./msw/cards";
import { kanbanHandlers, type KanbanServer } from "./msw/kanban";
import { LOOP_PATH } from "./msw/loops";
import { COLUMNS } from "./msw/ticketView";
import { renderLoopPage } from "./renderLoopPage";

/** Backlog holds two Tickets; In Progress and Done are empty. */
function board(): KanbanServer {
  return {
    lists: [...COLUMNS],
    cards: [
      ticketCard({ id: "card-1", title: "Rotate the signing key" }),
      ticketCard({ id: "card-2", title: "Expire idle sessions", ticket_key: "SES-1-PH01-002" }),
    ],
    writes: [],
  };
}

async function renderBoard() {
  const server = board();
  const page = await renderLoopPage("", "in_progress", {}, kanbanHandlers(server));
  const column = (name: string) => screen.findByRole("region", { name: `Column ${name}` });
  return { ...page, server, column };
}

/** The titles of a column's cards, top to bottom. */
function titles(column: HTMLElement): (string | null)[] {
  return within(column)
    .queryAllByRole("button")
    .filter((button) => button.hasAttribute("data-ticket-open"))
    .map((button) => button.textContent);
}

describe("moving a card from its menu", () => {
  it("moves it up in its column, says where, and keeps the focus on its menu", async () => {
    const { user, server, column } = await renderBoard();
    const backlog = await column("Backlog");
    await user.click(
      await within(backlog).findByRole("button", { name: "Actions for Expire idle sessions" }),
    );
    // A move that would not move it stays in the menu and says why.
    expect(
      screen.getByRole("menuitem", { name: "Move down: Already at the bottom" }),
    ).toHaveAttribute("aria-disabled", "true");
    await user.click(screen.getByRole("menuitem", { name: "Move up" }));

    expect(titles(backlog)).toEqual(["Expire idle sessions", "Rotate the signing key"]);
    await waitFor(() => {
      expect(server.writes).toContainEqual({
        route: `POST ${LOOP_PATH}/cards/card-2/move`,
        body: { version: 3, list_id: "list-1", position: 0 },
      });
    });
    await waitFor(() => {
      expect(announcer()).toHaveTextContent(
        "Expire idle sessions moved to Backlog, position 1 of 2.",
      );
    });
    expect(
      within(backlog).getByRole("button", { name: "Actions for Expire idle sessions" }),
    ).toHaveFocus();
  });

  it("moves it to the end of another column, with the focus on its menu there", async () => {
    const { user, server, column } = await renderBoard();
    const backlog = await column("Backlog");
    await user.click(
      await within(backlog).findByRole("button", { name: "Actions for Rotate the signing key" }),
    );
    await user.click(screen.getByRole("menuitem", { name: "Move to In Progress" }));

    const progress = await column("In Progress");
    await waitFor(() => {
      expect(titles(progress)).toEqual(["Rotate the signing key"]);
    });
    expect(titles(backlog)).toEqual(["Expire idle sessions"]);
    await waitFor(() => {
      expect(
        within(progress).getByRole("button", { name: "Actions for Rotate the signing key" }),
      ).toHaveFocus();
    });
    expect(server.writes).toContainEqual({
      route: `POST ${LOOP_PATH}/cards/card-1/move`,
      body: { version: 3, list_id: "list-2", position: 0 },
    });
    await waitFor(() => {
      expect(announcer()).toHaveTextContent(
        "Rotate the signing key moved to In Progress, position 1 of 1.",
      );
    });
  });
});

describe("moving a column from its menu", () => {
  it("moves it right, says where, and keeps the focus on its menu", async () => {
    const { user, server, column } = await renderBoard();
    const backlog = await column("Backlog");
    await user.click(within(backlog).getByRole("button", { name: "Column actions for Backlog" }));
    expect(
      screen.getByRole("menuitem", { name: "Move left: Already the first column" }),
    ).toHaveAttribute("aria-disabled", "true");
    await user.click(screen.getByRole("menuitem", { name: "Move right" }));

    await waitFor(() => {
      expect(
        screen.getAllByRole("region", { name: /^Column / }).map((region) => region.ariaLabel),
      ).toEqual(["Column In Progress", "Column Backlog", "Column Done"]);
    });
    expect(server.writes).toContainEqual({
      route: `POST ${LOOP_PATH}/lists/list-1/move`,
      body: { position: 1 },
    });
    await waitFor(() => {
      expect(announcer()).toHaveTextContent("Column Backlog moved to position 2 of 3.");
    });
    await waitFor(() => {
      expect(screen.getByRole("button", { name: "Column actions for Backlog" })).toHaveFocus();
    });
  });
});
