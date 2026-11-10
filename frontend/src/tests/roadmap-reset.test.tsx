import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http } from "msw";
import { describe, expect, it } from "vitest";
import type { DocumentKind, Loop, LoopDocument } from "@/lib/types";
import { apiPath, ok } from "./msw/envelope";
import {
  DOCUMENTS,
  emptyDocument,
  LOOP,
  LOOP_ID,
  LOOP_PATH,
  NOW,
  planningDialogHandlers,
} from "./msw/loops";
import { server } from "./msw/server";
import { renderDocuments } from "./renderDocuments";

function written(kind: DocumentKind, state: LoopDocument["state"]): LoopDocument {
  return {
    ...emptyDocument(kind),
    state,
    current_revision_id: `${kind}-rev-1`,
    current_revision_number: 1,
    current_created_at: NOW,
    current_content: "text",
  };
}

/** The analysis approved and the RoadMap emptied by a reset; `loop` says whether a plan is still in force. */
function open(loop: Loop) {
  const { state, handlers } = planningDialogHandlers([]);
  server.use(
    http.get(apiPath(`${LOOP_PATH}/documents`), () =>
      ok({
        loop_id: LOOP_ID,
        loop_version: 1,
        documents: {
          ...DOCUMENTS,
          info: written("info", "ready_for_review"),
          analysis_ai: written("analysis_ai", "ready_for_review"),
          analysis: written("analysis", "approved"),
        },
        approvals: {},
      }),
    ),
    ...handlers,
  );
  renderDocuments("roadmap", loop);
  return { state, user: userEvent.setup() };
}

const IN_FORCE: Loop = {
  ...LOOP,
  plan: {
    plan_id: "plan-1",
    revision_number: 1,
    activated_at: NOW,
    phase_count: 6,
    ticket_total: 20,
    ticket_completed: 0,
  },
};

describe("resetting the RoadMap", () => {
  it("takes a plan still on the Kanban off it, and says so before it does", async () => {
    const { state, user } = open(IN_FORCE);
    await user.click(await screen.findByRole("button", { name: "Reset RoadMap" }));
    expect(screen.getByText(/Its 20 Tickets leave the Kanban/)).toHaveTextContent(
      "those nobody touched are deleted, the others archived",
    );
    await user.click(screen.getByRole("button", { name: "Reset and clear" }));
    await waitFor(() =>
      expect(state.requests).toContain(`POST ${LOOP_PATH}/reviews/roadmap/reset`),
    );
  });

  it("offers nothing to reset when the RoadMap is empty and no plan is in force", async () => {
    open({ ...LOOP, plan: null });
    await screen.findByRole("button", { name: /Generate RoadMap/ });
    expect(screen.queryByRole("button", { name: "Reset RoadMap" })).not.toBeInTheDocument();
  });
});
