import { AlertTriangle, Check, User } from "lucide-react";
import { useMemo } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent } from "@/components/ui/dialog";
import { api } from "@/lib/api";
import { useReadiness } from "@/lib/queries";
import type { Loop, PlanPhaseView, PlanTicketView } from "@/lib/types";

const PHASE_TONES = {
  pending: "neutral",
  active: "brand",
  complete: "success",
} as const;

export function LoopPlanDialog({
  boardId,
  loop,
  open,
  onClose,
  onChanged,
}: {
  boardId: string;
  loop: Loop;
  open: boolean;
  onClose: () => void;
  onChanged: () => void;
}) {
  const readiness = useReadiness(boardId, loop.id);
  const phases: PlanPhaseView[] = useMemo(() => readiness.data?.phases ?? [], [readiness.data]);

  return (
    <Dialog open={open} onOpenChange={(value) => (!value ? onClose() : undefined)}>
      <DialogContent
        title={`${loop.key} plan and readiness`}
        description="Phases group the work; columns do not. Readiness comes from the approved dependency graph."
        className="w-[min(920px,96vw)]"
      >
        {readiness.data?.blocked_reason ? (
          <p className="mb-3 flex items-center gap-2 rounded-lg border border-[var(--warning)] p-2 text-xs text-[var(--warning)]">
            <AlertTriangle size={14} /> {readiness.data.blocked_reason.message}
          </p>
        ) : null}

        {phases.length === 0 ? (
          <p className="rounded-lg border border-dashed border-[var(--border)] p-3 text-xs text-[var(--muted-foreground)]">
            No approved plan has been published for this Loop yet.
          </p>
        ) : (
          <ol className="flex flex-col gap-3">
            {phases.map((phase) => (
              <li
                key={phase.id}
                className="rounded-lg border border-[var(--border)] bg-[var(--surface-raised)] p-3"
              >
                <div className="flex flex-wrap items-center gap-2">
                  <span className="font-mono text-xs text-[var(--muted-foreground)]">
                    Phase {phase.number}
                  </span>
                  <span className="text-sm font-medium">{phase.name}</span>
                  <Badge tone={PHASE_TONES[phase.state]}>{phase.state}</Badge>
                </div>
                {phase.objective ? (
                  <p className="mt-1 text-xs text-[var(--muted-foreground)]">{phase.objective}</p>
                ) : null}
                {phase.blocked_by.length > 0 ? (
                  <p className="mt-1 text-[11px] text-[var(--warning)]">
                    Waiting for:{" "}
                    {phase.blocked_by
                      .map((blocker) =>
                        blocker.type === "phase"
                          ? `Phase ${blocker.phase_number ?? "?"}`
                          : (blocker.key ?? "Ticket"),
                      )
                      .join(", ")}
                  </p>
                ) : null}
                <ul className="mt-2 flex flex-col gap-1.5">
                  {phase.tickets.map((ticket) => (
                    <TicketRow
                      key={ticket.id}
                      ticket={ticket}
                      disabled={loop.stage === "completed"}
                      onChanged={onChanged}
                      boardId={boardId}
                      loopId={loop.id}
                    />
                  ))}
                </ul>
              </li>
            ))}
          </ol>
        )}
      </DialogContent>
    </Dialog>
  );
}

function TicketRow({
  ticket,
  boardId,
  loopId,
  disabled,
  onChanged,
}: {
  ticket: PlanTicketView;
  boardId: string;
  loopId: string;
  disabled: boolean;
  onChanged: () => void;
}) {
  return (
    <li className="rounded-md border border-[var(--border)] bg-[var(--surface)] px-2 py-1.5">
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-mono text-[11px] text-[var(--muted-foreground)]">{ticket.key}</span>
        <span className="text-sm">{ticket.title}</span>
        {ticket.human_action_required ? (
          <Badge tone="warning">
            <User size={11} /> Human action required
          </Badge>
        ) : null}
        {ticket.execution_mode === "pre_phase_gate" ? (
          <Badge tone="brand">gate</Badge>
        ) : null}
        {ticket.completed_at ? (
          <Badge tone="success">
            <Check size={11} /> done
          </Badge>
        ) : null}
        {!ticket.ready && !ticket.completed_at ? (
          <Badge tone="neutral">blocked</Badge>
        ) : null}
      </div>
      {ticket.human_action_required && ticket.human_action_reason ? (
        <p className="mt-1 text-[11px] text-[var(--muted-foreground)]">
          Why a human is needed: {ticket.human_action_reason}
        </p>
      ) : null}
      {ticket.human_action_required && ticket.human_instructions ? (
        <p className="text-[11px] text-[var(--muted-foreground)]">
          What to do: {ticket.human_instructions}
        </p>
      ) : null}
      {ticket.human_action_required && ticket.downstream_phase_numbers.length > 0 ? (
        <p className="text-[11px] text-[var(--muted-foreground)]">
          Until this is confirmed, Phase {ticket.downstream_phase_numbers.join(", ")} and its
          dependent phases cannot start.
        </p>
      ) : null}
      {ticket.blockers.length > 0 && !ticket.completed_at ? (
        <p className="text-[11px] text-[var(--warning)]">
          Blocked by:{" "}
          {ticket.blockers
            .map((blocker) =>
              blocker.type === "phase"
                ? `Phase ${blocker.phase_number ?? "?"}`
                : (blocker.key ?? "Ticket"),
            )
            .join(", ")}
        </p>
      ) : null}
      {ticket.card_id && ticket.human_action_required ? (
        <div className="mt-1 flex justify-end">
          <ConfirmButton
            boardId={boardId}
            loopId={loopId}
            cardId={ticket.card_id}
            disabled={disabled || !ticket.ready}
            onChanged={onChanged}
          />
        </div>
      ) : null}
    </li>
  );
}

function ConfirmButton({
  boardId,
  loopId,
  cardId,
  disabled,
  onChanged,
}: {
  boardId: string;
  loopId: string;
  cardId: string;
  disabled: boolean;
  onChanged: () => void;
}) {
  async function confirm() {
    const card = await api.getCard(boardId, loopId, cardId);
    await api.confirmHumanTicket(boardId, loopId, cardId, { version: card.version });
    onChanged();
  }

  return (
    <Button
      size="sm"
      variant="outline"
      disabled={disabled}
      onClick={() => {
        void confirm();
      }}
    >
      Confirm human action
    </Button>
  );
}
