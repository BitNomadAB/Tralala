import { screen, waitFor, within } from "@testing-library/react";
import { http } from "msw";
import { describe, expect, it } from "vitest";
import { STOPS_DEFAULT, STOPS_RULE } from "@/features/loops/stopList";
import type { Loop, PocCounts } from "@/lib/types";
import { announcer } from "./announcer";
import { apiPath, ok } from "./msw/envelope";
import { LOOP, LOOP_PATH } from "./msw/loops";
import { pocDecision, pocHandlers } from "./msw/poc";
import { query, renderLoopPage } from "./renderLoopPage";

const NONE: PocCounts = { open: 0, built_on_open: 0, missing_open: 0, due: 0, answered: 0 };

/** Two due, one of them built on; one missing from a person; four open in all. */
const ITEMS = [
  pocDecision(1, { due: true, built_on: true, builds_on: "The report counts on it." }),
  pocDecision(2, { due: true }),
  pocDecision(3, { kind: "missing", missing: "A key.", title: "The mail key" }),
  pocDecision(4),
];
const COUNTS: PocCounts = { open: 4, built_on_open: 1, missing_open: 1, due: 2, answered: 0 };

describe("the Decisions tab on the Loop page", () => {
  it("carries the number of open ones beside its name, and none when nothing is open", async () => {
    await renderLoopPage("", "in_progress", { poc_decisions: COUNTS });
    expect(await screen.findByRole("tab", { name: "Decisions 4" })).toBeInTheDocument();
  });

  it("has no number while nothing is open", async () => {
    await renderLoopPage("", "in_progress", { poc_decisions: { ...NONE, answered: 2 } });
    expect(screen.getByRole("tab", { name: "Decisions" })).toBeInTheDocument();
  });
});

describe("the notice above the tabs", () => {
  it("says how many wait for a review, how many other work builds on and what is missing", async () => {
    const poc = pocHandlers(ITEMS);
    const { user } = await renderLoopPage(
      "",
      "in_progress",
      { poc_decisions: COUNTS },
      poc.handlers,
    );
    const notice = await screen.findByRole("region", { name: "Decisions to review" });
    expect(
      await within(notice).findByText(
        "2 POC decisions wait for your review; other work builds on 1 of them.",
      ),
    ).toBeInTheDocument();
    expect(within(notice).getByText("1 thing is missing from a person.")).toBeInTheDocument();
    await user.click(within(notice).getByRole("button", { name: "Review decisions" }));
    expect(query()).toHaveTextContent("?tab=decisions");
    expect(screen.getByRole("tab", { name: "Decisions 4" })).toHaveAttribute(
      "aria-selected",
      "true",
    );
  });

  it("is not there while nothing is due or missing", async () => {
    await renderLoopPage("", "in_progress", { poc_decisions: { ...NONE, open: 3 } });
    await screen.findByRole("tab", { name: "Decisions 3" });
    expect(screen.queryByRole("region", { name: "Decisions to review" })).toBeNull();
  });
});

describe("the dialogs that close a Loop", () => {
  it("say how many are not answered and lead to the tab, holding nothing up", async () => {
    const planned = { ...LOOP, stage: "in_progress" } satisfies Loop;
    const { user } = await renderLoopPage(
      "?dialog=completion",
      "in_progress",
      { poc_decisions: { ...NONE, open: 2 } },
      [http.get(apiPath(LOOP_PATH), () => ok(planned)), ...pocHandlers([]).handlers],
    );
    const dialog = await screen.findByRole("dialog", { name: "SES-1 completion and QA" });
    expect(
      await within(dialog).findByText(
        /2 POC decisions are not answered\. They cannot be answered once the Loop is closed\./,
      ),
    ).toBeInTheDocument();
    expect(
      within(dialog).getByRole("button", { name: "Accept implementation" }),
    ).not.toHaveAttribute("aria-disabled");
    await user.click(within(dialog).getByRole("link", { name: "Open the Decisions tab" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(query()).toHaveTextContent("?tab=decisions");
  });

  it("say it in the dialog that closes a Loop without a plan too", async () => {
    const withoutPlan: Loop = { ...LOOP, stage: "in_progress", without_plan: true, warnings: [] };
    await renderLoopPage(
      "?dialog=completion",
      "in_progress",
      {
        without_plan: true,
        tickets: { total: 1, completed: 1 },
        poc_decisions: { ...NONE, open: 1 },
      },
      [http.get(apiPath(LOOP_PATH), () => ok(withoutPlan))],
    );
    const dialog = await screen.findByRole("dialog", { name: "Close SES-1" });
    expect(
      await within(dialog).findByText(
        /1 POC decision is not answered\. It cannot be answered once the Loop is closed\./,
      ),
    ).toBeInTheDocument();
  });
});

describe("the stop list under Info", () => {
  async function renderStops(stage: Loop["stage"] = "draft") {
    const poc = pocHandlers([]);
    const page = await renderLoopPage("?tab=plan&doc=info", stage, {}, poc.handlers);
    const stops = await screen.findByRole("region", { name: "Stops" });
    await within(stops).findByRole("list", { name: "Stops" });
    return { ...page, poc, stops };
  }

  it("shows the lines, what they mean and that it is the default list", async () => {
    const { stops } = await renderStops();
    expect(within(stops).getByText(STOPS_RULE)).toBeInTheDocument();
    expect(within(stops).getByText(STOPS_DEFAULT)).toBeInTheDocument();
    expect(
      within(stops)
        .getAllByRole("listitem")
        .map((item) => item.textContent),
    ).toContain("Money");
  });

  it("lets a person edit the list, one line a stop, and save it", async () => {
    const { stops, poc, user } = await renderStops();
    await user.click(within(stops).getByRole("button", { name: "Edit stops" }));
    const field = within(stops).getByLabelText("Stops, one a line");
    expect(field).toHaveFocus();
    await user.clear(field);
    await user.type(field, "Money{Enter}{Enter}  Deleting data  {Enter}");
    await user.click(within(stops).getByRole("button", { name: "Save stops" }));
    await waitFor(() =>
      expect(
        within(stops)
          .getAllByRole("listitem")
          .map((item) => item.textContent),
      ).toEqual(["Money", "Deleting data"]),
    );
    expect(poc.state.stopWrites).toEqual([{ stops: ["Money", "Deleting data"] }]);
    expect(within(stops).queryByText(STOPS_DEFAULT)).toBeNull();
    await waitFor(() =>
      expect(within(stops).getByRole("button", { name: "Edit stops" })).toHaveFocus(),
    );
    await waitFor(() => expect(announcer()).toHaveTextContent("Stops saved"));
  });

  it("shows the server's refusal and keeps the draft", async () => {
    const { stops, user } = await renderStops();
    await user.click(within(stops).getByRole("button", { name: "Edit stops" }));
    const field = within(stops).getByLabelText("Stops, one a line");
    await user.clear(field);
    await user.type(field, "x".repeat(141));
    await user.click(within(stops).getByRole("button", { name: "Save stops" }));
    expect(await within(stops).findByRole("alert")).toHaveTextContent(
      "Line 1 has more than 140 characters.",
    );
    expect(within(stops).getByLabelText("Stops, one a line")).toHaveValue("x".repeat(141));
  });

  it("is read-only in a read-only Loop", async () => {
    const { stops } = await renderStops("completed");
    expect(within(stops).queryByRole("button", { name: "Edit stops" })).toBeNull();
  });
});
