import { ToneMark } from "@/components/ui/chip";
import type { Card } from "@/lib/types";
import { confirmationKeys, doneAwaiting } from "./ticketRules";

type Awaiting = Pick<Card, "completed_at" | "awaiting_confirmation" | "confirmations">;

/**
 * "Awaiting confirmation" on a Kanban card that is done while a person's task before it is not
 * confirmed yet: the word with a dot that only repeats it, and on hover, for a screen reader too,
 * whose confirmation it waits for. Nothing on an open Ticket, or once the person confirmed.
 */
export function AwaitingConfirmationChip({ card }: { card: Awaiting }) {
  if (!doneAwaiting(card)) return null;
  return (
    <ToneMark
      tone="warning"
      word="Awaiting confirmation"
      compact
      title={`Done; a person has still to confirm ${confirmationKeys(card)}`}
    />
  );
}

/** The same in the Ticket's rail, where the state stands: "Done · awaiting confirmation of KEY". */
export function DoneAwaitingLine({ card }: { card: Awaiting }) {
  if (!doneAwaiting(card)) return null;
  return (
    <ToneMark
      tone="warning"
      word="Done"
      reason={`awaiting confirmation of ${confirmationKeys(card)}`}
    />
  );
}
