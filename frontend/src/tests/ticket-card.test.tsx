import { DndContext } from "@dnd-kit/core";
import { SortableContext } from "@dnd-kit/sortable";
import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { TicketCard } from "@/features/loops/TicketCard";
import type { Card, TicketFace } from "@/lib/types";
import { ticketCard } from "./msw/cards";

const FACE: TicketFace = {
  summary: "Sessions end after 30 idle minutes.",
  why: "Idle sessions stay open for days.",
  if_skipped: "A lost laptop stays signed in.",
  pros: ["Safer"],
  cons: ["People sign in more often"],
  steps: ["End a session after 30 idle minutes"],
};

/** The card on a Kanban column, as the board renders it: sortable, with an open handler. */
function renderCard(card: Card) {
  const onOpen = vi.fn();
  render(
    <DndContext>
      <SortableContext items={[card.id]}>
        <ul>
          <TicketCard card={card} onOpen={onOpen} />
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
    expect(within(item).getByText("SES-1-PH01-001")).toHaveClass("font-mono");
    expect(within(item).getByRole("img", { name: "Owner: Ada Lovelace" })).toHaveTextContent("AL");
    for (const word of ["Ready", "Needs input", "Blocked", "done", "Needs a person"]) {
      expect(within(item).queryByText(word)).not.toBeInTheDocument();
    }
    // A click, not a pointer gesture: the board's pointer sensor waits for 4 px before it drags,
    // which the bare DndContext here does not.
    fireEvent.click(title);
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
  });

  it("shows Needs input with the reason of the wait", () => {
    renderCard(
      ticketCard({ state: "needs_input", waiting_for: "decision", waiting_reason: "Which TTL?" }),
    );
    expect(screen.getByText("Needs input").parentElement).toHaveAttribute("title", "Which TTL?");
    expect(screen.queryByText("Blocked")).not.toBeInTheDocument();
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
    expect(screen.getByText(new Date("2099-01-31T12:00:00Z").toLocaleDateString())).not.toHaveClass(
      "text-[var(--destructive)]",
    );
  });

  it("shows an overdue date in the danger colour, and no priority mark without one", () => {
    renderCard(ticketCard({ due_at: "2000-01-31T12:00:00Z" }));
    expect(screen.getByText(new Date("2000-01-31T12:00:00Z").toLocaleDateString())).toHaveClass(
      "text-[var(--destructive)]",
    );
    for (const word of ["Low", "Medium", "High", "Urgent"]) {
      expect(screen.queryByText(word)).not.toBeInTheDocument();
    }
  });
});
