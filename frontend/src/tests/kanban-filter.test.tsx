import { screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { emptyColumnText, matchText } from "@/features/loops/useLoopCards";
import { announcer } from "./announcer";
import { ticketCard } from "./msw/cards";
import { kanbanHandlers } from "./msw/kanban";
import { COLUMNS } from "./msw/ticketView";
import { renderLoopPage } from "./renderLoopPage";

describe("the Kanban's filter in words", () => {
  it("counts the matches and says what an empty column means", () => {
    expect([0, 1, 4].map(matchText)).toEqual([
      "No Tickets match",
      "1 Ticket matches",
      "4 Tickets match",
    ]);
    expect(emptyColumnText(false, null)).toBe("Drop cards here");
    expect(emptyColumnText(true, null)).toBe("Filtering…");
    expect(emptyColumnText(true, 0)).toBe("No Tickets match the filter");
  });
});

describe("filtering the Kanban", () => {
  it("shows and says how many Tickets match, and why a column is empty", async () => {
    const server = {
      lists: [...COLUMNS],
      cards: [
        ticketCard({ id: "card-1", title: "Rotate the signing key" }),
        ticketCard({ id: "card-2", title: "Expire idle sessions" }),
      ],
      writes: [],
    };
    const { user } = await renderLoopPage("", "in_progress", {}, kanbanHandlers(server));
    const progress = await screen.findByRole("region", { name: "Column In Progress" });
    expect(within(progress).getByText("Drop cards here")).toBeInTheDocument();

    await user.type(screen.getByRole("textbox", { name: "Filter tickets" }), "rotate");
    expect(await screen.findByText("1 Ticket matches")).toBeVisible();
    await waitFor(() => {
      expect(announcer()).toHaveTextContent("1 Ticket matches");
    });
    expect(within(progress).getByText("No Tickets match the filter")).toBeInTheDocument();
    const backlog = screen.getByRole("region", { name: "Column Backlog" });
    expect(within(backlog).getByRole("button", { name: "Rotate the signing key" })).toBeVisible();
    expect(within(backlog).queryByText("Expire idle sessions")).not.toBeInTheDocument();
  });
});

describe("moving a card from its menu while the Kanban is filtered", () => {
  it("offers only the moves to another column, and says where without hidden cards", async () => {
    const server = {
      lists: [...COLUMNS],
      cards: [
        ticketCard({ id: "card-1", title: "Rotate the signing key" }),
        ticketCard({ id: "card-2", title: "Expire idle sessions" }),
        ticketCard({ id: "card-3", title: "Rotate the backup key" }),
      ],
      writes: [],
    };
    const { user } = await renderLoopPage("", "in_progress", {}, kanbanHandlers(server));
    await user.type(screen.getByRole("textbox", { name: "Filter tickets" }), "rotate");
    expect(await screen.findByText("2 Tickets match")).toBeVisible();
    const backlog = screen.getByRole("region", { name: "Column Backlog" });
    await waitFor(() => {
      expect(within(backlog).queryByText("Expire idle sessions")).not.toBeInTheDocument();
    });

    await user.click(
      within(backlog).getByRole("button", { name: "Actions for Rotate the backup key" }),
    );
    // Up would swap it with a card the filter hides: the order is changed without the filter.
    for (const name of ["Move up", "Move down", "Move to top", "Move to bottom"]) {
      expect(
        screen.getByRole("menuitem", { name: `${name}: Clear the filter to reorder` }),
      ).toHaveAttribute("aria-disabled", "true");
    }
    await user.click(screen.getByRole("menuitem", { name: "Move to In Progress" }));

    await waitFor(() => {
      expect(announcer()).toHaveTextContent(
        "Rotate the backup key moved to the end of In Progress.",
      );
    });
    expect(server.writes).toContainEqual({
      route: expect.stringContaining("/cards/card-3/move") as unknown,
      body: { version: 3, list_id: "list-2", position: 0 },
    });
  });
});
