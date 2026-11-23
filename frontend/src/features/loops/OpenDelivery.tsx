import { Button } from "@/components/ui/button";
import { useAnnounce } from "@/components/ui/useAnnounce";
import type { OpenDeliveryTicket } from "@/lib/types";

/** "1 delivery Ticket" or "3 delivery Tickets". */
function counted(count: number): string {
  return count === 1 ? "1 delivery Ticket" : `${String(count)} delivery Tickets`;
}

/**
 * The completion dialog's note on delivery Tickets that are not done. They hold the acceptance up
 * until the person either completes them or accepts without them; once the Loop is completed, each
 * one left is marked Not done and never counts as done. The one button stays where it is while its
 * words change, so it keeps the focus (WCAG 2.4.3), and the sentence `reasonId` names says what
 * holds the Accept button up.
 */
export function OpenDelivery({
  tickets,
  accepted,
  onAcceptedChange,
  reasonId,
  disabled,
}: {
  tickets: readonly OpenDeliveryTicket[];
  /** Whether the person chose to accept without them. */
  accepted: boolean;
  onAcceptedChange: (accepted: boolean) => void;
  reasonId: string;
  disabled: boolean;
}) {
  const announce = useAnnounce();
  if (tickets.length === 0) return null;
  const one = tickets.length === 1;
  const them = one ? "it" : "them";
  return (
    <div className="grid gap-2 rounded-lg border border-[var(--warning)] p-3 text-sm">
      <p id={reasonId} className="m-0 font-medium">
        {accepted
          ? `Accepting without ${counted(tickets.length)}.`
          : `${counted(tickets.length)} ${one ? "is" : "are"} not done.`}
      </p>
      <ul className="m-0 grid list-none gap-0.5 p-0">
        {tickets.map((ticket) => (
          <li key={ticket.id}>
            {ticket.ticket_key ? (
              <span className="font-mono text-xs font-semibold">{ticket.ticket_key}</span>
            ) : null}{" "}
            {ticket.title}
            {ticket.archived_at ? (
              <span className="text-[var(--muted-foreground)]"> (archived)</span>
            ) : null}
          </li>
        ))}
      </ul>
      <p className="m-0 text-xs text-[var(--muted-foreground)]">
        {accepted
          ? `${one ? "It stays as it is" : "They stay as they are"}. `
          : `Complete ${them} first, or accept without ${them}. `}
        Once the Loop is completed, a Ticket that is still not done is marked Not done and never
        counts as done.
      </p>
      <Button
        variant="outline"
        size="sm"
        className="justify-self-start"
        disabled={disabled}
        onClick={() => {
          announce(
            accepted
              ? `${counted(tickets.length)} ${one ? "holds" : "hold"} the acceptance up again`
              : `Accepting without ${counted(tickets.length)}`,
          );
          onAcceptedChange(!accepted);
        }}
      >
        {accepted ? "Undo" : `Accept without ${them}`}
      </Button>
    </div>
  );
}
