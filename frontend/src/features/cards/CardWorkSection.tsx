import { useId, useState } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Field, Select, Textarea } from "@/components/ui/input";
import type { Card, Wait } from "@/lib/types";
import { formatDateTime } from "@/lib/utils";
import {
  STATE_HINTS,
  STATE_LABELS,
  STATE_TONES,
  WAIT_HINTS,
  WAIT_LABELS,
  WAITING_REASON_MAX,
  WAITS,
  WORKPLACE_LABELS,
  WORKPLACES,
} from "./ticketWork";
import { useCardWork } from "./useCardWork";

/**
 * Where a Ticket's work is done and what it waits for, with the state the server computes from
 * them. A person changes the workplace, sets a wait with its reason and clears it here.
 */
export function CardWorkSection({
  boardId,
  loopId,
  card,
  onChanged,
}: {
  boardId: string;
  loopId: string;
  card: Card;
  onChanged: () => void;
}) {
  const headingId = useId();
  const work = useCardWork({ boardId, loopId, card, onChanged });
  const completed = card.completed_at !== null;
  const waiting = card.waiting_for !== "nothing";

  return (
    <section
      aria-labelledby={headingId}
      className="flex flex-col gap-2 rounded-lg border border-[var(--border)] p-3"
    >
      <div className="flex flex-wrap items-center gap-2">
        <h3 id={headingId} className="text-sm font-semibold">
          Where and what it waits for
        </h3>
        {card.state ? (
          <Badge tone={STATE_TONES[card.state]}>{STATE_LABELS[card.state]}</Badge>
        ) : null}
      </div>
      {card.state ? (
        <p className="text-xs text-[var(--muted-foreground)]">{STATE_HINTS[card.state]}</p>
      ) : null}

      <Field
        label="Where the work is done"
        htmlFor={`${headingId}-workplace`}
        hint={completed ? "A completed Ticket keeps what it said." : undefined}
      >
        <Select
          id={`${headingId}-workplace`}
          value={card.workplace}
          disabled={completed || work.pending}
          onChange={(event) => {
            const value = WORKPLACES.find((workplace) => workplace === event.target.value);
            if (value) work.setWorkplace(value);
          }}
        >
          {WORKPLACES.map((workplace) => (
            <option key={workplace} value={workplace}>
              {WORKPLACE_LABELS[workplace]}
            </option>
          ))}
        </Select>
      </Field>

      {waiting ? (
        <CurrentWait card={card} pending={work.pending} onClear={work.clearWait} />
      ) : completed ? null : (
        <WaitForm idPrefix={headingId} pending={work.pending} onSave={work.setWait} />
      )}

      {work.error ? (
        <p role="alert" className="text-xs text-[var(--destructive)]">
          {work.error}
        </p>
      ) : null}
    </section>
  );
}

/** The wait that is set: its kind, its reason, who set it and when, and the way to clear it. */
function CurrentWait({
  card,
  pending,
  onClear,
}: {
  card: Card;
  pending: boolean;
  onClear: () => void;
}) {
  const kind = WAITS.find((wait) => wait === card.waiting_for);
  return (
    <div className="flex flex-col gap-1 rounded-md bg-[var(--surface-raised)] p-2 text-xs">
      <p>
        <span className="font-medium">Waits for: </span>
        {kind ? WAIT_LABELS[kind] : card.waiting_for}
      </p>
      {card.waiting_reason ? <p className="whitespace-pre-wrap">{card.waiting_reason}</p> : null}
      <p className="text-[var(--muted-foreground)]">
        Set by {card.waiting_set_by ?? "unknown"} · {formatDateTime(card.waiting_set_at)}
      </p>
      {card.completed_at ? null : (
        <>
          <p className="text-[var(--muted-foreground)]">
            Clear the wait before this Ticket can be completed.
          </p>
          <div>
            <Button variant="outline" size="sm" disabled={pending} onClick={onClear}>
              Clear the wait
            </Button>
          </div>
        </>
      )}
    </div>
  );
}

/** "Mark as waiting": the kind and a required reason, saved together. */
function WaitForm({
  idPrefix,
  pending,
  onSave,
}: {
  idPrefix: string;
  pending: boolean;
  onSave: (value: { waiting_for: Wait; reason: string }) => Promise<boolean>;
}) {
  const [open, setOpen] = useState(false);
  const [kind, setKind] = useState<Wait>("decision");
  const [reason, setReason] = useState("");
  const trimmed = reason.trim();

  if (!open) {
    return (
      <div>
        <Button variant="outline" size="sm" onClick={() => setOpen(true)}>
          Mark as waiting
        </Button>
      </div>
    );
  }

  async function save() {
    if (!trimmed) return;
    if (await onSave({ waiting_for: kind, reason: trimmed })) {
      setOpen(false);
      setReason("");
    }
  }

  return (
    <div className="flex flex-col gap-2 rounded-md bg-[var(--surface-raised)] p-2">
      <Field label="It waits for" htmlFor={`${idPrefix}-wait`} hint={WAIT_HINTS[kind]}>
        <Select
          id={`${idPrefix}-wait`}
          value={kind}
          onChange={(event) => {
            const value = WAITS.find((wait) => wait === event.target.value);
            if (value) setKind(value);
          }}
        >
          {WAITS.map((wait) => (
            <option key={wait} value={wait}>
              {WAIT_LABELS[wait]}
            </option>
          ))}
        </Select>
      </Field>
      <Field
        label="Why (required)"
        htmlFor={`${idPrefix}-reason`}
        hint={`What has to be answered, at most ${WAITING_REASON_MAX} characters.`}
      >
        <Textarea
          id={`${idPrefix}-reason`}
          className="min-h-16"
          maxLength={WAITING_REASON_MAX}
          required
          value={reason}
          onChange={(event) => setReason(event.target.value)}
        />
      </Field>
      <div className="flex gap-2">
        <Button
          variant="secondary"
          size="sm"
          disabled={!trimmed || pending}
          onClick={() => {
            void save();
          }}
        >
          {pending ? "Saving…" : "Save the wait"}
        </Button>
        <Button variant="ghost" size="sm" onClick={() => setOpen(false)}>
          Cancel
        </Button>
      </div>
    </div>
  );
}
