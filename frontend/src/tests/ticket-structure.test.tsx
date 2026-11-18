import { screen, waitFor, within } from "@testing-library/react";
import { http } from "msw";
import { describe, expect, it } from "vitest";
import type { Checklist } from "@/lib/types";
import { CARD_ID, CARD_PATH, ticketCard } from "./msw/cards";
import { apiPath, ok } from "./msw/envelope";
import { BOARD_ID, NOW } from "./msw/loops";
import { server } from "./msw/server";
import { renderTicket, TICKET_URL, writes } from "./renderTicket";

const TITLE = "Rotate the signing key";

const CHECKLIST: Checklist = {
  id: "checklist-1",
  card_id: CARD_ID,
  title: "Before release",
  position: 0,
  items: [
    {
      id: "item-a",
      checklist_id: "checklist-1",
      text: "Tell support",
      completed: false,
      position: 0,
    },
    {
      id: "item-b",
      checklist_id: "checklist-1",
      text: "Write the note",
      completed: true,
      position: 1,
    },
  ],
};

/** The headings of `level` in the order they are on screen. */
function headings(level: number) {
  return screen.getAllByRole("heading", { level }).map((node) => node.textContent);
}

describe("the Ticket's structure", () => {
  it("keeps the dialog named by the title while the title is edited", async () => {
    const { user } = await renderTicket();
    await user.click(screen.getByRole("button", { name: TITLE }));
    expect(screen.getByRole("textbox", { name: "Title" })).toHaveFocus();
    expect(screen.getByRole("dialog", { name: TITLE })).toBeInTheDocument();
  });

  it("links Open as page, so it can also open in a new tab", async () => {
    await renderTicket();
    expect(screen.getByRole("link", { name: "Open as page" })).toHaveAttribute("href", TICKET_URL);
  });

  it("puts the sections one level under the title: h3 in the dialog", async () => {
    await renderTicket(ticketCard({ acceptance_criteria: ["It rotates"] }));
    expect(headings(2)).toEqual([TITLE]);
    expect(headings(3)).toEqual(
      expect.arrayContaining(["What will be done", "Files 0", "Activity", "Details", "Checklists"]),
    );
  });

  it("puts the sections one level under the title: h2 on the page, h3 for the raw blocks", async () => {
    const { user } = await renderTicket(
      ticketCard({ acceptance_criteria: ["It rotates"] }),
      TICKET_URL,
    );
    expect(headings(1)).toEqual([TITLE]);
    expect(headings(2)).toEqual(
      expect.arrayContaining(["What will be done", "Files 0", "Activity", "Details", "Checklists"]),
    );
    await user.click(screen.getByRole("tab", { name: "Raw text" }));
    const raw = screen.getByRole("tabpanel", { name: "Raw text" });
    expect(within(raw).getByRole("heading", { level: 3, name: "Accepted when" })).toBeVisible();
  });
});

describe("the due date", () => {
  it("keeps the editor open while Tab moves to Clear, and Clear removes the date", async () => {
    const { view, user } = await renderTicket(ticketCard({ due_at: "2026-12-01T00:00:00Z" }));
    await user.click(screen.getByRole("button", { name: /^Due: (?!None)/ }));
    expect(screen.getByLabelText("Due date")).toHaveFocus();
    await user.tab();
    const clear = screen.getByRole("button", { name: "Clear" });
    expect(clear).toHaveFocus();
    expect(screen.getByLabelText("Due date")).toBeInTheDocument();
    await user.keyboard("{Enter}");
    expect(await screen.findByRole("button", { name: "Due: None" })).toHaveFocus();
    expect(writes(view)).toEqual([
      { route: `PATCH ${CARD_PATH}`, body: { version: 3, clear_due_at: true } },
    ]);
  });

  it("closes once focus leaves both, and leaves the focus where it went", async () => {
    const { view, user } = await renderTicket(ticketCard({ due_at: "2026-12-01T00:00:00Z" }));
    await user.click(screen.getByRole("button", { name: /^Due: (?!None)/ }));
    await user.tab();
    await user.tab();
    expect(screen.queryByLabelText("Due date")).toBeNull();
    expect(screen.getByRole("button", { name: "Labels: None" })).toHaveFocus();
    expect(writes(view)).toEqual([]);
  });
});

describe("the checklists", () => {
  it("shows each item as a checkbox named by its text, ticked at once and saved", async () => {
    const { view, user } = await renderTicket(
      ticketCard({ checklists: [CHECKLIST], checklist_total: 2, checklist_completed: 1 }),
    );
    // The server holds its answer until the test lets it go, so the tick is seen before it.
    let answer: () => void = () => undefined;
    const held = new Promise<void>((resolve) => {
      answer = resolve;
    });
    const sent: unknown[] = [];
    server.use(
      http.patch(apiPath(`/boards/${BOARD_ID}/checklist-items/:itemId`), async ({ request }) => {
        sent.push(await request.json());
        await held;
        const items = CHECKLIST.items.map((item) => ({ ...item, completed: true }));
        view.state.card = { ...view.state.card, checklists: [{ ...CHECKLIST, items }] };
        return ok(items[0]);
      }),
    );
    await user.click(screen.getByText("More", { selector: "summary" }));
    const list = screen.getByRole("list", { name: "Before release" });
    const open = within(list).getByRole("checkbox", { name: "Tell support" });
    expect(open).not.toBeChecked();
    expect(within(list).getByRole("checkbox", { name: "Write the note" })).toBeChecked();
    await user.click(open);
    await waitFor(() => expect(open).toBeChecked());
    expect(open).toHaveFocus();
    expect(sent).toEqual([{ completed: true }]);
    answer();
    // The refetch after the answer brings the server's count.
    await waitFor(() => expect(list.parentElement).toHaveTextContent("Before release2/2"));
    expect(open).toBeChecked();
    expect(screen.getByRole("button", { name: "Add item to Before release" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Add checklist" })).toBeInTheDocument();
  });
});

describe("the face's counters", () => {
  it("say what a field needs, and describe the field with it", async () => {
    const { user } = await renderTicket(
      ticketCard({
        face: {
          summary: "Keys rotate.",
          why: "Leaks.",
          if_skipped: "Risk.",
          pros: [],
          cons: [],
          steps: ["One."],
        },
        summary: "Keys rotate.",
        updated_at: NOW,
      }),
    );
    await user.click(screen.getByRole("button", { name: "Edit what will be done" }));
    const form = screen.getByRole("form", { name: "Edit the face" });
    const steps = within(form).getByLabelText("What will be done");
    await user.clear(steps);
    expect(steps).toHaveAccessibleDescription(
      "One step per line. 0 of 5 steps, needs at least 1 step",
    );
  });
});
