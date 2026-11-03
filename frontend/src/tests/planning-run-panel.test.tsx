import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http } from "msw";
import { describe, expect, it } from "vitest";
import { ToastProvider } from "@/components/ui/toast";
import { LoopDocumentDialog } from "@/features/loops/LoopDocumentDialog";
import { apiPath, ok } from "./msw/envelope";
import { BOARD_ID, generationRun, LOOP, LOOP_PATH, planningDialogHandlers } from "./msw/loops";
import { server } from "./msw/server";

/** A Loop with nothing generated yet; a started analysis run stays on its generating step. */
function planningServer() {
  server.use(
    ...planningDialogHandlers().handlers,
    http.post(apiPath(`${LOOP_PATH}/generation-runs`), () => ok(generationRun("queued", null))),
    http.get(apiPath(`${LOOP_PATH}/generation-runs/run-1`), () =>
      ok(generationRun("running", "generating")),
    ),
  );
}

async function startAnalysis() {
  planningServer();
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
  const user = userEvent.setup();
  await user.click(await screen.findByRole("button", { name: /Generate analysis/ }));
  expect(await screen.findByRole("button", { name: /Generating…/ })).toBeDisabled();
}

/** Every run panel on the page; jsdom applies no CSS, so the breakpoint is read from the class. */
async function runPanels() {
  const panels = await screen.findAllByRole("region", {
    name: "Generation progress",
    hidden: true,
  });
  const below2xl = panels.filter((panel) => panel.parentElement?.classList.contains("2xl:hidden"));
  const from2xl = panels.filter((panel) => panel.parentElement?.classList.contains("2xl:block"));
  return { panels, below2xl, from2xl };
}

describe("the planning dialog's run panel", () => {
  it("shows the run's steps once in the dialog below 2xl, and once beside it from 2xl", async () => {
    await startAnalysis();
    const { panels, below2xl, from2xl } = await runPanels();

    // Was two compact panels in the dialog, one above and one below the tabs, both visible on any
    // screen narrower than 2xl.
    expect(below2xl).toHaveLength(1);
    expect(from2xl).toHaveLength(1);
    expect(panels).toHaveLength(2);
    const dialog = screen.getByRole("dialog", { name: /planning documents/ });
    const compact = within(dialog).getByRole("region", {
      name: "Generation progress",
      hidden: true,
    });
    expect(below2xl).toEqual([compact]);
    // The compact panel sits under the button that started the run.
    const generating = within(dialog).getByRole("button", { name: /Generating…/ });
    expect(
      generating.compareDocumentPosition(compact) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
    expect(within(compact).getByText("Generating analysis")).toBeInTheDocument();
  });

  it("places the wide-screen panel 24 px right of the 960 px dialog, not at the window edge", async () => {
    await startAnalysis();
    const { from2xl } = await runPanels();
    const aside = from2xl[0]?.parentElement;
    expect(aside?.tagName).toBe("ASIDE");
    // Half the dialog's 960 px plus 24 px from the middle of the window, centred vertically.
    expect(aside).toHaveClass("fixed", "left-[calc(50%+504px)]", "top-1/2", "-translate-y-1/2");
    expect(aside).not.toHaveClass("right-6");
    const dialog = screen.getByRole("dialog", { name: /planning documents/ });
    expect(dialog).toHaveClass("w-[min(960px,96vw)]");
  });

  it("announces the started run with an ellipsis, not a question mark", async () => {
    await startAnalysis();

    expect(await screen.findByText("Following the run…")).toBeInTheDocument();
    expect(screen.queryByText("Following the run?")).not.toBeInTheDocument();
  });
});
