import { Bot, CornerDownLeft, Send } from "lucide-react";
import { useId, type Dispatch, type RefObject, type SetStateAction } from "react";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/input";
import { useAnnounceWhen } from "@/components/ui/useAnnounce";
import type { AgentDirectoryEntry } from "@/lib/types";
import { cn } from "@/lib/utils";
import { mentionAnnouncement } from "./ticketText";

/**
 * The comment box with its @-mention suggestions, as an autocomplete: the field keeps the focus,
 * Up and Down move the highlight (`aria-activedescendant` names it), Enter chooses it, Escape closes
 * only the list (the field is `data-keeps-escape` while it is open, so the Ticket's dialog and the
 * unsent comment stay), and a press on a suggestion chooses it. The highlight is marked by an
 * Enter sign and bold text, not by colour alone, and a screen reader hears how many agents match
 * and which one is highlighted. Ctrl (or Cmd) + Enter sends, as the Send button does.
 *
 * The field stays a textbox: a textarea takes no combobox role and no `aria-expanded` (axe:
 * aria-allowed-role, aria-allowed-attr), so the announcement says what `aria-expanded` would.
 */
export function CommentComposer({
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
  comment: string;
  onCommentChange: (value: string, caret: number) => void;
  /** Closes the suggestions: on Escape, and when the field loses the focus. */
  onCloseSuggestions: () => void;
  suggestions: AgentDirectoryEntry[];
  mentionIndex: number;
  onMentionIndexChange: Dispatch<SetStateAction<number>>;
  onChooseAgent: (agent: AgentDirectoryEntry) => void;
  commentField: RefObject<HTMLTextAreaElement | null>;
  onSubmitComment: (content: string) => void;
}) {
  const listId = useId();
  const open = suggestions.length > 0;
  const optionId = (index: number) => `${listId}-option-${String(index)}`;
  useAnnounceWhen(
    open,
    mentionAnnouncement(
      suggestions.map((agent) => agent.name),
      mentionIndex,
    ),
  );

  return (
    <>
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
            placeholder="Write a comment. Type @ to bring in an agent."
            aria-label="New comment"
            aria-autocomplete="list"
            // Point at the suggestions only while they are shown, so each reference resolves.
            aria-controls={open ? listId : undefined}
            aria-activedescendant={open ? optionId(mentionIndex) : undefined}
            data-keeps-escape={open ? "" : undefined}
            value={comment}
            onChange={(event) => onCommentChange(event.target.value, event.target.selectionStart)}
            onKeyDown={(event) => {
              if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) {
                event.preventDefault();
                if (comment.trim()) onSubmitComment(comment.trim());
                return;
              }
              if (!open) return;
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
              } else if (event.key === "Escape") {
                event.preventDefault();
                onCloseSuggestions();
              }
            }}
            onBlur={onCloseSuggestions}
          />
          {open ? (
            <div
              id={listId}
              role="listbox"
              aria-label="Mention an agent"
              className="absolute bottom-full left-0 z-10 mb-1 w-72 overflow-hidden rounded-lg border border-[var(--border)] bg-[var(--surface)] shadow-lg"
            >
              {suggestions.map((agent, index) => {
                const highlighted = index === mentionIndex;
                return (
                  <div
                    key={agent.id}
                    id={optionId(index)}
                    role="option"
                    aria-selected={highlighted}
                    // Focus stays in the field; a press chooses without taking it away.
                    tabIndex={-1}
                    onMouseDown={(event) => {
                      event.preventDefault();
                      onChooseAgent(agent);
                    }}
                    className={cn(
                      "flex w-full cursor-pointer items-center gap-2 border-l-2 px-2.5 py-1.5 text-left text-xs",
                      highlighted
                        ? "border-[var(--primary)] bg-[var(--surface-raised)] font-semibold text-[var(--foreground)]"
                        : "border-transparent text-[var(--muted-foreground)]",
                    )}
                  >
                    <Bot size={14} aria-hidden="true" />
                    <span className="font-medium">{agent.name}</span>
                    <span className="ml-auto text-[11px]">
                      {agent.role_template_name ?? "no role"}
                    </span>
                    <CornerDownLeft
                      size={12}
                      aria-hidden="true"
                      className={highlighted ? "shrink-0" : "invisible shrink-0"}
                    />
                  </div>
                );
              })}
            </div>
          ) : null}
        </div>
        <Button type="submit" size="icon" aria-label="Send comment" disabled={!comment.trim()}>
          <Send size={14} aria-hidden="true" />
        </Button>
      </form>
      <p className="m-0 mt-1.5 text-xs text-[var(--foreground-faint)]">
        <kbd className="font-sans">Ctrl</kbd> + <kbd className="font-sans">Enter</kbd> sends
      </p>
    </>
  );
}
