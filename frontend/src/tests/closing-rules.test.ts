import { describe, expect, it } from "vitest";
import {
  CLOSED_NOTICE,
  closeBlocked,
  commentsOf,
  isThreadClosed,
  mayClose,
  REOPENED_NOTICE,
  replyWords,
  ticketRefText,
} from "@/features/discussions/closingRules";
import { messageHeading } from "@/features/discussions/discussionData";
import { discussionNotices, liveState } from "@/features/discussions/discussionNotices";
import {
  decisionBlocked,
  replyNeedsRound,
  stateOf,
  talkBlocked,
} from "@/features/discussions/discussionRules";
import {
  discussionWaitsFor,
  inboxAside,
  ticketDiscussionAside,
  ticketDiscussionMark,
} from "@/features/discussions/inboxRules";
import { formatDate } from "@/lib/utils";
import { inboxRow } from "./msw/discussionInbox";
import { discussion } from "./msw/discussions";

const CLOSED = discussion({ status: "closed", closed_at: "2026-11-08T12:00:00Z" });

describe("closing a discussion", () => {
  it("is offered to the opener of a thread that is neither closed, cancelled nor decided", () => {
    expect(mayClose(discussion())).toBe(true);
    expect(mayClose(discussion({ opened_by_me: false }))).toBe(false);
    expect(mayClose(CLOSED)).toBe(false);
    expect(mayClose(discussion({ status: "cancelled" }))).toBe(false);
    expect(mayClose(discussion({ status: "approved" }))).toBe(false);
    expect(mayClose(discussion({ status: "vetoed" }))).toBe(false);
    expect(mayClose(discussion({ status: "rework_requested" }))).toBe(true);
  });

  it("waits for a run to stop and for a change on its way", () => {
    expect(closeBlocked(discussion(), false)).toBeNull();
    expect(closeBlocked(discussion({ run_state: "paused" }), false)).toBe(
      "Stop the run before you close it",
    );
    expect(closeBlocked(discussion(), true)).toBe("Wait a moment: the discussion is changing");
  });

  it("reads Closed, takes no decision and no round, and lists as waiting for nobody", () => {
    expect(isThreadClosed(CLOSED)).toBe(true);
    expect(stateOf(CLOSED).word).toBe("Closed");
    expect(decisionBlocked(CLOSED)).toBe("The discussion is closed");
    expect(talkBlocked(CLOSED)).toBe("The discussion is closed");
    expect(replyNeedsRound({ ...CLOSED, auto_run: null })).toBe(false);
    expect(discussionWaitsFor(CLOSED)).toBe("nobody");
    expect(ticketDiscussionMark(CLOSED).word).toBe("Closed");
    expect(ticketDiscussionAside({ ...CLOSED, decided_by_name: "Grace Hopper" })).toBe("Closed");
    const row = inboxRow("d", { status: "closed", waits_for: "nobody" });
    expect(inboxAside(row)).toBe(`Closed · ${formatDate(row.last_activity_at)}`);
  });

  it("is said when the thread closes or opens again, and not on the first look", () => {
    const open = liveState(discussion(), null);
    const shut = liveState(CLOSED, null);
    expect(discussionNotices(null, shut)).toEqual([]);
    expect(discussionNotices(open, shut)).toEqual([CLOSED_NOTICE]);
    expect(discussionNotices(shut, open)).toEqual([REOPENED_NOTICE]);
    expect(discussionNotices(shut, shut)).toEqual([]);
  });
});

describe("the reply and the comments", () => {
  it("says what the reply does: a comment once closed, a message without agents, else a round", () => {
    expect(replyWords(CLOSED)).toEqual({
      hint: "Your comment is added after the discussion was closed. The agents do not answer.",
      action: "Add comment",
    });
    expect(replyWords(discussion({ participants: [] }))).toEqual({
      hint: "Your reply is added to the discussion.",
      action: "Send",
    });
    expect(replyWords(discussion())).toEqual({
      hint: "The agents answer in a new round.",
      action: "Ask again",
    });
    expect(replyNeedsRound({ ...discussion({ participants: [] }), auto_run: null })).toBe(false);
  });

  it("lists as comments what is not the question and not the thread's own agents' answers", () => {
    const thread = discussion();
    expect(commentsOf(thread).map((message) => message.id)).toEqual(["m-reply"]);
    const answer = thread.messages[1];
    if (!answer) throw new Error("The fixture has an answer");
    // An AI that joined by its key writes as an agent, but is not one of the thread's own.
    const outside = { ...answer, id: "m-outside", author_actor_id: "agent-Outside" };
    const joined = { ...thread, messages: [...thread.messages, outside] };
    expect(commentsOf(joined).map((message) => message.id)).toEqual(["m-reply", "m-outside"]);
  });

  it("marks a late comment and the Ticket a message points at in the transcript's heading", () => {
    const base = discussion().messages[4];
    if (!base) throw new Error("The fixture has a reply");
    const ref = { card_id: "c", ticket_key: "SES-1-PH01-002", title: "Expire", loop_id: "l" };
    const late = { ...base, after_closed: true, ref_ticket: ref };
    expect(ticketRefText(late)).toBe("SES-1-PH01-002 Expire");
    expect(ticketRefText({ ...late, ref_ticket: { ...ref, ticket_key: null } })).toBe("Expire");
    expect(ticketRefText(base)).toBeNull();
    expect(messageHeading(late)).toMatch(/ · After closing · about SES-1-PH01-002 Expire$/);
    expect(messageHeading(base)).not.toContain("After closing");
  });
});
