import { useState } from "react";
import { Avatar } from "@/components/ui/avatar";
import { LabelChip } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Chip } from "@/components/ui/chip";
import { Fact, Facts } from "@/components/ui/facts";
import { SelectMenu } from "@/components/ui/select-menu";
import {
  PRIORITIES,
  type BoardPerson,
  type Card,
  type Label,
  type LoopReadiness,
} from "@/lib/types";
import { formatDate, fromDateInputValue, toDateInputValue } from "@/lib/utils";
import { EditableFact } from "./EditableFact";
import { createdText, dependencies, phaseName, priorityLabel } from "./ticketRules";
import { WORKPLACE_LABELS, WORKPLACES } from "./ticketWork";
import type { TicketActions } from "./useTicketActions";

/** The value the owner menu uses for nobody; an actor id is never empty. */
const NOBODY = "";

/**
 * "Details": the Ticket's facts, each a value that turns into its control when clicked and saves
 * itself with the version. The Phase and what the Ticket depends on come from the plan, and read
 * None while it is not loaded.
 */
export function TicketFacts({
  card,
  readiness,
  people,
  labels,
  readOnly,
  actions,
}: {
  card: Card;
  readiness: LoopReadiness | undefined;
  people: readonly BoardPerson[];
  labels: readonly Label[];
  readOnly: boolean;
  actions: Pick<TicketActions, "assign" | "setWorkplace" | "update">;
}) {
  const owners = [
    { value: NOBODY, label: "Nobody" },
    ...people.map((person) => ({ value: person.id, label: person.name })),
  ];
  // An agent (or a person no longer listed) who owns it stays choosable as it is.
  if (card.assignee_actor_id && !people.some((person) => person.id === card.assignee_actor_id)) {
    owners.push({ value: card.assignee_actor_id, label: card.assignee_name ?? "Someone" });
  }
  const phase = phaseName(card, readiness);
  const after = dependencies(card, readiness);

  return (
    <Facts>
      <EditableFact
        label="Owner"
        valueText={card.assignee_name ?? "None"}
        none={card.assignee_actor_id === null}
        readOnly={readOnly}
        editor={(done) => (
          <SelectMenu
            label="Owner"
            value={card.assignee_actor_id ?? NOBODY}
            options={owners}
            defaultOpen
            onChange={(next) => void actions.assign(next === NOBODY ? null : next)}
            onClose={done}
            className="w-full"
          />
        )}
      >
        {card.assignee_name ? (
          <>
            <Avatar name={card.assignee_name} size="sm" />
            {card.assignee_name}
          </>
        ) : null}
      </EditableFact>

      <Fact label="Phase" none={card.phase_number === null}>
        {card.phase_number}
        {phase ? ` · ${phase}` : null}
      </Fact>

      <EditableFact
        label="Work is done"
        valueText={WORKPLACE_LABELS[card.workplace]}
        readOnly={readOnly || card.completed_at !== null}
        editor={(done) => (
          <SelectMenu
            label="Work is done"
            value={card.workplace}
            options={WORKPLACES.map((value) => ({ value, label: WORKPLACE_LABELS[value] }))}
            defaultOpen
            onChange={(next) => void actions.setWorkplace(next)}
            onClose={done}
            className="w-full"
          />
        )}
      >
        {WORKPLACE_LABELS[card.workplace]}
      </EditableFact>

      <Fact label="Depends on" none={after.length === 0}>
        {after.map((item) => (
          <Chip
            key={item.id}
            mono
            trailing={
              item.done ? (
                <span className="text-xs font-semibold text-[var(--success)]">done</span>
              ) : undefined
            }
          >
            {item.key}
          </Chip>
        ))}
      </Fact>

      <EditableFact
        label="Priority"
        valueText={priorityLabel(card.priority)}
        none={card.priority === "none"}
        readOnly={readOnly}
        editor={(done) => (
          <SelectMenu
            label="Priority"
            value={card.priority}
            options={PRIORITIES.map((value) => ({ value, label: priorityLabel(value) }))}
            defaultOpen
            onChange={(priority) => void actions.update({ priority })}
            onClose={done}
            className="w-full"
          />
        )}
      >
        {priorityLabel(card.priority)}
      </EditableFact>

      <EditableFact
        label="Due"
        valueText={card.due_at ? formatDate(card.due_at) : "None"}
        none={card.due_at === null}
        readOnly={readOnly}
        editor={(done) => (
          <DueEditor
            value={card.due_at}
            onDone={done}
            onSave={(due) =>
              void actions.update(
                due === null ? { clear_due_at: true } : { due_at: fromDateInputValue(due) ?? "" },
              )
            }
          />
        )}
      >
        {formatDate(card.due_at)}
      </EditableFact>

      <EditableFact
        label="Labels"
        valueText={card.labels.map((label) => label.name).join(", ") || "None"}
        none={card.labels.length === 0}
        readOnly={readOnly}
        editor={(done) => (
          <LabelPicker
            chosen={card.labels.map((label) => label.id)}
            labels={labels}
            onChange={(ids) => void actions.update({ labels: ids })}
            onDone={done}
          />
        )}
      >
        {card.labels.map((label) => (
          <LabelChip key={label.id} name={label.name} color={label.color} />
        ))}
      </EditableFact>

      <Fact label="Created">{createdText(card)}</Fact>
    </Facts>
  );
}

