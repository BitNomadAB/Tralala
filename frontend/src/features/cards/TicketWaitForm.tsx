import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Field, Select, Textarea } from "@/components/ui/input";
import { ReasonButton } from "@/components/ui/reason-button";
import { useLoopStops } from "@/lib/queries";
import type { Wait } from "@/lib/types";
import {
  SAVING,
  WAIT_HINTS,
  WAIT_LABELS,
  WAIT_REASON_FIRST,
  WAITING_REASON_MAX,
  WAITS,
} from "./ticketWork";
import type { WaitValue } from "./useCardWork";

/** The stop picker's choice for a wait that names no line of the stop list. */
const NO_STOP = "";

export const WAIT_STOP_HINT = "Optional: the line of the Loop's stop list this wait is for.";

/**
 * "Mark as waiting": the kind, a required reason and, optionally, the line of the Loop's stop list
 * the wait is for, saved together. The kind takes the focus when the form opens; Cancel hands
 * `onCancel` what had the focus before, so it can go back there. The stop list is read when the
 * form opens; a Loop whose list is empty offers no stop.
 */
export function WaitForm({
  boardId,
  loopId,
  pending,
  onSave,
  onCancel,
}: {
  boardId: string;
  loopId: string;
  pending: boolean;
  onSave: (value: WaitValue) => Promise<boolean>;
  onCancel: (opener: HTMLElement | null) => void;
}) {
  const [kind, setKind] = useState<Wait>("decision");
  const [reason, setReason] = useState("");
  const [stop, setStop] = useState(NO_STOP);
  const stops = useLoopStops(boardId, loopId).data?.stops ?? [];
  // Read while the form is first drawn, before its field takes the focus: the control that opened it.
  const [opener] = useState(() =>
    document.activeElement instanceof HTMLElement ? document.activeElement : null,
  );
  const trimmed = reason.trim();

  return (
    <div className="grid gap-2 rounded-md bg-[var(--surface-raised)] p-2.5">
      <Field label="It waits for" htmlFor="ticket-wait-kind" hint={WAIT_HINTS[kind]}>
        <Select
          id="ticket-wait-kind"
          autoFocus
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
        htmlFor="ticket-wait-reason"
        hint={`What has to be answered, at most ${WAITING_REASON_MAX} characters.`}
      >
        <Textarea
          id="ticket-wait-reason"
          className="min-h-16"
          maxLength={WAITING_REASON_MAX}
          required
          value={reason}
          onChange={(event) => setReason(event.target.value)}
        />
      </Field>
      {stops.length > 0 ? (
        <Field label="Stop (optional)" htmlFor="ticket-wait-stop" hint={WAIT_STOP_HINT}>
          <Select
            id="ticket-wait-stop"
            value={stop}
            onChange={(event) => setStop(event.target.value)}
          >
            <option value={NO_STOP}>No stop named</option>
            {stops.map((line) => (
              <option key={line} value={line}>
                {line}
              </option>
            ))}
          </Select>
        </Field>
      ) : null}
      <div className="flex flex-wrap items-start gap-2">
        <ReasonButton
          variant="secondary"
          size="sm"
          disabledReason={!trimmed ? WAIT_REASON_FIRST : pending ? SAVING : null}
          onClick={() => {
            void onSave({
              waiting_for: kind,
              reason: trimmed,
              ...(stop === NO_STOP ? {} : { stop }),
            });
          }}
        >
          Save the wait
        </ReasonButton>
        <Button variant="ghost" size="sm" onClick={() => onCancel(opener)}>
          Cancel
        </Button>
      </div>
    </div>
  );
}
