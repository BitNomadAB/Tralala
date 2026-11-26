import type { Confirmation } from "@/features/settings/ConfirmDialog";
import type { Discussion, DiscussionMessage } from "@/lib/types";
import { isTalking, replyHint } from "./discussionRules";

/**
 * The words of closing a discussion, opening it again and commenting after the close. The one who
 * opened a thread closes it; the opener or any signed-in person opens it again. A closed thread
 * stays readable and takes comments, which no agent answers.
 */

/** Closed by its opener: no decision and no round, but comments still come in. */
export function isThreadClosed(discussion: Discussion): boolean {
  return discussion.status === "closed";
}

/** Whether "Close discussion" is offered: to the opener, on a thread not closed or cancelled. */
export function mayClose(discussion: Discussion): boolean {
  return (
    discussion.opened_by_me && !isThreadClosed(discussion) && discussion.status !== "cancelled"
  );
}

/** Why "Close discussion" cannot be pressed now, or null when it can (the server's rule). */
export function closeBlocked(discussion: Discussion, busy: boolean): string | null {
  if (busy) return "Wait a moment: the discussion is changing";
  if (isTalking(discussion)) return "Stop the run before you close it";
  return null;
}

/** The question before "Close discussion" is carried out. */
export const CLOSE_QUESTION: Confirmation = {
  title: "Close this discussion?",
  consequence:
    "No decision or round can follow while it is closed. It stays readable, anyone can still comment, and it can be opened again.",
  confirmLabel: "Close discussion",
};

/** What a screen reader hears when the thread is closed or opened again, by anyone. */
export const CLOSED_NOTICE = "The discussion is closed. Comments can still be added.";
export const REOPENED_NOTICE = "The discussion is open again.";

/** The mark on a message written while the thread was closed. */
export const AFTER_CLOSING = "After closing";

/** What the reply says under it, and what its button says, in the thread as it is now. */
export function replyWords(discussion: Discussion): { hint: string; action: string } {
  if (isThreadClosed(discussion)) {
    return {
      hint: "Your comment is added after the discussion was closed. The agents do not answer.",
      action: "Add comment",
    };
  }
  if (discussion.participants.length === 0) {
    return { hint: "Your reply is added to the discussion.", action: "Send" };
  }
  return { hint: replyHint(discussion), action: "Ask again" };
}

/**
 * The messages "For you" lists as comments: everything not written by one of the thread's own
 * agents (people, and AIs that joined through their key), without the opening question, which is
 * the heading. The agents' answers are the rows above.
 */
export function commentsOf(discussion: Discussion): DiscussionMessage[] {
  const agents = new Set(discussion.participants.map((entry) => entry.participant_id));
  const [opening] = [...discussion.messages].sort((a, b) =>
    a.created_at.localeCompare(b.created_at),
  );
  return discussion.messages.filter(
    (message) =>
      message !== opening &&
      !(message.author_type === "agent" && agents.has(message.author_actor_id)),
  );
}

/** "SES-1-PH01-001 Rotate the signing key", the Ticket a message points at. */
export function ticketRefText(message: DiscussionMessage): string | null {
  const ref = message.ref_ticket;
  if (!ref) return null;
  return ref.ticket_key ? `${ref.ticket_key} ${ref.title}` : ref.title;
}
