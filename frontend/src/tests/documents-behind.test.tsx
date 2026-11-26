import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http } from "msw";
import { describe, expect, it } from "vitest";
import { ToastProvider } from "@/components/ui/toast";
import { AuthContext } from "@/features/auth/useAuth";
import { LoopPlanTab } from "@/features/loops/LoopPlanTab";
import type { PlanTab } from "@/features/loops/loopUi";
import {
  DOCUMENTS_CHANGED_TEXT,
  documentsBehind,
  summaryRevision,
} from "@/features/loops/useDocumentsBehind";
import { keys } from "@/lib/queries";
import type { DocumentKind, LoopDocument, LoopSummary } from "@/lib/types";
import { announcer } from "./announcer";
import { summary } from "./msw/boards";
import { apiPath, ok } from "./msw/envelope";
import {
  BOARD_ID,
  DOCUMENTS,
  emptyDocument,
  LOOP,
  LOOP_ID,
  LOOP_PATH,
  NOW,
  planningDialogHandlers,
} from "./msw/loops";
import { server } from "./msw/server";
import { MEMBER } from "./msw/session";

const EMPTY: LoopSummary["documents"] = {
  info: "empty",
  analysis_ai: "empty",
  analysis: "empty",
  roadmap_ai: "empty",
  roadmap: "empty",
};

/** A document at revision `number` holding `content`. */
function written(kind: DocumentKind, number: number, content: string): LoopDocument {
  return {
    ...emptyDocument(kind),
    state: "ready_for_review",
    current_revision_id: `${kind}-rev-${String(number)}`,
    current_revision_number: number,
    current_created_at: NOW,
    current_content: content,
  };
}

describe("summaryRevision", () => {
  it("reads the revision a summary's document line names", () => {
    expect(summaryRevision("approved r12")).toBe(12);
    expect(summaryRevision("ready_for_review r1")).toBe(1);
    expect(summaryRevision("empty")).toBeNull();
    expect(summaryRevision(undefined)).toBeNull();
  });
});

describe("documentsBehind", () => {
  const info = written("info", 1, "The intent.");
  const shown = { ...DOCUMENTS, info, analysis: written("analysis", 1, "The analysis.") };
  const current = { ...EMPTY, info: "ready_for_review r1", analysis: "ready_for_review r1" };

  it("is not behind on the current revisions, or before both are read", () => {
    expect(documentsBehind(current, shown)).toBe("no");
    expect(documentsBehind(undefined, shown)).toBe("no");
    expect(documentsBehind(current, undefined)).toBe("no");
  });

  it("calls a document nobody has on screen yet unread", () => {
    expect(
      documentsBehind({ ...current, roadmap_ai: "draft r1", roadmap: "draft r1" }, shown),
    ).toBe("unread");
  });

  it("calls a text on screen that is no longer the current one replaced", () => {
    expect(documentsBehind({ ...current, analysis: "ready_for_review r2" }, shown)).toBe(
      "replaced",
    );
    // Replaced wins over unread.
    expect(documentsBehind({ ...current, analysis: "draft r2", roadmap: "draft r1" }, shown)).toBe(
      "replaced",
    );
  });

  it("is not behind where the screen is ahead of a summary read before it", () => {
    // The person's own run wrote the analysis and the page read it; the summary is the older one.
    expect(documentsBehind({ ...current, analysis: "empty" }, shown)).toBe("no");
    const ahead = { ...shown, analysis: written("analysis", 3, "The third analysis.") };
    expect(documentsBehind({ ...current, analysis: "ready_for_review r2" }, ahead)).toBe("no");
  });

  it("calls Info replaced even when the page shows none, because a draft is saved against it", () => {
    expect(documentsBehind({ ...EMPTY, info: "draft r1" }, DOCUMENTS)).toBe("replaced");
  });
});

