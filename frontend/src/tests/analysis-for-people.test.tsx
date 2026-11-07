import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http } from "msw";
import { describe, expect, it } from "vitest";
import { ToastProvider } from "@/components/ui/toast";
import { LoopDocumentDialog } from "@/features/loops/LoopDocumentDialog";
import { viewAuthorship } from "@/features/loops/loopUi";
import { stageLabel, traceStages } from "@/lib/runTrace";
import type { DocumentKind, GenerationRun, LoopDocument } from "@/lib/types";
import { apiPath, ok } from "./msw/envelope";
import {
  BOARD_ID,
  DOCUMENTS,
  emptyDocument,
  generationRun,
  LOOP,
  LOOP_ID,
  LOOP_PATH,
  planningDialogHandlers,
} from "./msw/loops";
import { server } from "./msw/server";

function written(kind: DocumentKind, content: string, provenance: Record<string, unknown>) {
  return {
    ...emptyDocument(kind),
    state: "ready_for_review",
    current_revision_id: `${kind}-1`,
    current_revision_number: 1,
    current_content: content,
    current_provenance: provenance,
  } satisfies LoopDocument;
}

/** A Loop whose analysis pair is ready for review; the human view says who wrote it. */
function analysisDocuments(provenance: Record<string, unknown>) {
  return {
    ...DOCUMENTS,
    info: written("info", "Users must confirm.", {}),
    analysis_ai: written("analysis_ai", "```json\n{}\n```", { model: "m-1" }),
    analysis: written("analysis", "People confirm by e-mail [F-02].", provenance),
  };
}

function openAnalysis(provenance: Record<string, unknown>, runs: GenerationRun[] = []) {
  const { state, handlers } = planningDialogHandlers(runs);
  const started: unknown[] = [];
  // Before the dialog's defaults: MSW answers with the first handler that matches.
  server.use(
    http.get(apiPath(`${LOOP_PATH}/documents`), () =>
      ok({
        loop_id: LOOP_ID,
        loop_version: 1,
        documents: analysisDocuments(provenance),
        approvals: {},
      }),
    ),
    http.post(apiPath(`${LOOP_PATH}/generation-runs`), async ({ request }) => {
      started.push(await request.json());
      return ok(generationRun("queued", null, { purpose: "analysis_human" }));
    }),
    http.get(apiPath(`${LOOP_PATH}/generation-runs/run-1`), () =>
      ok(generationRun("running", "writing_for_people", { purpose: "analysis_human", trace: [] })),
    ),
    ...handlers,
  );
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={queryClient}>
      <ToastProvider>
        <LoopDocumentDialog
          boardId={BOARD_ID}
          loop={LOOP}
          initialTab="analysis"
          isHuman
          readOnly={false}
          onClose={() => undefined}
          onChanged={() => undefined}
        />
      </ToastProvider>
    </QueryClientProvider>,
  );
  return { state, started };
}

describe("the analysis written for people", () => {
  it("names who wrote the human view, or that it was rendered from the structure", () => {
    const document = (provenance: Record<string, unknown>) =>
      written("analysis", "text", provenance);
    expect(viewAuthorship(document({ written: true, agent_name: "Alpha" }))).toBe(
      "Written by Alpha",
    );
    expect(viewAuthorship(document({ written: true }))).toBe("Written by a board agent");
    expect(viewAuthorship(document({ rendered: true, submitted: true }))).toBe(
      "Rendered from the structure",
    );
    expect(viewAuthorship(document({}))).toBeNull();
    expect(viewAuthorship(emptyDocument("analysis"))).toBeNull();
  });

  it("shows its run as reading the analysis, writing for people and checking coverage", () => {
    expect(stageLabel("documents", "analysis_human")).toBe("Reading the analysis");
    expect(stageLabel("writing", "analysis_human")).toBe("Writing for people");
    expect(stageLabel("checking", "analysis_human")).toBe("Checking coverage");
    expect(stageLabel("saving", "analysis_human")).toBe("Saving");
    const run = generationRun("running", "writing_for_people", {
      purpose: "analysis_human",
      trace: [],
    });
    // No repository is read for it.
    expect(traceStages("analysis_human", run).map((stage) => stage.label)).toEqual([
      "Reading the analysis",
      "Writing for people",
      "Checking coverage",
      "Saving",
    ]);
  });

  it("labels the human view and starts a rewrite for people", async () => {
    const { started } = openAnalysis({ written: true, agent_name: "Alpha" });
    expect(await screen.findByText("Written by Alpha")).toBeInTheDocument();
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: /Rewrite for people/ }));
    // The run panel, in the dialog and beside it, names the stages of writing for people.
    expect(await screen.findAllByText("Writing for people")).not.toHaveLength(0);
    expect(started).toEqual([{ purpose: "analysis_human" }]);
  });

  it("keeps the rewrite out of the technical view", async () => {
    openAnalysis({ rendered: true });
    expect(await screen.findByText("Rendered from the structure")).toBeInTheDocument();
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "For AI" }));
    expect(screen.queryByRole("button", { name: /Rewrite for people/ })).not.toBeInTheDocument();
  });

  it("is not approved while a board agent is writing it", async () => {
    openAnalysis({ rendered: true }, [
      generationRun("running", "writing_for_people", { id: "run-7", purpose: "analysis_human" }),
    ]);
    // The analysis is there and complete, so only the run keeps it from being approved.
    expect(await screen.findByText("Rendered from the structure")).toBeInTheDocument();
    expect(
      await screen.findByText(/A board agent is writing the brief of this analysis for people/),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Approve analysis" })).toBeDisabled();
    expect(screen.getByRole("button", { name: /Rewrite for people/ })).toBeDisabled();
  });

  it("can be approved once nobody is writing it", async () => {
    openAnalysis({ written: true, agent_name: "Alpha" }, [
      generationRun("completed", "writing_for_people", { id: "run-7", purpose: "analysis_human" }),
    ]);
    expect(await screen.findByText("Written by Alpha")).toBeInTheDocument();
    expect(await screen.findByRole("button", { name: "Approve analysis" })).toBeEnabled();
    expect(
      screen.queryByText(/A board agent is writing the brief of this analysis for people/),
    ).not.toBeInTheDocument();
  });
});
