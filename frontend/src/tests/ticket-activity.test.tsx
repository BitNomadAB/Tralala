import { screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { completionComments, historyLine } from "@/features/cards/ticketText";
import { askedDecisions } from "@/features/history/askedThrough";
import type { ActivityEntry, Comment } from "@/lib/types";
import { CARD_ID, CARD_PATH, ticketCard } from "./msw/cards";
import { NOW } from "./msw/loops";
import { MEMBER } from "./msw/session";
import { renderTicket, writes } from "./renderTicket";

function entry(id: string, action: string, extra: Partial<ActivityEntry> = {}): ActivityEntry {
  return {
    id,
    actor_id: MEMBER.id,
    actor_type: "user",
    action,
    entity_type: "card",
    entity_id: CARD_ID,
    request_id: null,
    timestamp: NOW,
    changes: {},
    ...extra,
  };
}

function comment(id: string, content: string): Comment {
  return {
    id,
    card_id: CARD_ID,
    actor_id: "agent-1",
    actor_name: "Coding session",
    actor_type: "agent",
    content,
    created_at: NOW,
    updated_at: NOW,
    after_loop_completed: false,
  };
}

const COMPLETION = "The guard ends idle sessions.\n\n**Evidence**\n\n- The unit suite passed";

describe("Activity", () => {
  it("starts on Comments with the composer, its placeholder and its hint", async () => {
    await renderTicket();
    const tabs = screen.getByRole("tablist", { name: "Activity" });
    await waitFor(() =>
      expect(
        within(tabs)
          .getAllByRole("tab")
          .map((tab) => tab.textContent),
      ).toEqual(["Comments", "Discussions 0", "History", "Work"]),
    );
    expect(within(tabs).getByRole("tab", { name: "Comments" })).toHaveAttribute(
      "aria-selected",
      "true",
    );
    expect(screen.getByLabelText("New comment")).toHaveAttribute(
      "placeholder",
      "Write a comment. Type @ to bring in an agent.",
    );
    expect(screen.getByText("No comments yet.")).toBeVisible();
    expect(screen.getByRole("tabpanel", { name: "Comments" })).toHaveTextContent(
      "Ctrl + Enter sends",
    );
  });

  it("sends a comment with Ctrl + Enter", async () => {
    const { view, user } = await renderTicket();
    await user.type(screen.getByLabelText("New comment"), "Started on it.");
    await user.keyboard("{Control>}{Enter}{/Control}");
    await waitFor(() =>
      expect(writes(view)).toEqual([
        { route: `POST ${CARD_PATH}/comments`, body: { content: "Started on it." } },
      ]),
    );
  });

  it("shows the history as event rows that say who did what", async () => {
    const { user } = await renderTicket(ticketCard(), undefined, {
      activity: [
        entry("a-2", "card.updated", { changes: { title: { before: "a", after: "b" } } }),
        entry("a-1", "card.created", { actor_id: "agent-9", actor_type: "agent" }),
      ],
    });
    await user.click(screen.getByRole("tab", { name: "History" }));
    const rows = within(await screen.findByRole("list", { name: "History" })).getAllByRole(
      "listitem",
    );
    expect(rows[0]).toHaveTextContent(`${MEMBER.name} changed the title`);
    expect(rows[1]).toHaveTextContent("An agent created this Ticket");
  });

  it("says when no work is recorded, and shows a completion with its evidence", async () => {
    const { user } = await renderTicket();
    await user.click(screen.getByRole("tab", { name: "Work" }));
    expect(screen.getByRole("tabpanel", { name: "Work" })).toHaveTextContent(
      "No work recorded yet. A coding session's summaries and the completion with its evidence appear here.",
    );
  });

  it("lists the summary a coding session wrote and its completion", async () => {
    const { user } = await renderTicket(
      ticketCard({
        summary: "Idle sessions end after 30 minutes.",
        summary_source: "agent",
        completed_at: NOW,
        state: null,
        comments: [comment("c-1", "Halfway there."), comment("c-2", COMPLETION)],
      }),
    );
    await user.click(screen.getByRole("tab", { name: "Work" }));
    const work = within(screen.getByRole("tabpanel", { name: "Work" })).getByRole("list", {
      name: "Work",
    });
    expect(work).toHaveTextContent("A coding session wrote the summaryIdle sessions end");
    expect(work).toHaveTextContent("Completed");
    expect(work).toHaveTextContent("The unit suite passed");
    expect(work).not.toHaveTextContent("Halfway there.");
  });

  it("shows the Comments tab again when the head's Comment is pressed", async () => {
    const { user } = await renderTicket();
    await user.click(screen.getByRole("tab", { name: "History" }));
    await user.click(screen.getByRole("button", { name: "Comment" }));
    expect(screen.getByRole("tab", { name: "Comments" })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByLabelText("New comment")).toHaveFocus();
  });
});

describe("the history's words", () => {
  it("names the fields a change touched, a completion and an unknown action", () => {
    const changed = entry("1", "card.updated", {
      changes: { priority: {}, due_at: {}, labels: {} },
    });
    expect(historyLine(changed, "Ada")).toBe(
      "Ada changed the priority, the due date and the labels",
    );
    const done = entry("2", "card.updated", { changes: { completed: { after: true } } });
    expect(historyLine(done, null)).toBe("A person completed this Ticket");
    const reopened = entry("3", "card.updated", { changes: { completed: { after: false } } });
    expect(historyLine(reopened, "Ada")).toBe("Ada reopened this Ticket");
    const service = entry("4", "card.something_new", { actor_type: "service" });
    expect(historyLine(service, null)).toBe("Tralala card.something_new");
    expect(completionComments([comment("x", "Plain."), comment("y", COMPLETION)])).toHaveLength(1);
  });

  it("says a person was asked from a coding session, and through which keys a decision was", () => {
    const asked = entry("5", "decision.requested", { actor_id: "agent-1", actor_type: "agent" });
    expect(historyLine(asked, "Laptop key")).toBe(
      "Laptop key asked a person to decide, from a coding session",
    );
    const laptop = { credential_id: "cred-1", key_name: "Laptop", via: "link" };
    const cleared = entry("6", "card.wait_cleared", { changes: { asked_through: [laptop] } });
    expect(historyLine(cleared, "Ada")).toBe(
      "Ada cleared the wait, asked from a coding session through the key Laptop",
    );
    const both = entry("7", "card.human_confirmed", {
      changes: {
        asked_through: [laptop, { credential_id: "cred-2", key_name: "Desktop", via: "link" }],
      },
    });
    expect(historyLine(both, "Ada")).toBe(
      "Ada confirmed the human action, asked from a coding session through the keys Laptop and Desktop",
    );
    // A decision nobody asked for reads as before.
    expect(historyLine(entry("8", "card.wait_cleared"), "Ada")).toBe("Ada cleared the wait");
  });

  it("says a decision taken in the editor came through which one key", () => {
    const laptop = { credential_id: "cred-1", key_name: "Laptop", via: "form" };
    const desktop = { credential_id: "cred-2", key_name: "Desktop", via: "link" };
    const cleared = entry("9", "card.wait_cleared", {
      changes: { taken_through: laptop, asked_through: [desktop, laptop] },
    });
    expect(historyLine(cleared, "Ada")).toBe(
      "Ada cleared the wait, decided in a coding session through the key Laptop, asked from a coding session through the keys Desktop and Laptop",
    );
    const envelope = {
      activity: [
        {
          action: "loop.analysis_reviewed",
          changes: { decision: "approved", taken_through: laptop, asked_through: [laptop] },
        },
      ],
      approvals: [
        {
          scope: "implementation",
          decision: "approved",
          revisions: { taken_through: laptop, asked_through: [laptop] },
        },
      ],
    };
    expect(askedDecisions(envelope)).toEqual([
      "Approved the analysis, decided in a coding session through the key Laptop, asked from a coding session through the key Laptop",
      "Accepted the implementation, decided in a coding session through the key Laptop, asked from a coding session through the key Laptop",
    ]);
  });
});
