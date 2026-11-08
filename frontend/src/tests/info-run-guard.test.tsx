import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http } from "msw";
import { describe, expect, it } from "vitest";
import type { PlanTab } from "@/features/loops/loopUi";
import { candidateMarkdown, staleCandidate } from "@/lib/keptCandidate";
import { keys } from "@/lib/queries";
import type { GenerationRun } from "@/lib/types";
import { apiPath, ok } from "./msw/envelope";
import {
  BOARD_ID,
  DOCUMENTS,
  generationRun,
  LOOP_ID,
  LOOP_PATH,
  planningDialogHandlers,
} from "./msw/loops";
import { server } from "./msw/server";
import { renderDocuments } from "./renderDocuments";

const SAVE_INFO = `PUT ${LOOP_PATH}/documents/info`;
const CANCEL_RUN = `POST ${LOOP_PATH}/generation-runs/run-1/cancel`;
const START_RUN = `POST ${LOOP_PATH}/generation-runs`;

/**
 * The Plan tab's documents against a Loop whose run list is `runs`: saving Info, cancelling run-1 and
 * starting a run are answered, and a cancelled run-1 is listed as cancelled from then on.
 */
async function openDocuments(initialTab: PlanTab, runs: GenerationRun[]) {
  const { state, handlers } = planningDialogHandlers(runs);
  const startedPurposes: string[] = [];
  server.use(
    ...handlers,
    http.put(apiPath(`${LOOP_PATH}/documents/info`), () =>
      ok({ loop_id: LOOP_ID, loop_version: 1, documents: DOCUMENTS, approvals: {} }),
    ),
    http.post(apiPath(`${LOOP_PATH}/generation-runs/run-1/cancel`), () => {
      state.runs = [generationRun("cancelled", "generating")];
      return ok(state.runs[0]);
    }),
    http.post(apiPath(`${LOOP_PATH}/generation-runs`), async ({ request }) => {
      const body: unknown = await request.json();
      if (typeof body === "object" && body !== null && "purpose" in body) {
        startedPurposes.push(String(body.purpose));
      }
      return ok(generationRun("queued", null, { id: "run-2" }));
    }),
    http.get(apiPath(`${LOOP_PATH}/generation-runs/run-2`), () =>
      ok(generationRun("running", "generating", { id: "run-2" })),
    ),
  );
  const queryClient = renderDocuments(initialTab);
  // The guard reads the Loop's run list, so a save is only meaningful once that list has arrived.
  await waitFor(() => {
    expect(queryClient.getQueryData(keys.generationRuns(BOARD_ID, LOOP_ID))).toBeDefined();
  });
  return { state, startedPurposes, user: userEvent.setup() };
}

/** Types a new Info and presses "Save as new revision". */
async function saveInfo(user: ReturnType<typeof userEvent.setup>) {
  await user.type(screen.getByLabelText("Write or revise Info"), "Sessions expire after 30 min.");
  await user.click(screen.getByRole("button", { name: "Save as new revision" }));
}

