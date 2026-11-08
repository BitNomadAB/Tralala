import { screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ended, event, RUN_ID, talkEvents, talking } from "./msw/discussionRuns";
import { discussion } from "./msw/discussions";
import { MEMBER } from "./msw/session";
import { MODAL_URL, renderDiscussion } from "./renderDiscussion";

const CSRF = "csrf-discussion";

function sign() {
  return screen.getByRole("region", { name: "Tralala's suggestion" });
}

function row(name: string) {
  return within(screen.getByRole("list", { name: "Answers" })).getByRole("listitem", { name });
}

function summary(title: string): HTMLElement {
  const found = Array.from(document.querySelectorAll("summary")).find(
    (node) => node.textContent === title,
  );
  if (!(found instanceof HTMLElement)) throw new Error(`No expander "${title}"`);
  return found;
}

describe("the runs: idle", () => {
  it("offers Let them talk it out with the rounds left, and sends rounds and budgets", async () => {
    const { user, api } = await renderDiscussion();
    await user.click(screen.getByRole("button", { name: "Let them talk it out" }));
    const dialog = screen.getByRole("dialog", { name: "Let them talk it out" });
    expect(dialog).toHaveTextContent(
      "The agents answer each other for up to 2 rounds and stop when they agree or when the budget is spent.",
    );
    await user.click(summary("Options"));
    const rounds = within(dialog).getByLabelText("Rounds");
    expect(rounds).toHaveValue(2);
    expect(rounds).toHaveAttribute("max", "2");
    expect(dialog).toHaveTextContent("Empty means the server's default.");
    await user.clear(rounds);
    await user.type(rounds, "1");
    await user.type(within(dialog).getByLabelText("Token budget"), "8000");
    await user.type(within(dialog).getByLabelText("Time budget in seconds"), "120");
    api.state.next.start = talking();
    await user.click(within(dialog).getByRole("button", { name: "Start" }));
    await waitFor(() =>
      expect(api.state.bodies).toEqual([
        {
          route: "start",
          body: { autonomous: true, rounds: 1, token_budget: 8000, time_budget_seconds: 120 },
          csrf: CSRF,
        },
      ]),
    );
    await waitFor(() =>
      expect(screen.queryByRole("dialog", { name: "Let them talk it out" })).toBeNull(),
    );
    expect(await screen.findByRole("button", { name: "Stop" })).toBeEnabled();
  });

  it("sends no budget when the fields are left empty", async () => {
    const { user, api } = await renderDiscussion();
    await user.click(screen.getByRole("button", { name: "Let them talk it out" }));
    await user.click(screen.getByRole("button", { name: "Start" }));
    await waitFor(() => expect(api.state.bodies).toHaveLength(1));
    expect(api.state.bodies[0]?.body).toStrictEqual({ autonomous: true, rounds: 2 });
  });

  it("is disabled with the reason when no round is left or the discussion is decided", async () => {
    await renderDiscussion(discussion({ round_count: 4 }));
    const talk = screen.getByRole("button", { name: "Let them talk it out" });
    expect(talk).toBeDisabled();
    expect(talk).toHaveAttribute("title", "No round is left: the discussion has had all 4");
  });

  it("stays disabled once decided, beside More only", async () => {
    await renderDiscussion(discussion({ status: "approved" }));
    const talk = screen.getByRole("button", { name: "Let them talk it out" });
    expect(talk).toBeDisabled();
    expect(talk).toHaveAttribute("title", "The discussion is decided");
    expect(screen.queryByRole("button", { name: "Approve" })).toBeNull();
  });
});

