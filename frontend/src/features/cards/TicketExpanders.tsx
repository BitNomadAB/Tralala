import type { ReactNode } from "react";
import { Expander } from "@/components/ui/expander";
import type { TicketFace } from "@/lib/types";
import { prosConsHint } from "./ticketText";

function Points({
  label,
  items,
  mark,
  tone,
}: {
  label: string;
  items: readonly string[];
  mark: string;
  tone: string;
}) {
  return (
    <ul aria-label={label} className="m-0 grid list-none content-start gap-[7px] p-0 text-[14.5px]">
      {items.map((item, index) => (
        <li key={index} className="grid grid-cols-[16px_minmax(0,1fr)] items-baseline gap-2">
          <span aria-hidden="true" className={`text-[13px] font-bold ${tone}`}>
            {mark}
          </span>
          <span>{item}</span>
        </li>
      ))}
    </ul>
  );
}

/**
 * The face's sections as buttons that expand: Why it is needed, If we skip it, and Pro and con in
 * two columns, each absent when the face has nothing for it; `children` follow them (the Ticket
 * view's Your notes). Read only: the RoadMap review shows a face the same way.
 */
export function TicketExpanders({
  face,
  children,
}: {
  face: TicketFace | null;
  children?: ReactNode;
}) {
  return (
    <div className="grid gap-2">
      {face?.why ? (
        <Expander title="Why it is needed">
          <p className="m-0 max-w-[60ch] text-[14.5px]">{face.why}</p>
        </Expander>
      ) : null}
      {face?.if_skipped ? (
        <Expander title="If we skip it">
          <p className="m-0 max-w-[60ch] text-[14.5px]">{face.if_skipped}</p>
        </Expander>
      ) : null}
      {face && face.pros.length + face.cons.length > 0 ? (
        <Expander title="Pro and con" hint={prosConsHint(face)}>
          <div className="grid grid-cols-1 gap-7 sm:grid-cols-2">
            <Points label="For" items={face.pros} mark="+" tone="text-[var(--success)]" />
            <Points label="Against" items={face.cons} mark="–" tone="text-[var(--warning)]" />
          </div>
        </Expander>
      ) : null}
      {children}
    </div>
  );
}
