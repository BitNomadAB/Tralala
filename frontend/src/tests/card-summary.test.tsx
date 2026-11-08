import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { CardSummaryNote } from "@/features/cards/CardSummaryNote";
import type { Card } from "@/lib/types";

const NOW = "2026-11-05T10:00:00Z";

function card(extra: Partial<Card>): Card {
  return {
    id: "card-1",
    board_id: "board-1",
    loop_id: "loop-1",
    list_id: "list-1",
    title: "Login",
    description: "Build the page.",
    summary: "",
    summary_source: "",
    summary_stale: false,
    face: null,
    position: 1024,
    priority: "none",
    due_at: null,
    completed_at: null,
    assignee_actor_id: null,
    assignee_type: null,
    assignee_name: null,
    assigned_at: null,
    created_at: NOW,
    updated_at: NOW,
    archived_at: null,
    version: 1,
    labels: [],
    checklist_total: 0,
    checklist_completed: 0,
    comment_count: 0,
    ticket_key: "L-1-PH01-001",
    kind: "ticket",
    phase_number: 1,
    required_actor: "any",
    execution_mode: "normal",
    human_action_required: false,
    human_action_reason: "",
    human_instructions: "",
    human_confirmed_at: null,
    acceptance_criteria: [],
    expected_evidence: [],
    ready: true,
    blockers: [],
    downstream_phase_numbers: [],
    plan_item_id: "card-1",
    workplace: "unknown",
    waiting_for: "nothing",
    waiting_reason: "",
    waiting_set_at: null,
    waiting_set_by: null,
    state: "ready",
    needs_person: false,
    ...extra,
  };
}

describe("a Ticket's summary", () => {
  it("shows the summary with who wrote it", () => {
    render(
      <CardSummaryNote card={card({ summary: "Adds a login page.", summary_source: "plan" })} />,
    );
    const section = screen.getByRole("region", { name: "Summary" });
    expect(section).toHaveTextContent("Adds a login page.");
    expect(section).toHaveTextContent("From the RoadMap");
    expect(section).not.toHaveTextContent("out of date");
  });

  it("says when the Ticket changed after the summary was written", () => {
    render(
      <CardSummaryNote
        card={card({ summary: "Adds a login page.", summary_source: "agent", summary_stale: true })}
      />,
    );
    const section = screen.getByRole("region", { name: "Summary" });
    expect(section).toHaveTextContent("Written by an agent");
    expect(section).toHaveTextContent("it may be out of date");
  });

  it("shows nothing for a Ticket without a summary", () => {
    const { container } = render(<CardSummaryNote card={card({})} />);
    expect(container).toBeEmptyDOMElement();
  });
});
