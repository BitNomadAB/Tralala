import { CircleCheck } from "lucide-react";
import { useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { StateChip } from "@/components/ui/chip";
import { Field, Select, Textarea } from "@/components/ui/input";
import { ReasonButton } from "@/components/ui/reason-button";
import { useAnnounce } from "@/components/ui/useAnnounce";
import type { Card, Wait } from "@/lib/types";
import { formatDateTime } from "@/lib/utils";
import { stateReason } from "./ticketRules";
import { SAVING, WAIT_HINTS, WAIT_LABELS, WAITING_REASON_MAX, WAITS } from "./ticketWork";
import { useCardWork } from "./useCardWork";
import { focusTarget, useFocusAfter } from "./useFocusAfter";

const LINK =
  "w-fit rounded text-[13px] text-[var(--primary)] hover:underline focus-visible:outline-2 focus-visible:outline-[var(--ring)] disabled:opacity-50";

/** Why Save the wait cannot be pressed yet. */
export const WAIT_REASON_FIRST = "Write why it waits first.";

/**
 * Where the Ticket stands, under its column in the rail: the state with what holds it up, the wait
 * that is set (with Clear the wait), "Mark as waiting…" with its form inline, and, for a Ticket only
 * a person can do, the confirmation that completes it. The server computes the state from the wait
 * and the plan; a person sets a wait with its reason and clears it here.
 *
 * Each change says what it did ("Wait saved", "Wait cleared") and hands the focus on (WCAG 2.4.3):
 * a saved wait to its Clear the wait, a cleared one to Mark as waiting…, a cancelled form back to
 * whatever opened it.
 */
export function TicketState({
  boardId,
  loopId,
  card,
  readOnly,
  onChanged,
  waitOpen,
  onWaitOpenChange,
  onConfirm,
  confirmBlocked,
  pending,
}: {
  boardId: string;
  loopId: string;
  card: Card;
  readOnly: boolean;
  onChanged: () => void;
  /** Whether the wait form is open; the head's Mark as waiting opens it too. */
  waitOpen: boolean;
  onWaitOpenChange: (open: boolean) => void;
  onConfirm: () => void;
  /** Why the confirmation cannot be given yet, or null. */
  confirmBlocked: string | null;
  pending: boolean;
}) {
  const work = useCardWork({ boardId, loopId, card, onChanged });
  const announce = useAnnounce();
  const focusAfter = useFocusAfter();
  const root = useRef<HTMLDivElement>(null);
  const completed = card.completed_at !== null;
  const waiting = card.waiting_for !== "nothing";
  const markWaiting = () => focusTarget(root.current, "mark-waiting");

  async function save(value: { waiting_for: Wait; reason: string }): Promise<boolean> {
    const saved = await work.setWait(value);
    if (saved) {
      announce("Wait saved");
      onWaitOpenChange(false);
      focusAfter(() => focusTarget(root.current, "clear-wait"));
    }
    return saved;
  }

  async function clear() {
    if (!(await work.clearWait())) return;
    announce("Wait cleared");
    focusAfter(markWaiting);
  }

  return (
    // `contents`: the rail's section lays the parts out; this only gives the focus a place to look.
    <div ref={root} className="contents">
      {card.state ? (
        <StateChip state={card.state} reason={stateReason(card)} />
      ) : completed ? (
        <span className="inline-flex items-center gap-2 text-sm">
          <CircleCheck size={15} aria-hidden="true" className="text-[var(--success)]" />
          <b className="font-semibold">Completed</b>
          <span className="text-[var(--muted-foreground)]">
            · {formatDateTime(card.completed_at)}
          </span>
        </span>
      ) : null}

      {waiting ? (
        <CurrentWait card={card} pending={work.pending} onClear={() => void clear()} />
      ) : completed || readOnly ? null : waitOpen ? (
        <WaitForm
          pending={work.pending}
          onSave={save}
          onCancel={(opener) => {
            onWaitOpenChange(false);
            focusAfter(() => (opener?.isConnected ? opener : markWaiting()));
          }}
        />
      ) : (
        <button
          type="button"
          className={LINK}
          data-focus-target="mark-waiting"
          onClick={() => onWaitOpenChange(true)}
        >
          Mark as waiting…
        </button>
      )}

      {card.human_action_required && !completed && !readOnly ? (
        <div className="grid gap-1.5 rounded-md border border-[var(--border)] p-2.5 text-[13px]">
          <p className="m-0 text-[var(--muted-foreground)]">
            Only a person can do this work; confirm it once it is done.
          </p>
          <ReasonButton
            variant="secondary"
            size="sm"
            wrapperClassName="justify-self-start"
            data-focus-target="confirm"
            disabledReason={confirmBlocked ?? (pending ? SAVING : null)}
            onClick={onConfirm}
          >
            <CircleCheck size={14} aria-hidden="true" /> Confirm human action
          </ReasonButton>
        </div>
      ) : null}

      {work.error ? (
        <p role="alert" className="m-0 text-xs text-[var(--destructive)]">
          {work.error}
        </p>
      ) : null}
    </div>
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
    <div className="grid gap-1 rounded-md bg-[var(--surface-raised)] p-2.5 text-[13px]">
      <p className="m-0">
        <span className="font-medium">Waits for: </span>
        {kind ? WAIT_LABELS[kind] : card.waiting_for}
      </p>
      {card.waiting_reason ? (
        <p className="m-0 whitespace-pre-wrap">{card.waiting_reason}</p>
      ) : null}
      <p className="m-0 text-xs text-[var(--muted-foreground)]">
        Set by {card.waiting_set_by ?? "unknown"} · {formatDateTime(card.waiting_set_at)}
      </p>
      {/* A Ticket left undone in a closed Loop keeps its wait as it was; nobody clears it. */}
      {card.completed_at || card.state === "not_done" ? null : (
        <>
          <p className="m-0 text-xs text-[var(--muted-foreground)]">
            Clear the wait before this Ticket can be completed.
          </p>
          <ReasonButton
            variant="outline"
            size="sm"
            wrapperClassName="justify-self-start"
            data-focus-target="clear-wait"
            disabledReason={pending ? SAVING : null}
            onClick={onClear}
          >
            Clear the wait
          </ReasonButton>
        </>
      )}
    </div>
  );
}

/**
 * "Mark as waiting": the kind and a required reason, saved together. The kind takes the focus when
 * the form opens; Cancel hands `onCancel` what had the focus before, so it can go back there.
 */
function WaitForm({
  pending,
  onSave,
  onCancel,
}: {
  pending: boolean;
  onSave: (value: { waiting_for: Wait; reason: string }) => Promise<boolean>;
  onCancel: (opener: HTMLElement | null) => void;
}) {
  const [kind, setKind] = useState<Wait>("decision");
  const [reason, setReason] = useState("");
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
      <div className="flex flex-wrap items-start gap-2">
        <ReasonButton
          variant="secondary"
          size="sm"
          disabledReason={!trimmed ? WAIT_REASON_FIRST : pending ? SAVING : null}
          onClick={() => {
            void onSave({ waiting_for: kind, reason: trimmed });
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
