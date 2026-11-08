import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { http } from "msw";
import type { ReactNode } from "react";
import { describe, expect, it } from "vitest";
import { openUnplanned } from "@/features/loops/loopUi";
import { PlanReadiness } from "@/features/loops/PlanReadiness";
import { TicketCard } from "@/features/loops/TicketCard";
import { UnplannedWarning } from "@/features/loops/Unplanned";
import type { Card, LoopReadiness, UnplannedTicket } from "@/lib/types";
import { apiPath, ok } from "./msw/envelope";
import { BOARD_ID, LOOP, LOOP_ID, LOOP_PATH, NOW } from "./msw/loops";
import { server } from "./msw/server";

function unplanned(
  key: string,
  title: string,
  extra: Partial<UnplannedTicket> = {},
): UnplannedTicket {
  return {
    id: key,
    key,
    title,
    completed_at: null,
    archived_at: null,
    workplace: "unknown",
    waiting_for: "nothing",
    state: "ready",
    ...extra,
  };
}

const OUTSIDE: UnplannedTicket[] = [
  unplanned("SES-1-UNP-001", "Rename the export"),
  unplanned("SES-1-UNP-002", "Fix the date", { completed_at: NOW }),
  unplanned("SES-1-UNP-003", "Dropped idea", { archived_at: NOW }),
];

function answerReadiness(tickets: UnplannedTicket[]) {
  const readiness: LoopReadiness = {
    loop_id: LOOP_ID,
    stage: "in_progress",
    execution_allowed: true,
    blocked_reason: null,
    items: [],
    phases: [],
    unplanned: tickets,
  };
  server.use(http.get(apiPath(`${LOOP_PATH}/readiness`), () => ok(readiness)));
}

function withQueries(children: ReactNode) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={queryClient}>{children}</QueryClientProvider>);
}

function card(extra: Partial<Card>): Card {
  return {
    id: "card-1",
    board_id: BOARD_ID,
    loop_id: LOOP_ID,
    list_id: "list-1",
    title: "Rename the export",
    description: "",
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
    ticket_key: null,
    kind: "manual",
    phase_number: null,
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
    plan_item_id: null,
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

describe("work outside the plan", () => {
  it("is listed on the Plan tab, without the archived ones", async () => {
    answerReadiness(OUTSIDE);
    withQueries(
      <PlanReadiness
        boardId={BOARD_ID}
        loop={{ ...LOOP, stage: "in_progress" }}
        onChanged={() => undefined}
      />,
    );
    const section = await screen.findByRole("region", { name: "Outside the plan" });
    expect(section).toHaveTextContent("SES-1-UNP-001");
    expect(section).toHaveTextContent("Fix the date");
    expect(section).not.toHaveTextContent("Dropped idea");
    expect(section).toHaveTextContent("never block");
  });

  it("warns at completion about what is still open, and only then", async () => {
    expect(openUnplanned(OUTSIDE).map((ticket) => ticket.key)).toEqual(["SES-1-UNP-001"]);
    answerReadiness(OUTSIDE);
    withQueries(<UnplannedWarning boardId={BOARD_ID} loopId={LOOP_ID} />);
    expect(await screen.findByText(/outside the plan are still open/)).toHaveTextContent(
      "SES-1-UNP-001",
    );
    expect(screen.getByText(/do not block acceptance/)).toBeInTheDocument();
  });

  it("carries an Unplanned badge on the Kanban, a plain manual card none", () => {
    const { unmount } = render(<TicketCard card={card({ ticket_key: "SES-1-UNP-001" })} overlay />);
    expect(screen.getByText("Unplanned")).toBeInTheDocument();
    unmount();
    render(<TicketCard card={card({})} overlay />);
    expect(screen.queryByText("Unplanned")).not.toBeInTheDocument();
  });
});