/** A date field: Enter or leaving it saves a change, Escape keeps the date, Clear removes it. */
function DueEditor({
  value,
  onSave,
  onDone,
}: {
  value: string | null;
  onSave: (due: string | null) => void;
  onDone: () => void;
}) {
  const initial = toDateInputValue(value);
  const [draft, setDraft] = useState(initial);

  function commit() {
    if (draft !== initial) onSave(draft === "" ? null : draft);
    onDone();
  }

  return (
    <span className="flex flex-wrap items-center gap-2">
      <input
        type="date"
        aria-label="Due date"
        autoFocus
        data-keeps-escape=""
        value={draft}
        onChange={(event) => setDraft(event.target.value)}
        onBlur={commit}
        onKeyDown={(event) => {
          if (event.key === "Enter") {
            event.preventDefault();
            commit();
          } else if (event.key === "Escape") {
            event.preventDefault();
            onDone();
          }
        }}
        className="h-8 rounded-md border border-[var(--border)] bg-[var(--surface)] px-2 text-sm text-[var(--foreground)]"
      />
      {value ? (
        <Button
          variant="quiet"
          size="sm"
          // Keeps the field focused, so its blur does not close the editor before the click lands.
          onMouseDown={(event) => event.preventDefault()}
          onClick={() => {
            onSave(null);
            onDone();
          }}
        >
          Clear
        </Button>
      ) : null}
    </span>
  );
}

/** The board's labels as toggles; each press saves, Done (or Escape) closes the picker. */
function LabelPicker({
  chosen,
  labels,
  onChange,
  onDone,
}: {
  chosen: string[];
  labels: readonly Label[];
  onChange: (ids: string[]) => void;
  onDone: () => void;
}) {
  return (
    <span className="flex flex-wrap items-center gap-1.5" data-keeps-escape="">
      {labels.length === 0 ? (
        <span className="text-xs text-[var(--muted-foreground)]">No labels on this board yet.</span>
      ) : (
        labels.map((label) => {
          const selected = chosen.includes(label.id);
          return (
            <button
              key={label.id}
              type="button"
              aria-pressed={selected}
              onClick={() =>
                onChange(selected ? chosen.filter((id) => id !== label.id) : [...chosen, label.id])
              }
              onKeyDown={(event) => {
                if (event.key === "Escape") onDone();
              }}
              className={selected ? "opacity-100" : "opacity-45"}
            >
              <LabelChip name={label.name} color={label.color} />
            </button>
          );
        })
      )}
      <Button
        variant="quiet"
        size="sm"
        autoFocus
        onClick={onDone}
        onKeyDown={(event) => {
          if (event.key === "Escape") onDone();
        }}
      >
        Done
      </Button>
    </span>
  );
}
