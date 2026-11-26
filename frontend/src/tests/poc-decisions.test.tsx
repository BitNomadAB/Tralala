import { screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { POC_EMPTY } from "@/features/loops/pocDecisions";
import type { PocDecision } from "@/lib/types";
import { announcer } from "./announcer";
import { FEEDBACK_TICKET, pocDecision, pocHandlers } from "./msw/poc";
import { renderLoopPage } from "./renderLoopPage";

/** One taken on the Ticket in Phase 1, finished, that other work builds on; due now. */
const BUILT_ON = pocDecision(3, {
  title: "Sessions end after 30 minutes",
  card_id: "card-1",
  ticket_key: "SES-1-P1-001",
  ticket_title: "Rotate the signing key",
  phase_number: 1,
  phase_complete: true,
  builds_on: "The logout page and the audit report count on this limit.",
  built_on: true,
  due: true,
  details: "<b>not html</b> see backend/app/services/sessions.py",
});
const MISSING = pocDecision(2, {
  kind: "missing",
  title: "The mail service key",
  missing: "An API key for the mail service.",
  reason: "Reset mails cannot be sent without it.",
  chosen: "Mails are written to the log for now.",
  change_path: "Put the key in the settings and turn mails on.",
  alternative: "",
});
const PLAIN = pocDecision(1, { title: "Dates are shown in the local time zone" });
const ANSWERED = pocDecision(4, {
  title: "The button reads Sign out",
  status: "ok",
  answered_at: "2026-11-03T10:00:00Z",
  answered_by_name: "Ada Member",
});

async function renderDecisions(
  items: PocDecision[],
  stage: Parameters<typeof renderLoopPage>[1] = "in_progress",
  options: Parameters<typeof pocHandlers>[1] = {},
) {
  const poc = pocHandlers(items, options);
  const page = await renderLoopPage("?tab=decisions", stage, {}, poc.handlers);
  const panel = screen.getByRole("tabpanel", { name: /^Decisions/ });
  await within(panel).findByRole("heading", { name: "POC decisions", level: 2 });
  return { ...page, panel, poc };
}

function article(panel: HTMLElement, title: string): HTMLElement {
  return within(panel).getByRole("article", { name: title });
}

describe("the Decisions tab", () => {
  it("lists the records in review order under their headings, answered ones collapsed", async () => {
    const { panel } = await renderDecisions([PLAIN, MISSING, BUILT_ON, ANSWERED]);
    expect(await within(panel).findByText("3 wait for an answer.")).toBeInTheDocument();
    const headings = within(panel)
      .getAllByRole("heading", { level: 3 })
      .map((heading) => heading.textContent);
    expect(headings).toEqual([
      "Other work builds on these 1",
      "Missing from a person 1",
      "Other decisions 1",
      "Answered",
    ]);
    const titles = within(panel)
      .getAllByRole("article")
      .map((entry) => within(entry).getByRole("heading", { level: 4 }).textContent);
    expect(titles).toEqual([BUILT_ON.title, MISSING.title, PLAIN.title, ANSWERED.title]);
    // Answered is collapsed, with its count beside it.
    const answered = within(panel).getByText("Answered").closest("details");
    expect(answered).not.toHaveAttribute("open");
    expect(answered).toHaveTextContent("Answered1");
  });

  it("shows a decision's sign, its Ticket, its finished Phase and the raw text as text", async () => {
    const { panel } = await renderDecisions([BUILT_ON]);
    const item = article(
      await within(panel).findByRole("list", { name: "Other work builds on these" }),
      BUILT_ON.title,
    );
    expect(within(item).getByText("SES-1-POC-003")).toBeInTheDocument();
    expect(within(item).getByText("Due for review")).toBeInTheDocument();
    expect(
      within(item).getByRole("link", { name: "SES-1-P1-001 Rotate the signing key" }),
    ).toHaveAttribute("href", "/boards/board-1/loops/loop-1?tab=decisions&card=card-1");
    expect(within(item).getByText("Phase 1, finished")).toBeInTheDocument();
    const labels = within(item)
      .getAllByRole("term")
      .map((term) => term.textContent);
    expect(labels).toEqual(["Chosen", "Why", "Instead of", "To change it", "Builds on it"]);
    expect(within(item).getByText(BUILT_ON.builds_on)).toBeInTheDocument();
    // The agent's text sits behind Raw text, as written: no element is made of it.
    expect(within(item).getByText("Raw text")).toBeInTheDocument();
    expect(within(item).getByText(BUILT_ON.details)).toBeInTheDocument();
    expect(item.querySelector("b")).toBeNull();
  });

  it("words something missing from a person with its own labels", async () => {
    const { panel } = await renderDecisions([MISSING]);
    const item = article(
      await within(panel).findByRole("list", { name: "Missing from a person" }),
      MISSING.title,
    );
    expect(
      within(item)
        .getAllByRole("term")
        .map((term) => term.textContent),
    ).toEqual(["Missing", "Why it is needed", "How the work went around it", "Once it is there"]);
    expect(within(item).queryByText("Raw text")).toBeNull();
  });

  it("answers OK, announces it and keeps the record in place with the focus on its answer", async () => {
    const { panel, poc, user } = await renderDecisions([PLAIN, BUILT_ON]);
    const item = article(
      await within(panel).findByRole("list", { name: "Other decisions" }),
      PLAIN.title,
    );
    await user.click(within(item).getByRole("button", { name: "OK" }));
    const answer = await within(item).findByText("Answered OK");
    expect(poc.state.answers).toEqual([{ answer: "ok" }]);
    await waitFor(() => expect(answer.closest("[data-focus-target]")).toHaveFocus());
    await waitFor(() => expect(announcer()).toHaveTextContent("SES-1-POC-001 answered OK"));
    // Still under Other decisions, now with feedback still possible and no OK.
    const again = article(
      within(panel).getByRole("list", { name: "Other decisions" }),
      PLAIN.title,
    );
    expect(within(again).queryByRole("button", { name: "OK" })).toBeNull();
    expect(within(again).getByRole("button", { name: "Give feedback…" })).toBeInTheDocument();
    expect(await within(panel).findByText("1 waits for an answer.")).toBeInTheDocument();
  });

  it("sends feedback and shows it with a link to the Ticket it became", async () => {
    const { panel, poc, user } = await renderDecisions([ANSWERED]);
    await user.click(within(panel).getByText("Answered"));
    const item = article(panel, ANSWERED.title);
    await user.click(within(item).getByRole("button", { name: "Give feedback…" }));
    const field = within(item).getByLabelText("Your feedback");
    expect(field).toHaveFocus();
    const send = within(item).getByRole("button", { name: "Send feedback" });
    expect(send).toHaveAttribute("aria-disabled", "true");
    await user.type(field, "Call it Log out, as the rest of the app does.");
    await user.click(send);
    expect(
      await within(item).findByText("Call it Log out, as the rest of the app does."),
    ).toBeInTheDocument();
    expect(poc.state.answers).toEqual([
      { answer: "feedback", feedback: "Call it Log out, as the rest of the app does." },
    ]);
    expect(within(item).getByRole("link", { name: FEEDBACK_TICKET.key })).toHaveAttribute(
      "href",
      `/boards/board-1/loops/loop-1?tab=decisions&card=${FEEDBACK_TICKET.id}`,
    );
    await waitFor(() =>
      expect(announcer()).toHaveTextContent(
        `Feedback sent on SES-1-POC-004; it became Ticket ${FEEDBACK_TICKET.key}`,
      ),
    );
    // Feedback is final: nothing more to answer.
    expect(within(item).queryByRole("button", { name: "Give feedback…" })).toBeNull();
  });

  it("returns the focus to Give feedback… on Cancel", async () => {
    const { panel, user } = await renderDecisions([PLAIN]);
    const item = article(
      await within(panel).findByRole("list", { name: "Other decisions" }),
      PLAIN.title,
    );
    await user.click(within(item).getByRole("button", { name: "Give feedback…" }));
    await user.click(within(item).getByRole("button", { name: "Cancel" }));
    await waitFor(() =>
      expect(within(item).getByRole("button", { name: "Give feedback…" })).toHaveFocus(),
    );
  });

  it("shows the server's refusal and keeps the record open", async () => {
    const message = "A Loop in review takes no new Ticket.";
    const { panel, user } = await renderDecisions([PLAIN], "in_progress", {
      refuseAnswer: { status: 409, code: "loop_stage_closed", message },
    });
    const item = article(
      await within(panel).findByRole("list", { name: "Other decisions" }),
      PLAIN.title,
    );
    await user.click(within(item).getByRole("button", { name: "Give feedback…" }));
    await user.type(within(item).getByLabelText("Your feedback"), "Use 15 minutes.");
    await user.click(within(item).getByRole("button", { name: "Send feedback" }));
    expect(await within(item).findByRole("alert")).toHaveTextContent(message);
    expect(within(item).getByLabelText("Your feedback")).toHaveValue("Use 15 minutes.");
  });

  it("offers no answer in a read-only Loop", async () => {
    const { panel } = await renderDecisions([PLAIN, ANSWERED], "completed");
    const item = article(
      await within(panel).findByRole("list", { name: "Other decisions" }),
      PLAIN.title,
    );
    expect(within(item).queryByRole("button")).toBeNull();
    expect(within(panel).queryByRole("button", { name: "Give feedback…" })).toBeNull();
  });

  it("says what a POC decision is when there is none", async () => {
    const { panel } = await renderDecisions([]);
    expect(await within(panel).findByText(POC_EMPTY)).toBeInTheDocument();
  });
});
