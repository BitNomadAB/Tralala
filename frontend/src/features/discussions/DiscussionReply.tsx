import { useId } from "react";
import { Avatar } from "@/components/ui/avatar";
import { FieldMessage, Textarea } from "@/components/ui/input";
import { useFieldErrors } from "@/components/ui/useFieldErrors";
import { EMPTY_REPLY } from "./discussionRules";
import { HeldButton } from "./HeldButton";

/**
 * Your reply: one message, which the agents answer in a new round ("Ask again"); the hint under
 * it says so, or while the agents answer, why the reply waits (`disabled`). Nothing here leaves
 * the tab order while it waits: the reply is read-only and "Ask again" is held, both described by
 * the hint, so focus stays where it was when a round starts or the reply is on its way. "Ask
 * again" with nothing written says so under the reply and puts focus there (WCAG 3.3.1).
 */
export function DiscussionReply({
  author,
  value,
  onChange,
  hint,
  disabled,
  sending,
  onSend,
}: {
  author: string;
  value: string;
  onChange: (value: string) => void;
  hint: string;
  disabled: boolean;
  sending: boolean;
  onSend: () => void;
}) {
  const replyId = useId();
  const hintId = useId();
  const errorId = useId();
  const errors = useFieldErrors();
  const error = errors.errorOf(replyId);
  return (
    <form
      aria-label="Your reply"
      noValidate
      className="grid grid-cols-[auto_minmax(0,1fr)] gap-3"
      onSubmit={(event) => {
        event.preventDefault();
        if (disabled || sending) return;
        if (value.trim() === "") {
          errors.report([{ id: replyId, message: EMPTY_REPLY }]);
          return;
        }
        onSend();
      }}
    >
      <Avatar name={author} />
      <div className="grid gap-2">
        <Textarea
          id={replyId}
          aria-label="Reply"
          aria-describedby={error ? `${errorId} ${hintId}` : hintId}
          aria-invalid={error ? true : undefined}
          aria-disabled={disabled ? true : undefined}
          readOnly={disabled}
          className="min-h-20 aria-disabled:opacity-60"
          value={value}
          onChange={(event) => {
            onChange(event.target.value);
            if (error && event.target.value.trim() !== "") errors.set(replyId, null);
          }}
          placeholder="Ask a follow-up question, or add what they missed."
        />
        {error ? <FieldMessage id={errorId}>{error}</FieldMessage> : null}
        <div className="flex flex-wrap items-center justify-between gap-2">
          <small id={hintId} className="text-[12.5px] text-[var(--foreground-faint)]">
            {hint}
          </small>
          <HeldButton
            type="submit"
            variant="secondary"
            size="sm"
            held={disabled || sending}
            reasonId={hintId}
          >
            Ask again
          </HeldButton>
        </div>
      </div>
    </form>
  );
}
