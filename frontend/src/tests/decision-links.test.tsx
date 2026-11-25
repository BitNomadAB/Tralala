import { screen, waitFor, within } from "@testing-library/react";
import { http } from "msw";
import { describe, expect, it } from "vitest";
import type { Loop, QaCycle } from "@/lib/types";
import { apiPath, ok } from "./msw/envelope";
import { LOOP, LOOP_ID, LOOP_PATH, NOW } from "./msw/loops";
import { query, renderLoopPage } from "./renderLoopPage";

/** The Loop page answered with `loop` instead of the fixture's Loop at the stage. */
function loopIs(loop: Loop) {
  return [http.get(apiPath(LOOP_PATH), () => ok(loop))];
}

const PLANNED = { ...LOOP, stage: "in_progress" } satisfies Loop;

const AWAITING_QA: Loop = {
  ...LOOP,
  stage: "awaiting_qa",
  qa: { cycle_id: "cycle-1", cycle_number: 1, status: "pending", card_id: "card-qa", open: true },
};

const CYCLE: QaCycle = {
  id: "cycle-1",
  loop_id: LOOP_ID,
  cycle_number: 1,
  status: "pending",
  card_id: "card-qa",
  instruction_revision: 1,
  delivery_baseline: "",
  ai_instructions: {},
  human_instructions: { scenarios: [{ id: "S1", title: "Sign in" }] },
  results: [],
  created_at: NOW,
  updated_at: NOW,
  decided_at: null,
  decision_note: "",
};

describe("a link to the completion dialog", () => {
  it("opens it over a Loop with a plan, and closing it takes dialog out of the address", async () => {
    const { user } = await renderLoopPage("?dialog=completion", "in_progress", {}, loopIs(PLANNED));
    const dialog = await screen.findByRole("dialog", { name: "SES-1 completion and QA" });
    expect(
      within(dialog).getByRole("heading", { name: "1. Accept the implementation" }),
    ).toBeVisible();
    expect(within(dialog).getByRole("button", { name: "Accept implementation" })).toBeVisible();
    // The probe is hidden from the accessibility tree while the dialog is open over the page.
    expect(screen.getByLabelText("Query")).toHaveTextContent("?dialog=completion");

    await user.click(within(dialog).getByRole("button", { name: "Close dialog" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(query()).toBeEmptyDOMElement();
  });

  it("keeps the rest of the address when it closes", async () => {
    const { user } = await renderLoopPage(
      "?tab=plan&dialog=completion",
      "in_progress",
      {},
      loopIs(PLANNED),
    );
    const dialog = await screen.findByRole("dialog", { name: "SES-1 completion and QA" });
    await user.keyboard("{Escape}");
    await waitFor(() => expect(dialog).not.toBeInTheDocument());
    expect(query()).toHaveTextContent(/^\?tab=plan$/);
    expect(screen.getByRole("tab", { name: "Plan" })).toHaveAttribute("aria-selected", "true");
  });

  it("opens the QA decision in the same dialog while the Loop waits for QA", async () => {
    await renderLoopPage("?dialog=completion", "awaiting_qa", {}, [
      ...loopIs(AWAITING_QA),
      http.get(apiPath(`${LOOP_PATH}/qa`), () => ok(CYCLE)),
    ]);
    const dialog = await screen.findByRole("dialog", { name: "SES-1 completion and QA" });
    expect(within(dialog).getByRole("heading", { name: "2. Quality assurance" })).toBeVisible();
    expect(within(dialog).getByRole("button", { name: "Reject QA" })).toBeVisible();
    expect(within(dialog).getByRole("button", { name: "Accept QA and complete" })).toBeVisible();
  });

  it("opens the dialog that closes a Loop without a plan", async () => {
    const withoutPlan: Loop = { ...LOOP, stage: "in_progress", without_plan: true, warnings: [] };
    await renderLoopPage(
      "?dialog=completion",
      "in_progress",
      { without_plan: true, tickets: { total: 1, completed: 1 } },
      loopIs(withoutPlan),
    );
    const dialog = await screen.findByRole("dialog", { name: "Close SES-1" });
    expect(within(dialog).getByRole("button", { name: "Close the Loop" })).toBeVisible();
    expect(within(dialog).queryByText("Was QA performed?")).toBeNull();
  });

  it("decides nothing by itself: the dialog waits for the person", async () => {
    const sent: string[] = [];
    await renderLoopPage("?dialog=completion", "in_progress", {}, [
      ...loopIs(PLANNED),
      http.post(apiPath(`${LOOP_PATH}/*`), ({ request }) => {
        sent.push(new URL(request.url).pathname);
        return ok({});
      }),
    ]);
    await screen.findByRole("dialog", { name: "SES-1 completion and QA" });
    expect(sent).toEqual([]);
  });

  it("opens nothing over a draft, which has nothing to finalize", async () => {
    const { header } = await renderLoopPage("?dialog=completion", "draft", {});
    expect(within(header).getByText("Draft")).toBeInTheDocument();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("opens nothing over a completed Loop, which is read-only", async () => {
    const completed: Loop = { ...LOOP, stage: "completed", completed_at: NOW };
    await renderLoopPage("?dialog=completion", "completed", {}, loopIs(completed));
    expect(await screen.findByText(/Read-only: this Loop is completed/)).toBeInTheDocument();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("knows no other dialog", async () => {
    const { header } = await renderLoopPage("?dialog=cancel", "in_progress", {}, loopIs(PLANNED));
    expect(within(header).getByRole("button", { name: "Loop actions" })).toBeInTheDocument();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });
});
