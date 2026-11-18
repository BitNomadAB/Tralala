import { Bot } from "lucide-react";
import type { Dispatch, RefObject, SetStateAction } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import type { AgentDirectoryEntry, Comment, MentionJob } from "@/lib/types";
import { formatDateTime } from "@/lib/utils";
import { CommentComposer } from "./CommentComposer";

const MENTION_TONES: Record<MentionJob["status"], "neutral" | "brand" | "success" | "danger"> = {
  queued: "neutral",
  running: "brand",
  completed: "success",
  failed: "danger",
};

/**
 * The agent mention jobs, the comment thread and the composer with @-mention suggestions
 * (`CommentComposer`). The composer stays open on a Ticket of a
 * completed, archived or cancelled Loop: such a Loop takes comments on its Tickets (only an
 * archived board refuses one), and a comment written after the Loop was completed says so.
 */
export function CardComments({
  live,
  mentions,
  retrying,
  onRetryMention,
  comments,
  comment,
  onCommentChange,
  onCloseSuggestions,
  suggestions,
  mentionIndex,
  onMentionIndexChange,
  onChooseAgent,
  commentField,
  onSubmitComment,
}: {
  live: boolean;
  mentions: MentionJob[];
  retrying: boolean;
  onRetryMention: (jobId: string) => void;
  comments: Comment[];
  comment: string;
  onCommentChange: (value: string, caret: number) => void;
  onCloseSuggestions: () => void;
  suggestions: AgentDirectoryEntry[];
  mentionIndex: number;
  onMentionIndexChange: Dispatch<SetStateAction<number>>;
  onChooseAgent: (agent: AgentDirectoryEntry) => void;
  commentField: RefObject<HTMLTextAreaElement | null>;
  onSubmitComment: (content: string) => void;
}) {
  return (
    <div>
      {live ? (
        <div className="mb-2">
          <Badge tone="success" className="align-middle">
            live
          </Badge>
        </div>
      ) : null}
      {mentions.length > 0 ? (
        <ul aria-label="Agent mentions" className="mb-2 flex flex-col gap-1">
          {mentions.map((job) => (
            <li
              key={job.id}
              className="flex flex-wrap items-center gap-2 rounded-lg border border-[var(--border)] px-2.5 py-1.5 text-xs"
            >
              <Bot size={14} aria-hidden="true" className="text-[var(--muted-foreground)]" />
              <span className="font-medium">{job.agent_name}</span>
              <Badge tone={MENTION_TONES[job.status]}>{job.status}</Badge>
              {job.error ? (
                <span className="min-w-[12rem] flex-1 break-words text-[var(--destructive)]">
                  {job.error}
                </span>
              ) : null}
              {job.can_retry ? (
                <Button
                  size="sm"
                  variant="outline"
                  className="ml-auto"
                  disabled={retrying}
                  onClick={() => onRetryMention(job.id)}
                >
                  Retry<span className="sr-only"> the mention of {job.agent_name}</span>
                </Button>
              ) : null}
            </li>
          ))}
        </ul>
      ) : null}
      <ul className="flex flex-col gap-2">
        {comments.map((entry) => (
          <li key={entry.id} className="rounded-lg border border-[var(--border)] p-2.5">
            <div className="flex items-center gap-2 text-xs text-[var(--muted-foreground)]">
              <span className="font-medium text-[var(--foreground)]">
                {entry.actor_name ?? "Unknown"}
              </span>
              <Badge tone={entry.actor_type === "agent" ? "brand" : "neutral"}>
                {entry.actor_type ?? "user"}
              </Badge>
              <span>{formatDateTime(entry.created_at)}</span>
              {entry.after_loop_completed ? (
                <Badge title="The Loop's history holds the comments as they were at completion">
                  written after the Loop was completed
                </Badge>
              ) : null}
            </div>
            <p className="mt-1 whitespace-pre-wrap text-sm">{entry.content}</p>
          </li>
        ))}
        {comments.length === 0 ? (
          <li className="text-xs text-[var(--muted-foreground)]">No comments yet.</li>
        ) : null}
      </ul>
      <CommentComposer
        comment={comment}
        onCommentChange={onCommentChange}
        onCloseSuggestions={onCloseSuggestions}
        suggestions={suggestions}
        mentionIndex={mentionIndex}
        onMentionIndexChange={onMentionIndexChange}
        onChooseAgent={onChooseAgent}
        commentField={commentField}
        onSubmitComment={onSubmitComment}
      />
    </div>
  );
}