describe("the Plan tab when the documents change elsewhere", () => {
  /**
   * The Plan tab on `doc` for the member, over documents and a summary the test changes; `reads`
   * counts how often the documents were read. `followBoard` is what a change of the board does to
   * the page: the summaries are read again, the documents are not.
   */
  async function renderPlan(doc: PlanTab, documents: Record<DocumentKind, LoopDocument>) {
    const state = { documents, lines: linesOf(documents), reads: 0 };
    server.use(...planningDialogHandlers().handlers);
    server.use(
      http.get(apiPath(`${LOOP_PATH}/documents`), () => {
        state.reads += 1;
        return ok({
          loop_id: LOOP_ID,
          loop_version: 1,
          documents: state.documents,
          approvals: {},
        });
      }),
      http.get(apiPath(`/boards/${BOARD_ID}/loop-summaries`), () =>
        ok({
          board_id: BOARD_ID,
          loops: [summary(LOOP_ID, LOOP.name, { documents: state.lines })],
          count: 1,
        }),
      ),
    );
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const auth = {
      actor: MEMBER,
      loading: false,
      login: () => Promise.resolve(MEMBER),
      logout: () => Promise.resolve(),
      refresh: () => Promise.resolve(MEMBER),
      addressForgotten: false,
      signOutLocally: () => undefined,
    };
    // What the Loop page's `onChanged` does to these two.
    const onChanged = () => {
      void client.invalidateQueries({ queryKey: keys.loopDocuments(BOARD_ID, LOOP_ID) });
      void client.invalidateQueries({ queryKey: keys.loopSummaries(BOARD_ID) });
    };
    render(
      <QueryClientProvider client={client}>
        <AuthContext.Provider value={auth}>
          <ToastProvider>
            <LoopPlanTab
              boardId={BOARD_ID}
              loop={LOOP}
              doc={doc}
              onDocChange={() => undefined}
              readOnly={false}
              onChanged={onChanged}
            />
          </ToastProvider>
        </AuthContext.Provider>
      </QueryClientProvider>,
    );
    await waitFor(() => {
      expect(state.reads).toBe(1);
    });
    const handIn = (next: Record<DocumentKind, LoopDocument>) => {
      state.documents = next;
      state.lines = linesOf(next);
    };
    const followBoard = () =>
      act(() => client.invalidateQueries({ queryKey: keys.loopSummaries(BOARD_ID) }));
    return { state, handIn, followBoard, user: userEvent.setup() };
  }

  /** The summary's document lines for `documents`, as the server writes them. */
  function linesOf(documents: Record<DocumentKind, LoopDocument>): LoopSummary["documents"] {
    const line = (kind: DocumentKind) => {
      const number = documents[kind].current_revision_number;
      return number === null ? "empty" : `${documents[kind].state} r${String(number)}`;
    };
    return {
      info: line("info"),
      analysis_ai: line("analysis_ai"),
      analysis: line("analysis"),
      roadmap_ai: line("roadmap_ai"),
      roadmap: line("roadmap"),
    };
  }

  const info = () => screen.getByRole("textbox", { name: "Write or revise Info" });

  it("keeps a text on screen, says it changed, and reads the latest when asked", async () => {
    const first = { ...DOCUMENTS, info: written("info", 1, "First intent.") };
    const { state, handIn, followBoard, user } = await renderPlan("info", first);
    await waitFor(() => {
      expect(info()).toHaveValue("First intent.");
    });
    expect(screen.queryByText(DOCUMENTS_CHANGED_TEXT)).not.toBeInTheDocument();

    handIn({ ...DOCUMENTS, info: written("info", 2, "Second intent.") });
    await followBoard();

    expect(await screen.findByText(DOCUMENTS_CHANGED_TEXT)).toBeInTheDocument();
    await waitFor(() => {
      expect(announcer()).toHaveTextContent(DOCUMENTS_CHANGED_TEXT);
    });
    // The page did not read the documents by itself: the first text is still what it shows.
    expect(state.reads).toBe(1);
    expect(info()).toHaveValue("First intent.");

    await user.click(screen.getByRole("button", { name: "Show the latest" }));

    await waitFor(() => {
      expect(info()).toHaveValue("Second intent.");
    });
    await waitFor(() => {
      expect(screen.queryByText(DOCUMENTS_CHANGED_TEXT)).not.toBeInTheDocument();
    });
    // The line left with the button that had the focus; the open document's switch takes it.
    expect(screen.getByRole("button", { name: "Info", pressed: true })).toHaveFocus();
  });

  it("reads a document handed in while the page showed none by itself, once", async () => {
    const first = { ...DOCUMENTS, info: written("info", 1, "The intent.") };
    const { state, handIn, followBoard } = await renderPlan("analysis", first);

    handIn({
      ...first,
      analysis_ai: written("analysis_ai", 1, "{}"),
      analysis: written("analysis", 1, "The analysis."),
    });
    await followBoard();

    await waitFor(() => {
      expect(state.reads).toBe(2);
    });
    expect(screen.queryByText(DOCUMENTS_CHANGED_TEXT)).not.toBeInTheDocument();
    // Another change of the board that leaves the documents as they are reads nothing again.
    await followBoard();
    expect(state.reads).toBe(2);
  });
});
