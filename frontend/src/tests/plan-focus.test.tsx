import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http } from "msw";
import { describe, expect, it } from "vitest";
import type { DocumentKind, Loop, LoopDocument } from "@/lib/types";
import { apiPath, ok } from "./msw/envelope";
import {
  DOCUMENTS,
  emptyDocument,
  generationRun,
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

const IN_FORCE: Loop = {
  ...LOOP,
  plan: {
    plan_id: "plan-1",
    revision_number: 1,
    activated_at: NOW,
    phase_count: 2,
    ticket_total: 3,
    ticket_completed: 0,
  },
};

/** The RoadMap of a Loop whose plan is in force, with the reset answered. */
function openRoadmap() {
  server.use(
    ...planningDialogHandlers([]).handlers,
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
    http.post(apiPath(`${LOOP_PATH}/reviews/roadmap/reset`), () =>
      ok({ scope: "roadmap", approval_id: null, cleared: [], version: 2 }),
    ),
  );
  renderDocuments("roadmap", IN_FORCE);
  return userEvent.setup();
}

describe("the focus around a reset", () => {
  it("reads the warning out, describes Reset and clear with it, and waits on Cancel", async () => {
    const user = openRoadmap();
    await user.click(await screen.findByRole("button", { name: "Reset RoadMap" }));

    expect(screen.getByRole("alert")).toHaveTextContent(
      "Resetting clears the RoadMap and any approval behind it.",
    );
    expect(
      screen.getByRole("button", {
        name: "Reset and clear",
        description: /Its 3 Tickets leave the Kanban/,
      }),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Cancel" })).toHaveFocus();
  });

  it("gives the focus back to Reset when the person cancels", async () => {
    const user = openRoadmap();
    await user.click(await screen.findByRole("button", { name: "Reset RoadMap" }));
    await user.keyboard("{Enter}");

    expect(screen.queryByRole("button", { name: "Reset and clear" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Reset RoadMap" })).toHaveFocus();
  });

  it("puts the focus on Generate after the reset, and the toast says what was reset", async () => {
    const user = openRoadmap();
    await user.click(await screen.findByRole("button", { name: "Reset RoadMap" }));
    await user.click(screen.getByRole("button", { name: "Reset and clear" }));

    expect(await screen.findByText("RoadMap reset")).toBeInTheDocument();
    await waitFor(() => {
      expect(screen.getByRole("button", { name: /Generate RoadMap/ })).toHaveFocus();
    });
  });
});

describe("the focus after a run panel goes", () => {
  it("is on Generate once the failed run's panel is dismissed", async () => {
    server.use(
      ...planningDialogHandlers().handlers,
      http.post(apiPath(`${LOOP_PATH}/generation-runs`), () => ok(generationRun("queued", null))),
      http.get(apiPath(`${LOOP_PATH}/generation-runs/run-1`), () =>
        ok(generationRun("failed", "generating", { error_message: "The provider timed out" })),
      ),
    );
    renderDocuments("analysis");
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: /Generate analysis/ }));
    const [dismiss] = await screen.findAllByRole("button", { name: "Dismiss progress" });
    if (!dismiss) throw new Error("no Dismiss button");

    await user.click(dismiss);
    expect(screen.queryByRole("region", { name: "Generation progress" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Generate analysis/ })).toHaveFocus();
  });
});

describe("the planning document switch", () => {
  it("says which document is open, not only by its colour", async () => {
    server.use(...planningDialogHandlers().handlers);
    renderDocuments("analysis");
    const user = userEvent.setup();
    const documents = await screen.findByRole("group", { name: "Planning document" });

    expect(within(documents).getByRole("button", { name: "Analysis" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    expect(within(documents).getByRole("button", { name: "Info" })).toHaveAttribute(
      "aria-pressed",
      "false",
    );
    await user.click(within(documents).getByRole("button", { name: "RoadMap" }));
    expect(
      within(screen.getByRole("group", { name: "Planning document" })).getByRole("button", {
        name: "RoadMap",
        pressed: true,
      }),
    ).toBeInTheDocument();
  });
});
