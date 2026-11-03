import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http } from "msw";
import { describe, expect, it } from "vitest";
import { ToastProvider } from "@/components/ui/toast";
import { LoopNotesPanel } from "@/features/loops/LoopNotesPanel";
import type { LoopNote } from "@/lib/types";
import { apiPath, ok } from "./msw/envelope";
import { BOARD_ID, LOOP, LOOP_ID, LOOP_PATH, NOW } from "./msw/loops";
import { server } from "./msw/server";

function note(id: string, content: string, author = "Ada", type = "user"): LoopNote {
  return {
    id,
    loop_id: LOOP_ID,
    author_actor_id: `${author}-id`,
    author_actor_type: type,
    author_name: author,
    content,
    created_at: NOW,
  };
}

/** The notes the server holds; a POST appends one, as the service does. */
function answerNotes(start: LoopNote[]) {
  const notes = [...start];
  const posted: unknown[] = [];
  server.use(
    http.get(apiPath(`${LOOP_PATH}/notes`), () => ok({ notes, count: notes.length })),
    http.post(apiPath(`${LOOP_PATH}/notes`), async ({ request }) => {
      const body = (await request.json()) as { content: string };
      posted.push(body);
      const added = note(`n-${notes.length + 1}`, body.content);
      notes.push(added);
      return ok(added);
    }),
  );
  return posted;
}

function openPanel(readOnly = false) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={queryClient}>
      <ToastProvider>
        <LoopNotesPanel
          boardId={BOARD_ID}
          loop={LOOP}
          open
          readOnly={readOnly}
          onClose={() => undefined}
        />
      </ToastProvider>
    </QueryClientProvider>,
  );
}

describe("the Loop's notes", () => {
  it("lists the notes oldest first with their author, a worker marked as an agent", async () => {
    answerNotes([
      note("n-1", "Baseline: **master**"),
      note("n-2", "Gates passed", "Worker", "agent"),
    ]);
    openPanel();
    expect(await screen.findByText("Gates passed")).toBeInTheDocument();
    const list = screen.getByRole("list", { name: "Notes" });
    const items = within(list).getAllByRole("listitem");
    expect(items).toHaveLength(2);
    expect(items[0]).toHaveTextContent("Ada");
    expect(items[0]).toHaveTextContent("Baseline: master");
    expect(items[1]).toHaveTextContent("Worker (agent)");
  });

  it("adds a note and shows it", async () => {
    const posted = answerNotes([]);
    openPanel();
    expect(await screen.findByText("No notes yet.")).toBeInTheDocument();
    const user = userEvent.setup();
    expect(screen.getByRole("button", { name: "Add note" })).toBeDisabled();
    await user.type(screen.getByRole("textbox", { name: "New note" }), "Deployed to staging");
    await user.click(screen.getByRole("button", { name: "Add note" }));
    expect(await screen.findByText("Deployed to staging")).toBeInTheDocument();
    expect(posted).toEqual([{ content: "Deployed to staging" }]);
    expect(screen.getByRole("textbox", { name: "New note" })).toHaveValue("");
  });

  it("offers no box on a read-only Loop", async () => {
    answerNotes([note("n-1", "Done")]);
    openPanel(true);
    expect(await screen.findByText("Done")).toBeInTheDocument();
    expect(screen.queryByRole("textbox", { name: "New note" })).not.toBeInTheDocument();
  });
});
