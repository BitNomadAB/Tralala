import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useId, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { Field, Textarea } from "@/components/ui/input";
import { ReasonButton } from "@/components/ui/reason-button";
import { Section } from "@/components/ui/section";
import { useAnnounce } from "@/components/ui/useAnnounce";
import { focusTarget, useFocusAfter } from "@/features/cards/useFocusAfter";
import { api } from "@/lib/api";
import { describeError } from "@/lib/describeError";
import { keys, useLoopStops } from "@/lib/queries";
import type { StopList } from "@/lib/types";
import {
  STOP_MAX_CHARS,
  stopLines,
  STOPS_DEFAULT,
  STOPS_MAX,
  STOPS_NONE,
  STOPS_RULE,
} from "./stopList";

/**
 * "Stops" under Info: the Loop's stop list, what it means, whether it is the default list, and for
 * a person in a Loop that takes writes "Edit stops", which opens the list as one line a stop with
 * "Save stops" and "Cancel". The server checks the list (`422 stops_invalid` names each line and
 * rule) and its message is shown as it words it. A save is announced and hands the focus back to
 * "Edit stops".
 */
export function LoopStops({
  boardId,
  loopId,
  canEdit,
}: {
  boardId: string;
  loopId: string;
  /** A person in a Loop that takes writes. */
  canEdit: boolean;
}) {
  const queryClient = useQueryClient();
  const announce = useAnnounce();
  const focusAfter = useFocusAfter();
  const root = useRef<HTMLDivElement>(null);
  const fieldId = useId();
  const stops = useLoopStops(boardId, loopId);
  const [draft, setDraft] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const save = useMutation({
    mutationFn: (lines: string[]) => api.saveLoopStops(boardId, loopId, lines),
    onMutate: () => {
      setError(null);
    },
    onSuccess: (saved) => {
      queryClient.setQueryData<StopList>(keys.loopStops(boardId, loopId), saved);
      setDraft(null);
      announce("Stops saved");
      focusAfter(() => focusTarget(root.current, "edit-stops"));
    },
    onError: (refusal) => {
      setError(describeError(refusal, "The stops were not saved."));
    },
  });

  const list = stops.data;
  const backToEdit = () => {
    setDraft(null);
    setError(null);
    focusAfter(() => focusTarget(root.current, "edit-stops"));
  };

  return (
    <Section title="Stops" level={3} className="mt-2">
      <div ref={root} className="grid gap-2 text-sm">
        <p className="m-0 text-[var(--muted-foreground)]">{STOPS_RULE}</p>
        {stops.error ? (
          <p role="alert" className="m-0 text-[var(--destructive)]">
            {describeError(stops.error, "The stops could not be read.")}
          </p>
        ) : !list ? (
          <p className="m-0 text-[var(--muted-foreground)]">Loading stops…</p>
        ) : draft === null ? (
          <>
            {list.is_default ? (
              <p className="m-0 text-xs text-[var(--foreground-faint)]">{STOPS_DEFAULT}</p>
            ) : null}
            {list.stops.length > 0 ? (
              <ul aria-label="Stops" className="m-0 grid list-disc gap-1 pl-5">
                {list.stops.map((stop) => (
                  <li key={stop}>{stop}</li>
                ))}
              </ul>
            ) : (
              <p className="m-0 text-[var(--foreground-faint)]">{STOPS_NONE}</p>
            )}
            {canEdit ? (
              <Button
                size="sm"
                variant="outline"
                className="justify-self-start"
                data-focus-target="edit-stops"
                onClick={() => {
                  setError(null);
                  setDraft(list.stops.join("\n"));
                }}
              >
                Edit stops
              </Button>
            ) : null}
          </>
        ) : (
          <div className="grid gap-2 rounded-md bg-[var(--surface-raised)] p-2.5">
            <Field
              label="Stops, one a line"
              htmlFor={fieldId}
              hint={`At most ${STOPS_MAX} lines of ${STOP_MAX_CHARS} characters each. An empty list means nothing stops.`}
            >
              <Textarea
                id={fieldId}
                autoFocus
                rows={Math.min(Math.max(stopLines(draft).length + 1, 4), STOPS_MAX + 1)}
                value={draft}
                onChange={(event) => setDraft(event.target.value)}
              />
            </Field>
            <div className="flex flex-wrap items-start gap-2">
              <ReasonButton
                variant="secondary"
                size="sm"
                disabledReason={save.isPending ? "Saving…" : null}
                onClick={() => save.mutate(stopLines(draft))}
              >
                Save stops
              </ReasonButton>
              <Button variant="ghost" size="sm" onClick={backToEdit}>
                Cancel
              </Button>
            </div>
          </div>
        )}
        {error ? (
          <p role="alert" className="m-0 text-xs text-[var(--destructive)]">
            {error}
          </p>
        ) : null}
      </div>
    </Section>
  );
}
