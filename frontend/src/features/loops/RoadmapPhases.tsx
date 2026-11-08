import { Chip } from "@/components/ui/chip";
import { Expander } from "@/components/ui/expander";
import { Section } from "@/components/ui/section";
import { TicketExpanders } from "@/features/cards/TicketExpanders";
import { TicketFace } from "@/features/cards/TicketFace";
import {
  rowLine,
  waitLine,
  WORKPLACE_WORDS,
  type ReviewPhase,
  type ReviewTicket,
} from "./roadmapPlan";

/** The row's text: title, the muted line, then the small facts (key, person, place, wait). */
function RowText({ ticket }: { ticket: ReviewTicket }) {
  const line = rowLine(ticket);
  const wait = waitLine(ticket);
  return (
    <span className="grid min-w-0 gap-1">
      <span className="text-[15px] font-semibold leading-snug text-[var(--foreground)]">
        {ticket.title}
      </span>
      {line ? (
        <span className="text-sm font-normal text-[var(--muted-foreground)]">{line}</span>
      ) : null}
      <span className="flex flex-wrap items-center gap-x-2.5 gap-y-1 text-xs font-normal text-[var(--foreground-faint)]">
        {ticket.key ? <span className="font-mono">{ticket.key}</span> : null}
        {ticket.needsPerson ? <Chip>Needs a person</Chip> : null}
        <span>{WORKPLACE_WORDS[ticket.workplace]}</span>
      </span>
      {wait ? (
        <span className="text-[13px] font-normal text-[var(--muted-foreground)]">{wait}</span>
      ) : null}
    </span>
  );
}

/**
 * One planned Ticket. With a face the row expands to the steps and the face's sections, read only,
 * as the Ticket view shows them; without one (a plan written before faces) the row shows the
 * objective, and the acceptance criteria wait behind "More".
 */
function TicketRow({ ticket }: { ticket: ReviewTicket }) {
  if (ticket.face) {
    return (
      <li>
        <Expander title={<RowText ticket={ticket} />}>
          <TicketFace steps={ticket.face.steps} />
          <TicketExpanders face={ticket.face} />
        </Expander>
      </li>
    );
  }
  return (
    <li className="grid gap-3 rounded-lg border border-[var(--border)] bg-[var(--surface)] px-3.5 py-3">
      <RowText ticket={ticket} />
      {ticket.acceptanceCriteria.length > 0 ? (
        <Expander title="More" hint="Accepted when">
          <ul aria-label="Accepted when" className="m-0 grid list-disc gap-1.5 pl-5 text-sm">
            {ticket.acceptanceCriteria.map((criterion, index) => (
              <li key={index}>{criterion}</li>
            ))}
          </ul>
        </Expander>
      ) : null}
    </li>
  );
}

/**
 * The plan for a person who decides on it: one Section per Phase (number and name, the objective
 * in one muted line, the count of Tickets), a row per Ticket.
 */
export function RoadmapPhases({ phases }: { phases: readonly ReviewPhase[] }) {
  return (
    <div className="grid gap-6">
      {phases.map((phase) => (
        <Section
          key={phase.id || phase.number}
          title={`Phase ${phase.number} · ${phase.name}`}
          count={phase.tickets.length}
          size="lg"
        >
          {phase.objective ? (
            <p className="-mt-1 mb-3 truncate text-sm text-[var(--muted-foreground)]">
              {phase.objective}
            </p>
          ) : null}
          {phase.tickets.length > 0 ? (
            <ul
              aria-label={`Tickets of Phase ${phase.number}`}
              className="m-0 grid list-none gap-2 p-0"
            >
              {phase.tickets.map((ticket) => (
                <TicketRow key={ticket.id || ticket.title} ticket={ticket} />
              ))}
            </ul>
          ) : (
            <p className="text-sm text-[var(--foreground-faint)]">No Tickets in this Phase.</p>
          )}
        </Section>
      ))}
    </div>
  );
}
