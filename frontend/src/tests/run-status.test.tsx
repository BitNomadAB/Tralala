import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http } from "msw";
import { describe, expect, it } from "vitest";
import { RunPhases } from "@/features/loops/RunPhases";
import { nearBottom, runProgressLine, runPurpose } from "@/features/loops/runStatus";
import type { RunTraceStep } from "@/lib/types";
import { announcer } from "./announcer";
import { apiPath, ok } from "./msw/envelope";
import { generationRun, LOOP_ID, LOOP_PATH, planningDialogHandlers } from "./msw/loops";
import { server } from "./msw/server";
import { renderDocuments } from "./renderDocuments";

const AT = "2026-11-03T10:00:00Z";

const step = (stage: RunTraceStep["stage"], text: string): RunTraceStep => ({
  stage,
  kind: "step",
  text,
  at: AT,
});

const READING: RunTraceStep[] = [
  step("documents", "Read the Loop's Info (revision 2)"),
  step("repository", "Opened app @ aaaaaaaa: 3 files"),
];

const running = (trace: RunTraceStep[]) => generationRun("running", "generating", { trace });

describe("the line a screen reader hears about a run", () => {
  it("names the stage the run is in, and only changes when the stage does", () => {
    expect(runProgressLine("analysis", running(READING))).toBe(
      "Step 2 of 5: reading the repository",
    );
    // Another step inside the same stage says nothing new.
    const more = [...READING, step("repository", "Read app/docs/install.md")];
    expect(runProgressLine("analysis", running(more))).toBe("Step 2 of 5: reading the repository");
    const writing = [...more, step("writing", "Asked the model")];
    expect(runProgressLine("analysis", running(writing))).toBe("Step 3 of 5: writing the analysis");
  });

  it("is quiet once the run has ended, which its toast says", () => {
    const failed = generationRun("failed", "generating", { trace: READING });
    expect(runProgressLine("analysis", failed)).toBeNull();
    expect(runProgressLine("analysis", generationRun("completed", "generating"))).toBeNull();
  });

  it("counts the three fixed phases of a run recorded before the tree", () => {
    expect(runProgressLine("roadmap", generationRun("running", "generating"))).toBe(
      "Step 3 of 3: generating RoadMap",
    );
  });

  it("follows the run's own purpose, whichever document is open", () => {
    expect(runPurpose("roadmap", generationRun("running", "generating"))).toBe("analysis");
    const brief = generationRun("running", null, { purpose: "roadmap_human" });
    expect(runPurpose("analysis", brief)).toBe("roadmap_human");
  });
});

describe("the run panel", () => {
  it("is not a live region, and says each stage's state in words", () => {
    render(<RunPhases purpose="analysis" run={running(READING)} />);
    const panel = screen.getByRole("region", { name: "Generation progress" });
    expect(panel).not.toHaveAttribute("aria-live");
    expect(within(panel).getByText("Reading the Loop's documents")).toHaveTextContent(
      "Reading the Loop's documents, done",
    );
    expect(within(panel).getByText("Reading the repository")).toHaveTextContent(
      "Reading the repository, in progress",
    );
    expect(within(panel).getByText("Saving")).toHaveTextContent("Saving, not started");
  });

  it("says the states in words when compact, captions or not", () => {
    render(<RunPhases purpose="analysis" compact run={running(READING)} />);
    expect(screen.getByText("Reading the repository")).toHaveTextContent(
      "Reading the repository, in progress",
    );
    const legacy = generationRun("failed", "generating");
    render(<RunPhases purpose="analysis" compact run={legacy} />);
    expect(screen.getByText("Generating analysis")).toHaveTextContent(
      "Generating analysis, failed",
    );
  });

  it("follows the newest step only while the person is at the end of the list", () => {
    const { rerender } = render(<RunPhases purpose="analysis" run={running(READING)} />);
    const [list] = within(screen.getByRole("region", { name: "Generation progress" })).getAllByRole(
      "list",
    );
    if (!list) throw new Error("no step list");
    Object.defineProperty(list, "clientHeight", { configurable: true, value: 200 });
    Object.defineProperty(list, "scrollHeight", { configurable: true, value: 1000 });

    // Scrolled up to read an earlier step: a new step leaves the list where it is.
    list.scrollTop = 100;
    fireEvent.scroll(list);
    const more = [...READING, step("repository", "Read app/docs/install.md")];
    rerender(<RunPhases purpose="analysis" run={running(more)} />);
    expect(list.scrollTop).toBe(100);

    // Back at the end: the next step is brought into view.
    list.scrollTop = 790;
    fireEvent.scroll(list);
    Object.defineProperty(list, "scrollHeight", { configurable: true, value: 1200 });
    rerender(<RunPhases purpose="analysis" run={running([...more, step("writing", "Asked")])} />);
    expect(list.scrollTop).toBe(1200);
  });

  it("counts a box within two lines of its end as at the end", () => {
    expect(nearBottom({ scrollTop: 800, scrollHeight: 1000, clientHeight: 200 })).toBe(true);
    expect(nearBottom({ scrollTop: 770, scrollHeight: 1000, clientHeight: 200 })).toBe(true);
    expect(nearBottom({ scrollTop: 600, scrollHeight: 1000, clientHeight: 200 })).toBe(false);
  });
});

describe("the Plan tab while a run works", () => {
  it("announces one line when the run reaches another stage", async () => {
    let trace = READING;
    server.use(
      ...planningDialogHandlers().handlers,
      http.post(apiPath(`${LOOP_PATH}/generation-runs`), () => ok(generationRun("queued", null))),
      http.get(apiPath(`${LOOP_PATH}/generation-runs/run-1`), () => ok(running(trace))),
    );
    const queryClient = renderDocuments("analysis");
    await userEvent.setup().click(await screen.findByRole("button", { name: /Generate analysis/ }));

    await waitFor(() => {
      expect(announcer()).toHaveTextContent("Step 2 of 5: reading the repository");
    });
    trace = [...READING, step("writing", "Asked the model")];
    await queryClient.invalidateQueries({ queryKey: ["generation-run", LOOP_ID, "run-1"] });
    await waitFor(() => {
      expect(announcer()).toHaveTextContent("Step 3 of 5: writing the analysis");
    });
  });
});