describe("saving Info while a generation run is in flight", () => {
  it("saves at once when no run is in flight", async () => {
    const { state, user } = await openDocuments("info", [generationRun("completed", "generating")]);
    await saveInfo(user);

    await waitFor(() => {
      expect(state.requests).toContain(SAVE_INFO);
    });
    expect(screen.queryByRole("button", { name: "Save anyway" })).not.toBeInTheDocument();
  });

  it("asks first, and Save anyway saves without touching the run", async () => {
    const { state, user } = await openDocuments("info", [generationRun("running", "generating")]);
    await saveInfo(user);

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "A generation run is in progress; saving now discards its result",
    );
    expect(state.requests).not.toContain(SAVE_INFO);
    expect(screen.getByRole("button", { name: "Cancel the run first" })).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Save anyway" }));
    await waitFor(() => {
      expect(state.requests).toContain(SAVE_INFO);
    });
    expect(state.requests).not.toContain(CANCEL_RUN);
    expect(await screen.findByText("Info saved as a new revision")).toBeInTheDocument();
  });

  it("Cancel the run first cancels the run, then saves", async () => {
    const { state, user } = await openDocuments("info", [generationRun("queued", null)]);
    await saveInfo(user);

    await user.click(await screen.findByRole("button", { name: "Cancel the run first" }));
    await waitFor(() => {
      expect(state.requests).toContain(SAVE_INFO);
    });
    expect(state.requests.indexOf(CANCEL_RUN)).toBeGreaterThanOrEqual(0);
    expect(state.requests.indexOf(CANCEL_RUN)).toBeLessThan(state.requests.indexOf(SAVE_INFO));
    // The run is over, so the next save is a plain save again.
    expect(await screen.findByRole("button", { name: "Save as new revision" })).toBeInTheDocument();
  });

  it("Back keeps the draft unsaved", async () => {
    const { state, user } = await openDocuments("info", [generationRun("running", "generating")]);
    await saveInfo(user);

    await user.click(await screen.findByRole("button", { name: "Back" }));
    expect(screen.getByRole("button", { name: "Save as new revision" })).toBeEnabled();
    expect(screen.getByLabelText("Write or revise Info")).toHaveValue(
      "Sessions expire after 30 min.",
    );
    expect(state.requests).not.toContain(SAVE_INFO);
  });
});

const CANDIDATE = { schema_version: 1, outcome: "Expire idle sessions", findings: [] };

const inputChanged = (output: Record<string, unknown>) =>
  generationRun("failed", "generating", {
    error_code: "generation_input_changed",
    error_message: "The documents changed while the model was working",
    output,
  });

describe("a run whose input changed while it worked", () => {
  it("shows the kept result as not promoted and regenerates from the current Info", async () => {
    const { state, startedPurposes, user } = await openDocuments("analysis", [
      inputChanged({ stale_candidate: CANDIDATE }),
    ]);

    const kept = await screen.findByRole("region", { name: "Kept analysis result" });
    expect(within(kept).getByText("not promoted")).toBeInTheDocument();
    // Rendered as the technical view renders a generated draft: the JSON in a code block.
    expect(kept.querySelector("pre code")).toHaveTextContent('"outcome": "Expire idle sessions"');

    await user.click(
      within(kept).getByRole("button", { name: "Regenerate from the current Info" }),
    );
    await waitFor(() => {
      expect(state.requests).toContain(START_RUN);
    });
    expect(startedPurposes).toEqual(["analysis"]);
    expect(await screen.findByRole("button", { name: /Generating…/ })).toBeDisabled();
  });

  it("shows nothing kept for a run that failed for another reason", async () => {
    await openDocuments("analysis", [
      generationRun("failed", "generating", {
        error_code: "provider_error",
        output: { stale_candidate: CANDIDATE },
      }),
    ]);

    expect(await screen.findByText(/Last analysis run failed/)).toBeInTheDocument();
    expect(screen.queryByRole("region", { name: /Kept/ })).not.toBeInTheDocument();
  });
});

describe("staleCandidate", () => {
  it("is the kept object of a failed generation_input_changed run, and null otherwise", () => {
    expect(staleCandidate(inputChanged({ stale_candidate: CANDIDATE }))).toEqual(CANDIDATE);
    expect(staleCandidate(inputChanged({}))).toBeNull();
    expect(staleCandidate(inputChanged({ stale_candidate: ["not", "an", "object"] }))).toBeNull();
    expect(staleCandidate(inputChanged({ stale_candidate: "text" }))).toBeNull();
    expect(staleCandidate(generationRun("completed", "generating"))).toBeNull();
    expect(staleCandidate(undefined)).toBeNull();
  });

  it("renders as a fenced JSON block", () => {
    expect(candidateMarkdown({ outcome: "x" })).toBe('```json\n{\n  "outcome": "x"\n}\n```\n');
  });
});
