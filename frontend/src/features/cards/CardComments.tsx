import { Bot, Send } from "lucide-react";
import type { Dispatch, RefObject, SetStateAction } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/input";
import type { AgentDirectoryEntry, Comment, MentionJob } from "@/lib/types";
import { formatDateTime } from "@/lib/utils";

const MENTION_TONES: Record<MentionJob["status"], "neutral" | "brand" | "success" | "danger"> = {
  queued: "neutral",
  running: "brand",
  completed: "success",
  failed: "danger",
};

/** The agent mention jobs, the comment thread and the composer with @-mention suggestions. */
export function CardComments({
  live,
  mentions,
  retrying,
  onRetryMention,
  comments,
  comment,
  onCommentChange,
  onCommentBlur,
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
  onCommentBlur: () => void;
  suggestions: AgentDirectoryEntry[];
  mentionIndex: number;
  onMentionIndexChange: Dispatch<SetStateAction<number>>;
  onChooseAgent: (agent: AgentDirectoryEntry) => void;
  commentField: RefObject<HTMLTextAreaElement | null>;
  onSubmitComment: (content: string) => void;
}) {
  return (
    <section>
      <div className="mb-2 flex items-center gap-2">
        <h3 className="text-sm font-semibold">Comments</h3>
        {live ? (
          <Badge tone="success" className="align-middle">
            live
          </Badge>
        ) : null}
      </div>
      {mentions.length > 0 ? (
        <ul aria-label="Agent mentions" className="mb-2 flex flex-col gap-1">
          {mentions.map((job) => (
            <li
              key={job.id}
              className="flex flex-wrap items-center gap-2 rounded-lg border border-[var(--border)] px-2.5 py-1.5 text-xs"
            >
              <Bot size={14} className="text-[var(--muted-foreground)]" />
              <span className="font-medium">{job.agent_name}</span>
              <Badge tone={MENTION_TONES[job.status]}>{job.status}</Badge>
              {job.error ? (
                <span
                  className="max-w-[220px] truncate text-[var(--destructive)]"
                  title={job.error}
                >
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
                  Retry
                </Button>
              ) : null}
            </li>
          ))}
        </ul>
      ) : null}
      <ul className="flex flex-col gap-2">
        {comments.map((entry) => (
          <li key={entry.id} className="rounded-lg border border-[var(--border)] p-2.5">
            <div className="flex items-center gap-2 text-[11px] text-[var(--muted-foreground)]">
              <span className="font-medium text-[var(--foreground)]">
                {entry.actor_name ?? "Unknown"}
              </span>
              <Badge tone={entry.actor_type === "agent" ? "brand" : "neutral"}>
                {entry.actor_type ?? "user"}
              </Badge>
              <span>{formatDateTime(entry.created_at)}</span>
            </div>
            <p className="mt-1 whitespace-pre-wrap text-sm">{entry.content}</p>
          </li>
        ))}
        {comments.length === 0 ? (
          <li className="text-xs text-[var(--muted-foreground)]">No comments yet.</li>
        ) : null}
      </ul>
      <form
        className="mt-2 flex items-end gap-1.5"
        onSubmit={(event) => {
          event.preventDefault();
          if (comment.trim()) onSubmitComment(comment.trim());
        }}
      >
        <div className="relative flex-1">
          <Textarea
            ref={commentField}
            id="new-comment"
            className="min-h-16"
            placeholder="Add a comment — type @ to mention an agent"
            aria-label="New comment"
            aria-autocomplete="list"
            aria-controls="mention-suggestions"
            aria-expanded={suggestions.length > 0}
            value={comment}
            onChange={(event) => onCommentChange(event.target.value, event.target.selectionStart)}
            onKeyDown={(event) => {
              if (suggestions.length === 0) return;
              if (event.key === "ArrowDown") {
                event.preventDefault();
                onMentionIndexChange((current) => (current + 1) % suggestions.length);
              } else if (event.key === "ArrowUp") {
                event.preventDefault();
                onMentionIndexChange(
                  (current) => (current - 1 + suggestions.length) % suggestions.length,
                );
              } else if (event.key === "Enter") {
                event.preventDefault();
                const highlighted = suggestions[mentionIndex];
                if (highlighted) onChooseAgent(highlighted);
              }
            }}
            onBlur={onCommentBlur}
          />
          {suggestions.length > 0 ? (
            <div
              id="mention-suggestions"
              role="listbox"
              aria-label="Mention an agent"
              className="absolute bottom-full left-0 z-10 mb-1 w-72 overflow-hidden rounded-lg border border-[var(--border)] bg-[var(--surface)] shadow-lg"
            >
              {suggestions.map((agent, index) => (
                <button
                  key={agent.id}
                  type="button"
                  role="option"
                  aria-selected={index === mentionIndex}
                  onMouseDown={(event) => {
                    event.preventDefault();
                    onChooseAgent(agent);
                  }}
                  className={`flex w-full items-center gap-2 px-2.5 py-1.5 text-left text-xs ${
                    index === mentionIndex
                      ? "bg-[var(--surface-raised)] text-[var(--foreground)]"
                      : "text-[var(--muted-foreground)]"
                  }`}
                >
                  <Bot size={14} />
                  <span className="font-medium">{agent.name}</span>
                  <span className="ml-auto text-[11px]">
                    {agent.role_template_name ?? "no role"}
                  </span>
                </button>
              ))}
            </div>
          ) : null}
        </div>
        <Button type="submit" size="icon" aria-label="Send comment" disabled={!comment.trim()}>
          <Send size={14} />
        </Button>
      </form>
    </section>
  );
}
