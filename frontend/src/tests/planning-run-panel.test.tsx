import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http } from "msw";
import { describe, expect, it } from "vitest";
import { apiPath, ok } from "./msw/envelope";
import { generationRun, LOOP_PATH, planningDialogHandlers } from "./msw/loops";
import { server } from "./msw/server";
import { renderDocuments } from "./renderDocuments";

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
  renderDocuments("analysis");
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

describe("the Plan tab's run panel", () => {
  it("shows the run's steps once under the button below 2xl, and once beside the documents from 2xl", async () => {
    await startAnalysis();
    const { panels, below2xl, from2xl } = await runPanels();

    // Was two compact panels, one above and one below the tabs, both visible on any screen
    // narrower than 2xl.
    expect(below2xl).toHaveLength(1);
    expect(from2xl).toHaveLength(1);
    expect(panels).toHaveLength(2);
    const compact = below2xl[0];
    if (!compact) throw new Error("no compact panel");
    // The compact panel sits under the button that started the run.
    const generating = screen.getByRole("button", { name: /Generating…/ });
    expect(
      generating.compareDocumentPosition(compact) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
    expect(within(compact).getByText("Generating analysis")).toBeInTheDocument();
  });

  it("places the wide-screen panel in a column beside the documents, not fixed to the window", async () => {
    await startAnalysis();
    const { from2xl } = await runPanels();
    const aside = from2xl[0]?.parentElement;
    expect(aside?.tagName).toBe("ASIDE");
    // The Plan tab's second column, kept in view while the page scrolls; it was fixed beside the
    // centred dialog and covered whatever the window showed there.
    expect(aside).toHaveClass("sticky", "hidden", "2xl:block");
    expect(aside).not.toHaveClass("fixed");
    const grid = aside?.parentElement;
    expect(grid).toHaveClass("grid", "2xl:grid-cols-[minmax(0,1fr)_15rem]");
    const generating = screen.getByRole("button", { name: /Generating…/ });
    expect(grid).toContainElement(generating);
    expect(aside).not.toContainElement(generating);
  });

  it("announces the started run with an ellipsis, not a question mark", async () => {
    await startAnalysis();

    expect(await screen.findByText("Following the run…")).toBeInTheDocument();
    expect(screen.queryByText("Following the run?")).not.toBeInTheDocument();
  });
});
