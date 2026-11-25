import { screen, waitFor, within } from "@testing-library/react";
import { http } from "msw";
import { describe, expect, it } from "vitest";
import type { Loop } from "@/lib/types";
import { apiPath, ok } from "./msw/envelope";
import { LOOP, LOOP_PATH } from "./msw/loops";
import { PHASE_NAME } from "./msw/ticketView";
import { query, renderLoopPage, TITLE } from "./renderLoopPage";

/** The Loop at `stage` without a plan, its one Ticket done when it is in progress. */
function withoutPlan(stage: Loop["stage"]): Loop {
  const completed = stage === "in_progress" ? 1 : 0;
  return {
    ...LOOP,
    stage,
    without_plan: true,
    warnings: [],
    progress: { ticket_total: 1, ticket_completed: completed, ticket_archived_incomplete: 0 },
  };
}

describe("the Loop page's header", () => {
  it("shows the key, the stage, what it waits for and the one decision", async () => {
    const { header, user } = await renderLoopPage("", "analysis_review", {});
    expect(within(header).getByText("SES-1")).toHaveClass("font-mono");
    expect(within(header).getByText("Analysis review")).toBeInTheDocument();
    expect(
      await within(header).findByText("Waits for you to approve the analysis"),
    ).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Kanban" })).toHaveAttribute("aria-selected", "true");

    // The approval binds to the text on screen, so the header opens the analysis to decide on.
    await user.click(within(header).getByRole("button", { name: "Approve analysis" }));
    expect(query()).toHaveTextContent("?tab=plan&doc=analysis");
    expect(screen.getByRole("tab", { name: "Plan" })).toHaveAttribute("aria-selected", "true");
    const documents = await screen.findByRole("region", { name: "Planning documents" });
    const approve = await within(documents).findByRole("button", { name: "Approve analysis" });
    expect(screen.getAllByRole("button", { name: "Approve analysis" })).toEqual([approve]);
  });

  it("offers no decision when the next step is not the person's, only the quiet menu", async () => {
    const { header } = await renderLoopPage("", "in_progress", { tickets: { ready: 1 } });
    expect(await within(header).findByText("1 Ticket ready to start")).toBeInTheDocument();
    expect(
      within(header)
        .getAllByRole("button")
        .map((button) => button.textContent),
    ).toEqual([""]);
    expect(within(header).getByRole("button", { name: "Loop actions" })).toBeInTheDocument();
  });

  it("edits the Loop's name against its version from the menu", async () => {
    const { header, writes, user } = await renderLoopPage("", "in_progress", {});
    await user.click(within(header).getByRole("button", { name: "Loop actions" }));
    await user.click(screen.getByRole("menuitem", { name: "Edit Loop" }));
    const dialog = screen.getByRole("dialog", { name: "Edit Loop" });
    const name = within(dialog).getByLabelText("Name");
    await user.clear(name);
    await user.type(name, "Session limits");
    await user.click(within(dialog).getByRole("button", { name: "Save" }));
    await waitFor(() => {
      expect(writes).toEqual([
        { route: `PATCH ${LOOP_PATH}`, body: { version: 1, name: "Session limits", goal: "" } },
      ]);
    });
    expect(screen.queryByRole("dialog", { name: "Edit Loop" })).not.toBeInTheDocument();
  });

  it("marks a Loop without a plan and closes it from the header's one decision", async () => {
    const { header, user } = await renderLoopPage(
      "",
      "in_progress",
      { tickets: { total: 1, completed: 1 }, without_plan: true },
      [http.get(apiPath(LOOP_PATH), () => ok(withoutPlan("in_progress")))],
    );
    expect(within(header).getByText("In progress")).toBeInTheDocument();
    expect(within(header).getByText("Without a plan")).toBeInTheDocument();
    expect(within(header).getByText(/1\/1 Tickets done/)).toBeInTheDocument();
    expect(await within(header).findByText("Waits for you to close the Loop")).toBeInTheDocument();

    await user.click(within(header).getByRole("button", { name: "Close Loop" }));
    const dialog = await screen.findByRole("dialog", { name: "Close SES-1" });
    expect(within(dialog).getByRole("button", { name: "Close the Loop" })).toBeInTheDocument();
    expect(within(dialog).queryByText("Was QA performed?")).toBeNull();
  });

  it("offers Close Loop in the menu of a Loop without a plan while Tickets are open", async () => {
    const { header, user } = await renderLoopPage(
      "",
      "ready",
      { tickets: { ready: 1, total: 1 }, without_plan: true, waiting_on: "anyone" },
      [http.get(apiPath(LOOP_PATH), () => ok(withoutPlan("ready")))],
    );
    expect(await within(header).findByText("1 Ticket ready to start")).toBeInTheDocument();
    await user.click(within(header).getByRole("button", { name: "Loop actions" }));
    expect(screen.queryByRole("menuitem", { name: /Finalize Loop/ })).toBeNull();
    await user.click(screen.getByRole("menuitem", { name: "Close Loop" }));
    expect(await screen.findByRole("dialog", { name: "Close SES-1" })).toBeInTheDocument();
  });

  it("shows a draft's Finalize Loop without offering it", async () => {
    const { header, user } = await renderLoopPage("", "draft", {});
    await user.click(within(header).getByRole("button", { name: "Loop actions" }));
    const finalize = screen.getByRole("menuitem", {
      name: "Finalize Loop: Nothing to finalize yet: add a Ticket or plan the Loop",
    });
    expect(finalize).toHaveAttribute("aria-disabled", "true");
    await user.click(finalize);
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("asks before it cancels the Loop", async () => {
    const { header, writes, user } = await renderLoopPage("", "in_progress", {});
    await user.click(within(header).getByRole("button", { name: "Loop actions" }));
    await user.click(screen.getByRole("menuitem", { name: "Cancel Loop" }));
    const dialog = screen.getByRole("dialog", { name: "Cancel Loop" });
    expect(writes).toEqual([]);
    await user.type(within(dialog).getByLabelText("Why (optional)"), "Replaced by SES-2");
    await user.click(within(dialog).getByRole("button", { name: "Cancel Loop" }));
    await waitFor(() => {
      expect(writes).toEqual([
        {
          route: `POST ${LOOP_PATH}/cancel`,
          body: { version: 1, reason: "Replaced by SES-2" },
        },
      ]);
    });
  });
});

describe("the Loop page's tabs", () => {
  it("switch between Kanban, Plan and Notes and keep the tab in the URL", async () => {
    const { user } = await renderLoopPage("", "in_progress", {});
    const backlog = await screen.findByRole("region", { name: "Column Backlog" });
    expect(await within(backlog).findByText("The key is rotated every 90 days.")).toBeVisible();
    expect(query()).toHaveTextContent("");

    await user.click(screen.getByRole("tab", { name: "Notes" }));
    expect(query()).toHaveTextContent("?tab=notes");
    expect(await screen.findByText("No notes yet.")).toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "Column Backlog" })).not.toBeInTheDocument();

    await user.click(screen.getByRole("tab", { name: "Kanban" }));
    expect(query()).toBeEmptyDOMElement();
    expect(screen.getByRole("region", { name: "Column Backlog" })).toBeInTheDocument();
  });

  it("land on the Plan tab from a link, with the planning documents alone", async () => {
    await renderLoopPage("?tab=plan", "in_progress", {});
    expect(screen.getByRole("tab", { name: "Plan" })).toHaveAttribute("aria-selected", "true");
    const documents = screen.getByRole("region", { name: "Planning documents" });
    for (const name of ["Info", "Analysis", "RoadMap"]) {
      expect(within(documents).getByRole("button", { name })).toBeInTheDocument();
    }
    // A Loop in delivery opens its RoadMap.
    expect(
      await within(documents).findByRole("button", { name: /Generate RoadMap/ }),
    ).toBeInTheDocument();
    // The plan's Tickets are on the Kanban; the Plan tab does not list them again.
    expect(screen.queryByRole("region", { name: "Phases and readiness" })).not.toBeInTheDocument();
    expect(screen.queryByText(PHASE_NAME)).not.toBeInTheDocument();
  });

  it("open a Ticket over the Plan tab and close it back to the Plan tab", async () => {
    const { user } = await renderLoopPage("?tab=plan&card=card-1", "in_progress", {});
    const dialog = await screen.findByRole("dialog", { name: TITLE });
    expect(screen.getByRole("tab", { name: "Plan", hidden: true })).toHaveAttribute(
      "aria-selected",
      "true",
    );
    await user.click(within(dialog).getByRole("button", { name: "Close dialog" }));
    await waitFor(() => {
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    });
    expect(query()).toHaveTextContent("?tab=plan");
    expect(query()).not.toHaveTextContent("card");
  });
});
