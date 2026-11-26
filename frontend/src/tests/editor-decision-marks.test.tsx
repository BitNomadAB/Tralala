import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import { http } from "msw";
import type { ReactNode } from "react";
import { describe, expect, it } from "vitest";
import { ToastProvider } from "@/components/ui/toast";
import { ActivityPanel } from "@/features/activity/ActivityPanel";
import { decidedByText } from "@/features/history/askedThrough";
import { LoopCompletionDialog } from "@/features/loops/LoopCompletionDialog";
import { PlanDocumentPanel } from "@/features/loops/PlanDocumentPanel";
import type { ActivityEntry } from "@/lib/types";
import { apiPath, ok } from "./msw/envelope";
import { BOARD_ID, DOCUMENTS, LOOP, LOOP_ID, LOOP_PATH, NOW, emptyDocument } from "./msw/loops";
import { server } from "./msw/server";
import { READINESS } from "./msw/ticketView";

/**
 * A Loop's decision taken in the editor through a key, shown while the Loop is live: the board's
 * Activity panel, the analysis and RoadMap on the Loop page, and the implementation in the
 * completion dialog all say "decided in a coding session through the key …", and who asked.
 */

const LAPTOP = { credential_id: "cred-1", key_name: "Laptop", via: "form" };
const DESKTOP = { credential_id: "cred-2", key_name: "Desktop", via: "link" };
const TRAIL =
  "decided in a coding session through the key Laptop, asked from a coding session through the keys Desktop and Laptop";

function approval(scope: string, decision = "approved", marks = true): Record<string, unknown> {
  return {
    id: `${scope}-1`,
    loop_id: LOOP_ID,
    scope,
    decision,
    reviewer_actor_id: "user-1",
    reviewer_name: "Ada",
    feedback: "",
    created_at: NOW,
    ...(marks ? { taken_through: LAPTOP, asked_through: [DESKTOP, LAPTOP] } : {}),
  };
}

function withClient(children: ReactNode) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  render(
    <QueryClientProvider client={client}>
      <ToastProvider>{children}</ToastProvider>
    </QueryClientProvider>,
  );
}

describe("who took a Loop's decision, and how", () => {
  it("says the person and the trail, and nothing more for a decision taken in Tralala", () => {
    expect(decidedByText(approval("analysis"))).toBe(`Approved by Ada, ${TRAIL}`);
    expect(decidedByText(approval("roadmap", "changes_requested"))).toBe(
      `Changes requested by Ada, ${TRAIL}`,
    );
    expect(decidedByText(approval("implementation"))).toBe(`Accepted by Ada, ${TRAIL}`);
    expect(decidedByText(approval("analysis", "approved", false))).toBe("Approved by Ada");
    expect(decidedByText(null)).toBeNull();
    expect(decidedByText(undefined)).toBeNull();
  });

  it("shows on the analysis on the Loop page", () => {
    render(
      <PlanDocumentPanel
        kind="analysis"
        document={{ ...emptyDocument("analysis"), state: "approved" }}
        decision={approval("analysis")}
      />,
    );
    expect(screen.getByText(`Approved by Ada, ${TRAIL}`)).toBeInTheDocument();
  });

  it("is not shown on a technical document", () => {
    render(
      <PlanDocumentPanel
        kind="analysis_ai"
        document={emptyDocument("analysis_ai")}
        decision={approval("analysis")}
      />,
    );
    expect(screen.queryByText(/Approved by Ada/)).not.toBeInTheDocument();
  });

  it("shows in the board's activity, on the decision and on the plan it published", async () => {
    const entries: ActivityEntry[] = [
      {
        id: "a-1",
        actor_id: "user-1",
        actor_type: "user",
        action: "loop.plan_published",
        entity_type: "loop",
        entity_id: LOOP_ID,
        request_id: null,
        timestamp: NOW,
        changes: { plan_id: "plan-1", tickets: 2, taken_through: LAPTOP },
      },
      {
        id: "a-2",
        actor_id: "user-1",
        actor_type: "user",
        action: "loop.roadmap_reviewed",
        entity_type: "loop",
        entity_id: LOOP_ID,
        request_id: null,
        timestamp: NOW,
        changes: { decision: "approved", taken_through: LAPTOP, asked_through: [DESKTOP, LAPTOP] },
      },
      {
        id: "a-3",
        actor_id: "user-1",
        actor_type: "user",
        action: "loop.analysis_reviewed",
        entity_type: "loop",
        entity_id: LOOP_ID,
        request_id: null,
        timestamp: NOW,
        changes: { decision: "approved" },
      },
    ];
    server.use(http.get(apiPath(`/boards/${BOARD_ID}/activity`), () => ok(entries)));
    withClient(<ActivityPanel boardId={BOARD_ID} onClose={() => undefined} />);

    const panel = screen.getByRole("complementary", { name: "Board activity" });
    const rows = await within(panel).findAllByRole("listitem");
    expect(rows).toHaveLength(3);
    const [published, reviewed, plain] = rows;
    expect(published).toHaveTextContent("decided in a coding session through the key Laptop");
    expect(reviewed).toHaveTextContent(TRAIL);
    expect(plain).not.toHaveTextContent("coding session");
  });

  it("shows on the implementation in the completion dialog", async () => {
    server.use(
      http.get(apiPath(`${LOOP_PATH}/readiness`), () => ok(READINESS)),
      http.get(apiPath(`${LOOP_PATH}/documents`), () =>
        ok({
          loop_id: LOOP_ID,
          loop_version: 3,
          documents: DOCUMENTS,
          approvals: { implementation: approval("implementation") },
        }),
      ),
    );
    withClient(
      <LoopCompletionDialog
        boardId={BOARD_ID}
        loop={{ ...LOOP, stage: "awaiting_qa", without_plan: false }}
        open
        isHuman
        onClose={() => undefined}
        onChanged={() => undefined}
      />,
    );
    expect(await screen.findByText(`Accepted by Ada, ${TRAIL}`)).toBeInTheDocument();
  });
});
