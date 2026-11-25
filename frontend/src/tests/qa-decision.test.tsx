import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http } from "msw";
import { describe, expect, it } from "vitest";
import { ToastProvider } from "@/components/ui/toast";
import { LoopCompletionDialog } from "@/features/loops/LoopCompletionDialog";
import { NO_SCENARIOS, qaRefusal } from "@/features/loops/qaRefusal";
import { ApiError } from "@/lib/api";
import type { Loop, QaCycle } from "@/lib/types";
import { isRecord } from "./msw/cards";
import { apiPath, failure, ok } from "./msw/envelope";
import { BOARD_ID, LOOP, LOOP_ID, LOOP_PATH, NOW } from "./msw/loops";
import { server } from "./msw/server";
import { READINESS } from "./msw/ticketView";

const REFUSED = "QA is incomplete; required scenarios are unresolved";

const AWAITING_QA: Loop = {
  ...LOOP,
  stage: "awaiting_qa",
  qa: { cycle_id: "cycle-1", cycle_number: 1, status: "pending", card_id: "card-qa", open: true },
};

const SCENARIOS = [
  { id: "S1", title: "Sign in" },
  { id: "S2", title: "Pay" },
];

function cycle(scenarios: { id: string; title: string }[]): QaCycle {
  return {
    id: "cycle-1",
    loop_id: LOOP_ID,
    cycle_number: 1,
    status: "pending",
    card_id: "card-qa",
    instruction_revision: scenarios.length > 0 ? 1 : 0,
    delivery_baseline: "",
    ai_instructions: {},
    human_instructions: scenarios.length > 0 ? { scenarios } : {},
    results: [],
    created_at: NOW,
    updated_at: NOW,
    decided_at: null,
    decision_note: "",
  };
}

/**
 * The completion dialog over a Loop that waits for QA, whose cycle has `scenarios`; every decision
 * it sends is in `sent`, and the server answers it with `answer`.
 */
function renderDialog(
  scenarios: { id: string; title: string }[],
  answer: () => Response = () => ok({}),
) {
  const sent: Record<string, unknown>[] = [];
  server.use(
    http.get(apiPath(`${LOOP_PATH}/readiness`), () => ok(READINESS)),
    http.get(apiPath(`${LOOP_PATH}/qa`), () => ok(cycle(scenarios))),
    http.post(apiPath(`${LOOP_PATH}/qa/decision`), async ({ request }) => {
      const body: unknown = await request.json();
      if (isRecord(body)) sent.push(body);
      return answer();
    }),
  );
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  render(
    <QueryClientProvider client={client}>
      <ToastProvider>
        <LoopCompletionDialog
          boardId={BOARD_ID}
          loop={AWAITING_QA}
          open
          isHuman
          onClose={() => undefined}
          onChanged={() => undefined}
        />
      </ToastProvider>
    </QueryClientProvider>,
  );
  return { sent, user: userEvent.setup() };
}

const acceptQa = () => screen.getByRole("button", { name: "Accept QA and complete" });

describe("the QA decision in the completion dialog", () => {
  it("holds Accept QA while the cycle has no scenarios, and names the way to close the Loop", async () => {
    const { sent, user } = renderDialog([]);
    const reason = await screen.findByText(NO_SCENARIOS);
    // Held, not disabled: it stays in the tab order and says why (WCAG 2.4.3, 3.3.2).
    expect(acceptQa()).toHaveAttribute("aria-disabled", "true");
    expect(acceptQa()).not.toBeDisabled();
    expect(acceptQa()).toHaveAttribute("aria-describedby", reason.id);
    await user.click(acceptQa());
    expect(sent).toEqual([]);
    // The way it names is there: the acceptance on the person's own word, under 1.
    expect(screen.getByRole("option", { name: "Tested and passed outside Tralala" })).toBeVisible();
  });

  it("sends the acceptance when the cycle has scenarios", async () => {
    const { sent, user } = renderDialog(SCENARIOS);
    await screen.findByText("Sign in");
    expect(acceptQa()).not.toHaveAttribute("aria-disabled");
    await user.click(acceptQa());
    await waitFor(() => expect(sent).toHaveLength(1));
    expect(sent[0]).toMatchObject({ cycle_id: "cycle-1", decision: "accepted", version: 1 });
    expect(await screen.findByText("QA decision recorded")).toBeInTheDocument();
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("lists in the dialog which scenarios the server names as unresolved", async () => {
    const { user } = renderDialog(SCENARIOS, () =>
      failure(409, "qa_incomplete", REFUSED, {
        blockers: [
          { scenario_id: "S1", reason: "not_run" },
          { scenario_id: "S2", reason: "failed", detail: "The charge was refused" },
        ],
      }),
    );
    await screen.findByText("Sign in");
    await user.click(acceptQa());
    const refusal = await screen.findByRole("alert");
    expect(refusal).toHaveTextContent("QA was not accepted:");
    expect(
      within(refusal)
        .getAllByRole("listitem")
        .map((item) => item.textContent),
    ).toEqual(["S1 Sign in: no result recorded", "S2 Pay: failed (The charge was refused)"]);
    // The toast says the same in short, over the dialog.
    expect(screen.getByText("Could not record the decision")).toBeInTheDocument();
    expect(
      screen.getByText("2 scenarios are unresolved; the dialog lists them."),
    ).toBeInTheDocument();
  });

  it("clears the refusal when the next attempt goes through", async () => {
    let refuse = true;
    const { user } = renderDialog(SCENARIOS, () =>
      refuse
        ? failure(409, "qa_incomplete", REFUSED, {
            blockers: [{ scenario_id: "S1", reason: "not_run" }],
          })
        : ok({}),
    );
    await screen.findByText("Sign in");
    await user.click(acceptQa());
    await screen.findByRole("alert");
    refuse = false;
    await user.click(acceptQa());
    await waitFor(() => expect(screen.queryByRole("alert")).toBeNull());
  });
});

describe("what a refused QA decision says", () => {
  const titles = new Map(SCENARIOS.map((scenario) => [scenario.id, scenario.title]));
  const refused = (blockers: unknown) =>
    new ApiError(REFUSED, { code: "qa_incomplete", status: 409, details: { blockers } });

  it("says that the cycle has no scenarios, with the way out, when the instructions are missing", () => {
    const error = refused([{ scenario_id: null, reason: "instructions_missing" }]);
    expect(qaRefusal(error, titles)).toEqual([NO_SCENARIOS]);
  });

  it("names each scenario by id and title with what is unresolved", () => {
    const error = refused([
      { scenario_id: "S1", reason: "not_applicable_requires_human_approval" },
      { scenario_id: "S2", reason: "instructions_revised" },
      { scenario_id: "S9", reason: "blocked" },
    ]);
    expect(qaRefusal(error, titles)).toEqual([
      "S1 Sign in: recorded as not applicable; choose its waiver to accept",
      "S2 Pay: its result is from earlier instructions; record it again",
      "S9: blocked",
    ]);
  });

  it("says a reason it does not know in the server's own words, once", () => {
    const error = refused([
      { scenario_id: "S1", reason: "needs_review" },
      { scenario_id: "S1", reason: "needs_review" },
    ]);
    expect(qaRefusal(error, titles)).toEqual(["S1 Sign in: needs review"]);
  });

  it("falls back to the refusal's own message when it names nothing", () => {
    expect(qaRefusal(refused([]), titles)).toEqual([REFUSED]);
    const other = new ApiError("This Loop is completed and read-only", {
      code: "loop_read_only",
      status: 409,
    });
    expect(qaRefusal(other, titles)).toEqual(["This Loop is completed and read-only"]);
  });
});
