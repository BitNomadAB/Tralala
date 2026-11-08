import { screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { answer, discussion, QUESTION, REASON, REASONING, TICKET_KEY } from "./msw/discussions";
import { renderDiscussion } from "./renderDiscussion";

/** An expander by the start of its title (the hint follows it in the summary). */
function expander(title: string): HTMLElement {
  const summary = Array.from(document.querySelectorAll("summary")).find((node) =>
    (node.textContent ?? "").startsWith(title),
  );
  const details = summary?.closest("details");
  if (!details) throw new Error(`No expander "${title}"`);
  return details;
}

function row(name: string) {
  return within(screen.getByRole("list", { name: "Answers" })).getByRole("listitem", { name });
}

describe("the discussion view", () => {
  it("shows the sign first: the verdict, its sentence, who holds out, and that it is a suggestion", async () => {
    await renderDiscussion();
    const dialog = screen.getByRole("dialog", { name: QUESTION });
    expect(dialog).toHaveTextContent(`${TICKET_KEY}· Discussion`);
    expect(dialog).toHaveTextContent("Asked by Ada Member · 4 agents · round 2 of 4");
    const sign = within(dialog).getByRole("region", { name: "Tralala's suggestion" });
    expect(sign).toHaveTextContent("Yes, with conditions");
    expect(sign).toHaveTextContent(REASON);
    expect(sign).toHaveTextContent("Cannot tell yet: Charlie · No answer yet from Delta");
    expect(sign).toHaveTextContent(
      "Tralala's summary of the answers after round 2. A suggestion, never a decision: you decide below.",
    );
    expect(screen.getByRole("button", { name: "Approve" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "Request rework" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "Veto" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "Let them talk it out" })).toBeEnabled();
  });

  it("says No answer yet before the first round, and keeps the decision until there is one", async () => {
    await renderDiscussion(
      discussion({ synthesis: null, positions: [], round_count: 0, runs: [], messages: [] }),
    );
    const sign = screen.getByRole("region", { name: "Tralala's suggestion" });
    expect(sign).toHaveTextContent("No answer yet");
    expect(screen.getByText(/· no round yet$/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Approve" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Approve" })).toHaveAttribute(
      "title",
      "There is no answer to decide on yet",
    );
    const status = screen.getByRole("region", { name: "Status" });
    expect(status).toHaveTextContent("No answer yet");
  });

  it("has one row per agent with its position, recommendation and confidence", async () => {
    await renderDiscussion();
    const rows = within(screen.getByRole("list", { name: "Answers" })).getAllByRole("listitem");
    expect(rows.map((item) => item.getAttribute("aria-label"))).toEqual([
      "Alpha",
      "Bravo",
      "Charlie",
      "Delta",
    ]);
    expect(row("Alpha")).toHaveTextContent("Product Owner");
    expect(row("Alpha")).toHaveTextContent("Yes, with conditions");
    expect(row("Alpha")).toHaveTextContent(
      "Let the agent write it, but show it to the person before the analysis goes on.",
    );
    expect(row("Alpha")).toHaveTextContent("High confidence");
    expect(row("Bravo")).toHaveTextContent("YesStore the assumption with the question.");
    expect(row("Bravo")).toHaveTextContent("Medium confidence");
    expect(row("Charlie")).toHaveTextContent("Answered in prose only");
    expect(row("Charlie")).not.toHaveTextContent("export owner");
    expect(row("Delta")).toHaveTextContent("No answer yet");
    expect(within(row("Delta")).queryByRole("button")).toBeNull();
  });

  it("opens For, Against, Conditions and Open questions under Details", async () => {
    const { user } = await renderDiscussion();
    const toggle = within(row("Alpha")).getByRole("button", { name: "Details from Alpha" });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    const panel = document.getElementById(toggle.getAttribute("aria-controls") ?? "");
    expect(panel).not.toBeVisible();
    await user.click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "true");
    expect(toggle).toHaveTextContent("Hide details");
    expect(panel).toBeVisible();
    const lists = within(row("Alpha"));
    expect(lists.getByRole("list", { name: "For" })).toHaveTextContent(
      "The approval covers the assumption in writing.",
    );
    expect(lists.getByRole("list", { name: "Against" })).toHaveTextContent(
      "It may read as the person's decision.",
    );
    expect(lists.getByRole("list", { name: "Conditions" })).toHaveTextContent(
      "The person sees the assumption first.",
    );
    expect(lists.getByRole("list", { name: "Open questions" })).toHaveTextContent(
      "Who rewrites a wrong assumption?",
    );
  });

  it("shows an answer stored under the old limits as it is", async () => {
    const long =
      "Write the assumption into the analysis, show it to the person who skipped the question, and keep the old text in the history so a later revision can repeat it word for word.";
    const five = ["One.", "Two.", "Three.", "Four.", "Five."];
    const base = discussion();
    const old = answer({ recommendation: long, pros: five });
    const { user } = await renderDiscussion({
      ...base,
      messages: base.messages.map((message) =>
        message.id === "m-bravo-1" ? { ...message, answer: old } : message,
      ),
      positions: (base.positions ?? []).map((entry) =>
        entry.participant === "Bravo" ? { ...entry, recommendation: long } : entry,
      ),
    });
    expect(row("Bravo")).toHaveTextContent(long);
    await user.click(within(row("Bravo")).getByRole("button", { name: "Details from Bravo" }));
    expect(
      within(within(row("Bravo")).getByRole("list", { name: "For" })).getAllByRole("listitem"),
    ).toHaveLength(5);
  });

  it("lists the conditions and open questions with who said them, and one line per round", async () => {
    await renderDiscussion();
    const conditions = expander("Conditions to accept if you go ahead");
    expect(conditions.querySelector("summary")).toHaveTextContent(
      "Conditions to accept if you go ahead1",
    );
    expect(within(conditions).getByRole("listitem", { hidden: true })).toHaveTextContent(
      "The person sees the assumption first. Alpha, Bravo",
    );
    const questions = expander("Open questions");
    expect(questions.querySelector("summary")).toHaveTextContent("Open questions1");
    expect(within(questions).getByRole("listitem", { hidden: true })).toHaveTextContent(
      "Who rewrites a wrong assumption? Alpha",
    );
    const rounds = expander("Rounds");
    expect(rounds.querySelector("summary")).toHaveTextContent("Rounds2 of 4");
    const lines = within(rounds)
      .getAllByRole("listitem", { hidden: true })
      .map((item) => item.textContent);
    expect(lines[0]).toBe("Round 1You asked the question · 3 answers · Unclear");
    expect(lines[1]).toMatch(
      /^Round 2Grace Hopper replied "What if the assumption turns out wrong later in the plan.*…" · 3 answers · Yes, with conditions$/,
    );
  });

  it("keeps what the agents wrote in Raw text: the reasoning as written, the answers as JSON, the runs", async () => {
    const { user } = await renderDiscussion();
    const forYou = screen.getByRole("tabpanel", { name: "For you" });
    expect(forYou).not.toHaveTextContent("reset_scope");
    expect(forYou).not.toHaveTextContent("the answer holds no JSON object");
    await user.click(screen.getByRole("tab", { name: "Raw text" }));
    const raw = screen.getByRole("tabpanel", { name: "Raw text" });
    expect(raw).toHaveTextContent(REASONING);
    expect(within(raw).getByText(/Alpha · Alpha's role · round 2 ·/)).toBeInTheDocument();
    expect(raw).toHaveTextContent("I would rather wait for the export owner.");
    expect(raw).toHaveTextContent('"position": "yes_with_conditions"');
    expect(raw).toHaveTextContent('"problem": "the answer holds no JSON object"');
    expect(raw).toHaveTextContent("stop: rounds_completed");
    expect(raw).toHaveTextContent("failures 0 · repeats 0 · 6200 tokens · 24.0 s");
  });

  it("puts the status in words and the facts in the rail", async () => {
    await renderDiscussion();
    const status = screen.getByRole("region", { name: "Status" });
    expect(status).toHaveTextContent("Waits for your decision· after round 2");
    const facts = screen.getByRole("region", { name: "Facts" });
    expect(within(facts).getByRole("link", { name: TICKET_KEY })).toHaveAttribute(
      "href",
      "/boards/board-1/loops/loop-1?card=card-1",
    );
    expect(facts).toHaveTextContent("Asked byAMAda Member");
    expect(facts).toHaveTextContent("Agents4");
    expect(facts).toHaveTextContent("Rounds2 of 4");
    expect(facts).toHaveTextContent("Tokens12 400");
  });

  it("opens the review dialog on Approve and sends the decision", async () => {
    const { user, api } = await renderDiscussion();
    await user.click(screen.getByRole("button", { name: "Approve" }));
    const review = screen.getByRole("dialog", { name: "Approve outcome" });
    await user.click(within(review).getByRole("button", { name: "Confirm" }));
    await waitFor(() =>
      expect(api.state.bodies).toEqual([
        { route: "review", body: { decision: "approve", reason: "" }, csrf: "csrf-discussion" },
      ]),
    );
    expect(await screen.findByText("Discussion approved")).toBeInTheDocument();
    await waitFor(() =>
      expect(screen.getByRole("region", { name: "Status" })).toHaveTextContent(
        "Approved by Ada Member",
      ),
    );
    expect(screen.queryByRole("button", { name: "Approve" })).toBeNull();
    expect(screen.queryByRole("textbox", { name: "Reply" })).toBeNull();
  });

  it("asks again with the reply, and leaves the round to the server on a roundtable thread", async () => {
    const { user, api } = await renderDiscussion();
    expect(screen.getByRole("textbox", { name: "Reply" })).toHaveAccessibleDescription(
      "The agents answer in a new round.",
    );
    await user.type(screen.getByRole("textbox", { name: "Reply" }), "And if it is wrong?");
    await user.click(screen.getByRole("button", { name: "Ask again" }));
    await waitFor(() =>
      expect(api.state.bodies).toEqual([
        { route: "messages", body: { content: "And if it is wrong?" }, csrf: "csrf-discussion" },
      ]),
    );
    expect(screen.getByRole("textbox", { name: "Reply" })).toHaveValue("");
  });

  it("starts the round itself on a manual thread, so nobody has to mention the agents", async () => {
    const { user, api } = await renderDiscussion(discussion({ mode: "manual" }));
    expect(screen.getByRole("textbox", { name: "Reply" })).toHaveAccessibleDescription(
      "The agents answer in a new round.",
    );
    await user.type(screen.getByRole("textbox", { name: "Reply" }), "And if it is wrong?");
    await user.click(screen.getByRole("button", { name: "Ask again" }));
    await waitFor(() =>
      expect(api.state.bodies).toEqual([
        { route: "messages", body: { content: "And if it is wrong?" }, csrf: "csrf-discussion" },
        { route: "start", body: { rounds: 1, background: true }, csrf: "csrf-discussion" },
      ]),
    );
  });
});
