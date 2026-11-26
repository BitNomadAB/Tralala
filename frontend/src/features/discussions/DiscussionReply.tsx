import { useEffect, useId, useState } from "react";
import { Avatar } from "@/components/ui/avatar";
import { HeldButton } from "@/components/ui/held-button";
import { Field, FieldMessage, Input, Textarea } from "@/components/ui/input";
import { useFieldErrors } from "@/components/ui/useFieldErrors";
import { fieldErrors } from "@/lib/describeError";
import { EMPTY_REPLY } from "./discussionRules";

/** What the server said about the reply's Ticket, or null when it named no Ticket. */
function ticketRefusal(error: Error): string | null {
  return fieldErrors(error).find((entry) => entry.field === "ticket")?.message ?? null;
}

/**
 * Your reply: one message, which the agents answer in a new round ("Ask again"); the hint under
 * it says so, or while the agents answer, why the reply waits (`disabled`), or in a closed thread
 * that it is a comment after the close that no agent answers ("Add comment"). Nothing here leaves
 * the tab order while it waits: the reply is read-only and its button is held, both described by
 * the hint, so focus stays where it was when a round starts or the reply is on its way. The button
 * with nothing written says so under the reply and puts focus there (WCAG 3.3.1). "About Ticket"
 * takes the key of a Ticket on the board the reply points at; one the server does not know is
 * said under the field, which takes focus (`refusal`, the last reply's error).
 */
export function DiscussionReply({
  author,
  value,
  onChange,
  ticket,
  onTicketChange,
  refusal,
  hint,
  action,
  disabled,
  sending,
  onSend,
}: {
  author: string;
  value: string;
  onChange: (value: string) => void;
  ticket: string;
  onTicketChange: (value: string) => void;
  refusal: Error | null;
  hint: string;
  /** The button's word: "Ask again", "Send" without agents, "Add comment" once closed. */
  action: string;
  disabled: boolean;
  sending: boolean;
  onSend: () => void;
}) {
  const replyId = useId();
  const ticketId = useId();
  const hintId = useId();
  const errorId = useId();
  const errors = useFieldErrors();
  const error = errors.errorOf(replyId);
  // The refusal's word on the Ticket, until the person types in the field again.
  const [dismissed, setDismissed] = useState<Error | null>(null);
  const refused = refusal === null ? null : ticketRefusal(refusal);
  const ticketError = refusal === dismissed ? null : refused;
  useEffect(() => {
    if (refused !== null) document.getElementById(ticketId)?.focus();
  }, [refusal, refused, ticketId]);

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
        <div className="max-w-[24rem]">
          <Field
            label="About Ticket"
            htmlFor={ticketId}
            hint="Optional: the key of a Ticket on this board."
            error={ticketError}
          >
            <Input
              id={ticketId}
              value={ticket}
              autoComplete="off"
              spellCheck={false}
              onChange={(event) => {
                onTicketChange(event.target.value);
                setDismissed(refusal);
              }}
            />
          </Field>
        </div>
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
            {action}
          </HeldButton>
        </div>
      </div>
    </form>
  );
}
