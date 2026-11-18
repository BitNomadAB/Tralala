import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { ToastProvider } from "@/components/ui/toast";
import { LoopKanban } from "@/features/loops/LoopKanban";
import type { Card } from "@/lib/types";
import { ticketCard } from "./msw/cards";
import { BOARD_ID, LOOP_ID } from "./msw/loops";
import { COLUMNS } from "./msw/ticketView";

const FIRST = ticketCard({ id: "card-1", title: "Rotate the signing key" });
const SECOND = ticketCard({ id: "card-2", title: "Expire idle sessions", ticket_key: null });

/** The Loop's columns with two cards in Backlog. */
function renderKanban(cardsByList: Record<string, Card[]> = { "list-1": [FIRST, SECOND] }) {
  const client = new QueryClient({ defaultOptions: { mutations: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <ToastProvider>
        <LoopKanban
          boardId={BOARD_ID}
          loopId={LOOP_ID}
          lists={COLUMNS}
          cardsByList={cardsByList}
          matchingIds={null}
          readOnly={false}
          onOpenCard={() => undefined}
          onListsChanged={() => undefined}
          onCardsChanged={() => undefined}
        >
          {null}
        </LoopKanban>
      </ToastProvider>
    </QueryClientProvider>,
  );
  return { user: userEvent.setup() };
}

/** dnd-kit's own live region, which reads the drag's announcements. */
function dragRegion(): HTMLElement {
  const region = document.querySelector<HTMLElement>('[id^="DndLiveRegion"]');
  if (!region) throw new Error("dnd-kit's live region is not in the page");
  return region;
}

describe("a drag with the keyboard", () => {
  it("tells how to move with the keys and names the Ticket and its place, not its id", async () => {
    const { user } = renderKanban();
    const backlog = screen.getByRole("region", { name: "Column Backlog" });
    const grip = within(backlog).getByRole("button", { name: "Move Expire idle sessions" });
    expect(grip).toHaveAccessibleDescription(/press Space or Enter on its grip to pick it up/);

    grip.focus();
    await user.keyboard(" ");
    // jsdom lays nothing out, so the card is over its neighbour at once; the text is what counts.
    await waitFor(() => {
      expect(dragRegion()).toHaveTextContent(
        /^Expire idle sessions is over Backlog, position \d of 2\.$/,
      );
    });

    await user.keyboard("{Escape}");
    await waitFor(() => {
      expect(dragRegion()).toHaveTextContent(
        "Moving Expire idle sessions was cancelled. It stays in Backlog, position 2 of 2.",
      );
    });
  });

  it("names a column by its name when its grip picks it up", async () => {
    const { user } = renderKanban();
    screen.getByRole("button", { name: "Reorder column In Progress" }).focus();
    await user.keyboard(" ");
    await waitFor(() => {
      expect(dragRegion()).toHaveTextContent(/^Column In Progress is over position \d of 3\.$/);
    });
    await user.keyboard("{Escape}");
    await waitFor(() => {
      expect(dragRegion()).toHaveTextContent(
        "Moving column In Progress was cancelled. It stays at position 2 of 3.",
      );
    });
  });
});
