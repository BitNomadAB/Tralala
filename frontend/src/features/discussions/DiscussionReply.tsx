import { useId } from "react";
import { Avatar } from "@/components/ui/avatar";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/input";

/**
 * Your reply: one message, which the agents answer in a new round ("Ask again"); the hint under
 * it says so, or while the agents answer, why the reply waits (`disabled`).
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
  const hintId = useId();
  return (
    <form
      aria-label="Your reply"
      className="grid grid-cols-[auto_minmax(0,1fr)] gap-3"
      onSubmit={(event) => {
        event.preventDefault();
        onSend();
      }}
    >
      <Avatar name={author} />
      <div className="grid gap-2">
        <Textarea
          aria-label="Reply"
          aria-describedby={hintId}
          className="min-h-20"
          value={value}
          disabled={disabled}
          onChange={(event) => onChange(event.target.value)}
          placeholder="Ask a follow-up question, or add what they missed."
        />
        <div className="flex flex-wrap items-center justify-between gap-2">
          <small id={hintId} className="text-[12.5px] text-[var(--foreground-faint)]">
            {hint}
          </small>
          <Button
            type="submit"
            variant="secondary"
            size="sm"
            disabled={disabled || !value.trim() || sending}
          >
            Ask again
          </Button>
        </div>
      </div>
    </form>
  );
}
