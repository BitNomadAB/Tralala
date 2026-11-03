import { Send } from "lucide-react";
import { Link } from "react-router-dom";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/input";
import type { Discussion } from "@/lib/types";
import { formatDateTime } from "@/lib/utils";
import { RunPanel } from "./RunPanel";

export type ReviewDecision = "approve" | "veto" | "rework";

/** The selected thread: its context, the human decisions, the run panel, messages and reply. */
export function DiscussionThread({
  boardId,
  discussion,
  live,
  onReview,
  onChanged,
  reply,
  onReplyChange,
  sending,
  onSend,
}: {
  boardId: string;
  discussion: Discussion;
  live: boolean;
  onReview: (decision: ReviewDecision) => void;
  onChanged: () => void;
  reply: string;
  onReplyChange: (reply: string) => void;
  sending: boolean;
  onSend: () => void;
}) {
  const decided =
    ["approved", "vetoed", "cancelled"].includes(discussion.status) ||
    ["running", "paused"].includes(discussion.run_state);
  return (
    <>
      <div className="border-b border-[var(--border)] pb-2">
        <h2 className="text-sm font-semibold">
          {discussion.title}
          {live ? (
            <Badge tone="success" className="ml-2 align-middle">
              live
            </Badge>
          ) : null}
        </h2>
        <p className="text-[11px] text-[var(--muted-foreground)]">
          {discussion.mode} · created by {discussion.created_by_name} ·{" "}
          {discussion.participants.length} snapshot(s)
        </p>
        {discussion.loop_id ? (
          <p className="mt-1 text-[11px]">
            <Link
              to={`/boards/${boardId}/loops/${discussion.loop_id}?card=${discussion.card_id}`}
              className="text-[var(--brand)] underline"
            >
              Open {discussion.ticket_key ?? discussion.card_title ?? "ticket"}
            </Link>
            <span className="text-[var(--muted-foreground)]">
              {" "}
              in {discussion.loop_name ?? "its Loop"}
            </span>
          </p>
        ) : null}
        <p className="mt-1 text-[11px] text-[var(--muted-foreground)]">
          {discussion.participants
            .map(
              (participant) =>
                `${participant.display_name} (${participant.role_template_name ?? "no role"})`,
            )
            .join(" · ") || "No AI participants yet"}
        </p>
        <div className="mt-2 flex flex-wrap items-center gap-2">
          <Button
            size="sm"
            variant="outline"
            disabled={decided}
            onClick={() => onReview("approve")}
          >
            Approve
          </Button>
          <Button size="sm" variant="outline" disabled={decided} onClick={() => onReview("rework")}>
            Request rework
          </Button>
          <Button size="sm" variant="danger" disabled={decided} onClick={() => onReview("veto")}>
            Veto
          </Button>
          <span className="text-[11px] text-[var(--muted-foreground)]">
            Each agent answers with its snapshotted role and an explicit verdict.
          </span>
        </div>
        <RunPanel boardId={boardId} discussion={discussion} onChanged={onChanged} />
        {(discussion.votes ?? []).length > 0 ? (
          <ul className="mt-2 flex flex-wrap gap-1.5 text-[11px]">
            {(discussion.votes ?? []).map((vote) => (
              <li
                key={`${vote.participant_id}-${vote.created_at}`}
                className="rounded-md border border-[var(--border)] px-1.5 py-0.5"
              >
                {vote.display_name ?? "agent"}: <span className="font-medium">{vote.position}</span>
              </li>
            ))}
          </ul>
        ) : null}
      </div>
      <ul className="scrollbar-thin flex-1 overflow-y-auto py-2">
        {discussion.messages.map((message) => (
          <li key={message.id} className="mb-3">
            <p className="text-[11px] text-[var(--muted-foreground)]">
              <span className="font-medium text-[var(--foreground)]">{message.author_name}</span> ·{" "}
              {message.author_type} · {formatDateTime(message.created_at)}
            </p>
            <p className="mt-0.5 whitespace-pre-wrap text-sm">{message.content}</p>
          </li>
        ))}
      </ul>
      <form
        className="flex items-end gap-2 border-t border-[var(--border)] pt-2"
        onSubmit={(event) => {
          event.preventDefault();
          if (reply.trim()) onSend();
        }}
      >
        <Textarea
          aria-label="Reply"
          className="min-h-10 flex-1"
          value={reply}
          onChange={(event) => onReplyChange(event.target.value)}
          placeholder={
            ["roundtable", "autonomous"].includes(discussion.mode)
              ? "Reply — the participants answer automatically"
              : "Reply — mention @agents to make the participants answer"
          }
        />
        <Button type="submit" disabled={!reply.trim() || sending}>
          <Send size={14} /> Send
        </Button>
      </form>
      {discussion.mode === "manual" ? (
        <p className="mt-1 text-[11px] text-[var(--muted-foreground)]">
          Mention <span className="font-medium text-[var(--foreground)]">@agents</span> (or a
          participant&apos;s name) to make the thread answer, or start a run above.
        </p>
      ) : null}
    </>
  );
}
