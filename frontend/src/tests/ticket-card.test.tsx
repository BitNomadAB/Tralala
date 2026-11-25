import { DndContext } from "@dnd-kit/core";
import { SortableContext } from "@dnd-kit/sortable";
import { fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { TicketCard } from "@/features/loops/TicketCard";
import type { Card, TicketFace } from "@/lib/types";
import { formatDate } from "@/lib/utils";
import { ticketCard } from "./msw/cards";

/** When a key took the Ticket, and what the mark says counts as a report. */
const TAKEN = "2026-11-25T10:00:00Z";
const REPORT = "A comment, a wait or a completion is a report.";

const FACE: TicketFace = {
  summary: "Sessions end after 30 idle minutes.",
  why: "Idle sessions stay open for days.",
  if_skipped: "A lost laptop stays signed in.",
  pros: ["Safer"],
  cons: ["People sign in more often"],
  steps: ["End a session after 30 idle minutes"],
};

/**
 * The card on a Kanban column, as the board renders it: sortable, with an open handler, in a Loop
 * with a plan unless `withoutPlan`.
 */
function renderCard(card: Card, withoutPlan = false) {
  const onOpen = vi.fn();
  render(
    <DndContext>
      <SortableContext items={[card.id]}>
        <ul>
          <TicketCard card={card} onOpen={onOpen} withoutPlan={withoutPlan} />
        </ul>
      </SortableContext>
    </DndContext>,
  );
  return { onOpen, item: screen.getByRole("listitem") };
}

describe("the Kanban card", () => {
  it("shows the title, the face's summary, the key and the owner, and no state when ready", () => {
    const { onOpen, item } = renderCard(
      ticketCard({
        face: FACE,
        summary: "The stored summary.",
        assignee_actor_id: "actor-ada",
        assignee_type: "user",
        assignee_name: "Ada Lovelace",
      }),
    );
    const title = within(item).getByRole("button", { name: "Rotate the signing key" });
    expect(title).toHaveClass("line-clamp-2", "text-base", "font-semibold");
    const summary = within(item).getByText(FACE.summary);
    expect(summary).toHaveClass("line-clamp-2");
    expect(within(item).queryByText("The stored summary.")).not.toBeInTheDocument();
    // The key stands out from the quiet row it sits in: bold, in the text's own colour.
    expect(within(item).getByText("SES-1-PH01-001")).toHaveClass(
      "font-mono",
      "font-semibold",
      "text-[var(--foreground)]",
    );
    expect(within(item).getByRole("img", { name: "Owner: Ada Lovelace" })).toHaveTextContent("AL");
    for (const word of ["Ready", "Needs input", "Blocked", "done", "Needs a person"]) {
      expect(within(item).queryByText(word)).not.toBeInTheDocument();
    }
    // A click, not a pointer gesture: the board's pointer sensor waits for 4 px before it drags,
    // which the bare DndContext here does not.
    fireEvent.click(title);
    expect(onOpen).toHaveBeenCalledTimes(1);
  });

  it("opens the Ticket with Enter on the title; the grip beside it is the keyboard's drag handle", async () => {
    const user = userEvent.setup();
    const { onOpen, item } = renderCard(ticketCard());
    const title = within(item).getByRole("button", { name: "Rotate the signing key" });
    const grip = within(item).getByRole("button", { name: "Move Rotate the signing key" });
    expect(title).not.toHaveAttribute("aria-roledescription");
    expect(grip).toHaveAttribute("aria-roledescription", "sortable");

    title.focus();
    await user.keyboard("{Enter}");
    expect(onOpen).toHaveBeenCalledTimes(1);
    expect(grip).not.toHaveAttribute("aria-pressed", "true");

    // Tab goes from the title to its grip; Space there picks the card up instead of opening it.
    await user.tab();
    expect(grip).toHaveFocus();
    await user.keyboard(" ");
    expect(grip).toHaveAttribute("aria-pressed", "true");
    await user.keyboard("{Escape}");
    expect(grip).not.toHaveAttribute("aria-pressed", "true");
    expect(onOpen).toHaveBeenCalledTimes(1);
  });

  it("falls back to the stored summary, and shows none when there is none", () => {
    const { item, onOpen } = renderCard(ticketCard({ summary: "The stored summary." }));
    expect(within(item).getByText("The stored summary.")).toBeInTheDocument();
    expect(onOpen).not.toHaveBeenCalled();
  });

  it("shows Blocked as a small pill with what holds it up", () => {
    renderCard(
      ticketCard({
        ready: false,
        state: "blocked",
        blockers: [{ type: "ticket", id: "card-0", key: "SES-1-PH01-000", reason: "prerequisite" }],
      }),
    );
    const blocked = screen.getByText("Blocked").parentElement;
    expect(blocked).toHaveClass("rounded-full", "border");
    expect(blocked).toHaveAttribute("title", "SES-1-PH01-000");
    expect(blocked).toHaveTextContent("Blocked: SES-1-PH01-000");
  });

  it("shows Needs input with the reason of the wait", () => {
    renderCard(
      ticketCard({ state: "needs_input", waiting_for: "decision", waiting_reason: "Which TTL?" }),
    );
    const held = screen.getByText("Needs input").parentElement;
    expect(held).toHaveAttribute("title", "Which TTL?");
    expect(held).toHaveTextContent("Needs input: Which TTL?");
    expect(screen.queryByText("Blocked")).not.toBeInTheDocument();
  });

  it("shows Not done on a Ticket its Loop was closed without, and asks no person for it", () => {
    renderCard(
      ticketCard({
        state: "not_done",
        human_action_required: true,
        waiting_for: "decision",
        waiting_reason: "Which TTL?",
      }),
    );
    const left = screen.getByText("Not done").parentElement;
    expect(left).toHaveClass("rounded-full", "border");
    // The reason is that the Loop was closed, not the wait it had then.
    expect(left).toHaveTextContent("Not done: The Loop was closed before this Ticket was done.");
    expect(screen.queryByText("Needs a person")).not.toBeInTheDocument();
    expect(screen.queryByText("done", { exact: true })).not.toBeInTheDocument();
  });

  it("says what Unplanned means in its text, not only on hover", () => {
    renderCard(ticketCard({ kind: "manual", ticket_key: "SES-1-UNP-001" }));
    const unplanned = screen.getByText("Unplanned").parentElement;
    expect(unplanned).toHaveAttribute("title", expect.stringMatching(/^Added outside the plan/));
    expect(unplanned).toHaveTextContent(
      "Unplanned: Added outside the plan; it never blocks the plan or the Loop's completion",
    );
  });

  it("marks no Ticket of a Loop without a plan Unplanned, and keeps its key", () => {
    const { item } = renderCard(ticketCard({ kind: "manual", ticket_key: "SES-1-UNP-001" }), true);
    expect(within(item).getByText("SES-1-UNP-001")).toBeInTheDocument();
    expect(within(item).queryByText("Unplanned")).not.toBeInTheDocument();
    expect(within(item).queryByText(/Added outside the plan/)).not.toBeInTheDocument();
  });

  it("says No report in words while a key that took it has not reported, with when and why", () => {
    renderCard(ticketCard({ list_id: "list-2", unreported_since: TAKEN }));
    const reason = `Taken by a key on ${formatDate(TAKEN)}. ${REPORT}`;
    const mark = screen.getByText("No report", { exact: true }).parentElement;
    expect(mark).toHaveClass("rounded-full", "border");
    expect(mark).toHaveAttribute("title", reason);
    // What the hover says is in the text for a screen reader too; the dot only repeats the word.
    expect(mark).toHaveTextContent(`No report: ${reason}`);
    expect(screen.getByText(`: ${reason}`)).toHaveClass("sr-only");
  });

  it.each([
    ["nothing is owed", ticketCard({ list_id: "list-2" })],
    [
      "the Ticket is completed",
      ticketCard({ unreported_since: TAKEN, completed_at: "2026-11-25T11:00:00Z", state: null }),
    ],
  ])("shows no No report when %s", (_, card) => {
    renderCard(card);
    expect(screen.queryByText("No report", { exact: true })).not.toBeInTheDocument();
    expect(screen.queryByTitle(/^Taken by a key/)).not.toBeInTheDocument();
  });

  it("marks a completed Ticket done, without a state", () => {
    renderCard(ticketCard({ completed_at: "2026-11-03T10:00:00Z", state: null }));
    expect(screen.getByText("done", { exact: true })).toBeInTheDocument();
    expect(screen.queryByText("Ready")).not.toBeInTheDocument();
  });

  it("says a person's task needs a person, and shows the priority and the due date when set", () => {
    renderCard(
      ticketCard({
        human_action_required: true,
        required_actor: "human",
        priority: "high",
        due_at: "2099-01-31T12:00:00Z",
      }),
    );
    expect(screen.getByText("Needs a person")).toBeInTheDocument();
    expect(screen.getByText("High")).toBeInTheDocument();
    const due = screen.getByText(new Date("2099-01-31T12:00:00Z").toLocaleDateString());
    expect(due.parentElement).not.toHaveClass("text-[var(--destructive)]");
    expect(due.parentElement).toHaveTextContent(/^Due \S+$/);
    expect(screen.queryByText("Overdue")).not.toBeInTheDocument();
  });

  it("says an overdue date in a word as well as the danger colour, and no priority without one", () => {
    renderCard(ticketCard({ due_at: "2000-01-31T12:00:00Z" }));
    const due = screen.getByText(new Date("2000-01-31T12:00:00Z").toLocaleDateString());
    expect(due).toHaveAttribute("datetime", "2000-01-31T12:00:00Z");
    expect(due.parentElement).toHaveClass("text-[var(--destructive)]");
    expect(screen.getByText("Overdue")).toBeVisible();
    expect(due.parentElement).toHaveTextContent(/^Due \S+ Overdue$/);
    for (const word of ["Low", "Medium", "High", "Urgent"]) {
      expect(screen.queryByText(word)).not.toBeInTheDocument();
    }
  });
});