describe("the runs: while the agents talk", () => {
  it("says where they are, gives Stop in place of the decision and holds the reply", async () => {
    await renderDiscussion(talking(), MODAL_URL, talkEvents());
    expect(sign()).toHaveTextContent("Agents are answering· round 3 of 4");
    expect(await within(sign()).findByText("1 of 4 agents have answered this round")).toBeVisible();
    for (const name of ["Approve", "Request rework", "Veto", "Let them talk it out"]) {
      expect(screen.queryByRole("button", { name })).toBeNull();
    }
    expect(screen.getByRole("button", { name: "Stop" })).toBeEnabled();
    expect(screen.getByRole("textbox", { name: "Reply" })).toBeDisabled();
    expect(screen.getByRole("textbox", { name: "Reply" })).toHaveAccessibleDescription(
      "The agents are answering. Reply once they are done.",
    );
    expect(screen.getByRole("button", { name: "Ask again" })).toBeDisabled();
    expect(screen.getByRole("region", { name: "Status" })).toHaveTextContent(
      "Agents are answering· round 3 of 4",
    );
  });

  it("says under its row that an agent could not be reached", async () => {
    await renderDiscussion(talking(), MODAL_URL, talkEvents());
    expect(
      await within(row("Bravo")).findByText(
        "No answer from Bravo: the agent could not be reached.",
      ),
    ).toBeVisible();
    expect(row("Alpha")).not.toHaveTextContent("could not be reached");
    expect(screen.getByRole("tabpanel", { name: "For you" })).not.toHaveTextContent(
      "connection_refused",
    );
  });

  it("stops the run with Stop and then says who stopped it", async () => {
    const { user, api } = await renderDiscussion(talking(), MODAL_URL, talkEvents());
    api.state.next.stop = ended({ status: "stopped", stop_reason: "human_stop" });
    api.state.events = [
      ...talkEvents(),
      event(7, "run_finished", { run_id: RUN_ID, run_status: "stopped" }, MEMBER.name),
    ];
    await user.click(screen.getByRole("button", { name: "Stop" }));
    await waitFor(() =>
      expect(api.state.bodies).toEqual([{ route: `runs/${RUN_ID}/stop`, body: {}, csrf: CSRF }]),
    );
    await waitFor(() =>
      expect(screen.getByRole("region", { name: "Status" })).toHaveTextContent(
        "Stopped by Ada Member",
      ),
    );
    // The rail's status and the line under the sign.
    expect(screen.getAllByText("Stopped by Ada Member")).toHaveLength(2);
    expect(screen.getByText("The run is stopped")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Approve" })).toBeEnabled();
  });

  it("pauses and resumes from More", async () => {
    const { user, api } = await renderDiscussion(talking(), MODAL_URL, talkEvents());
    api.state.next.pause = talking("paused");
    await user.click(screen.getByRole("button", { name: "More actions" }));
    await user.click(screen.getByRole("menuitem", { name: "Pause while they talk" }));
    await waitFor(() =>
      expect(screen.getByRole("region", { name: "Status" })).toHaveTextContent("Paused"),
    );
    expect(within(sign()).queryByText(/have answered this round/)).toBeNull();
    expect(screen.getByRole("button", { name: "Stop" })).toBeEnabled();
    expect(screen.getByRole("textbox", { name: "Reply" })).toBeDisabled();

    api.state.next.resume = talking();
    await user.click(screen.getByRole("button", { name: "More actions" }));
    await user.click(screen.getByRole("menuitem", { name: "Resume" }));
    await waitFor(() =>
      expect(api.state.bodies.map((entry) => entry.route)).toEqual([
        `runs/${RUN_ID}/pause`,
        `runs/${RUN_ID}/resume`,
      ]),
    );
    await waitFor(() =>
      expect(screen.getByRole("region", { name: "Status" })).toHaveTextContent(
        "Agents are answering",
      ),
    );
  });

  it("offers Pause and Stop the run in the rail's More", async () => {
    const { user, api } = await renderDiscussion(talking(), MODAL_URL, talkEvents());
    const rail = screen.getByRole("complementary", { name: "Status and facts" });
    await user.click(within(rail).getByText("More"));
    await user.click(within(rail).getByRole("button", { name: "Stop the run" }));
    await waitFor(() =>
      expect(api.state.bodies).toEqual([{ route: `runs/${RUN_ID}/stop`, body: {}, csrf: CSRF }]),
    );
    expect(within(rail).getByRole("button", { name: "Pause while they talk" })).toBeEnabled();
  });
});

describe("the runs: finished", () => {
  it("tells in plain words that no agent could be reached, and keeps the codes in Raw text", async () => {
    const failed = ended({
      status: "failed",
      stop_reason: "all_participants_failed",
      rounds_completed: 1,
    });
    const events = [
      ...talkEvents(),
      event(7, "agent_failed", {
        participant_id: "agent-Charlie",
        agent: "Charlie",
        round_number: 1,
        error: "timeout",
      }),
      event(8, "round_completed", { run_id: RUN_ID, round_number: 1 }),
      event(9, "run_finished", { run_id: RUN_ID, run_status: "failed" }),
    ];
    const { user } = await renderDiscussion(failed, MODAL_URL, events);
    expect(await screen.findByText("No agent could be reached")).toBeVisible();
    expect(screen.getByRole("button", { name: "Let them talk it out" })).toBeEnabled();
    expect(
      await within(row("Charlie")).findByText(
        "No answer from Charlie: the agent could not be reached.",
      ),
    ).toBeVisible();
    const forYou = screen.getByRole("tabpanel", { name: "For you" });
    expect(forYou).not.toHaveTextContent("all_participants_failed");
    await user.click(screen.getByRole("tab", { name: "Raw text" }));
    const raw = screen.getByRole("tabpanel", { name: "Raw text" });
    expect(raw).toHaveTextContent(
      "Run 3 · 2026-11-08T10:10:00Z · failed · autonomous · rounds 1 of 2",
    );
    expect(raw).toHaveTextContent("stop: all_participants_failed · error: none");
    expect(raw).toHaveTextContent("Failed in round 1 · Bravo · connection_refused");
    expect(raw).toHaveTextContent("Failed in round 1 · Charlie · timeout");
    expect(raw).toHaveTextContent("Run 1 · ");
  });

  it("says the budget ran out", async () => {
    await renderDiscussion(ended({ status: "budget_exhausted", stop_reason: "token_budget" }));
    expect(screen.getByText("The budget ran out")).toBeVisible();
  });

  it("puts no line under the sign when the agents agree", async () => {
    await renderDiscussion(ended({ status: "completed", stop_reason: "consensus" }));
    expect(screen.queryByText("The agents agree")).toBeNull();
  });
});
