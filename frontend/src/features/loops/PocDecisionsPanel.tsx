import { useQueryClient } from "@tanstack/react-query";
import { useCallback, useMemo, useState } from "react";
import { EmptyState } from "@/components/ui/empty-state";
import { Expander } from "@/components/ui/expander";
import { Section } from "@/components/ui/section";
import { describeError } from "@/lib/describeError";
import { keys, usePocDecisions } from "@/lib/queries";
import type { PocDecision, PocDecisionList } from "@/lib/types";
import type { PocAnswered } from "./PocAnswer";
import { PocDecisionItem } from "./PocDecisionItem";
import { naturalGroup, POC_EMPTY, pocGroups, waitingLine, type PocGroupId } from "./pocDecisions";

/**
 * The Decisions tab: what agents decided without stopping, and what is missing from a person, in
 * the server's review order under "Other work builds on these", "Missing from a person", "Other
 * decisions" and "Answered" (collapsed, with its count); an empty group is left out. The line above
 * says how many wait for an answer.
 *
 * A record answered on this visit stays where it was, showing its answer, so nothing jumps away
 * from the person who just answered it; it is under "Answered" the next time the page is opened.
 * An answer refetches the records and, through `onChanged`, the Loop's Tickets and summaries (a
 * feedback is a new Ticket). No answer is offered in a read-only Loop or to a key.
 */
export function PocDecisionsPanel({
  boardId,
  loopId,
  canAnswer,
  onChanged,
}: {
  boardId: string;
  loopId: string;
  canAnswer: boolean;
  onChanged: () => void;
}) {
  const queryClient = useQueryClient();
  const decisions = usePocDecisions(boardId, loopId);
  const [kept, setKept] = useState<ReadonlyMap<string, PocGroupId>>(new Map());

  const onAnswered = useCallback<PocAnswered>(
    (before, after) => {
      setKept((current) =>
        current.has(before.id) ? current : new Map(current).set(before.id, naturalGroup(before)),
      );
      queryClient.setQueryData<PocDecisionList>(keys.pocDecisions(boardId, loopId), (current) =>
        current
          ? {
              ...current,
              items: current.items.map((entry): PocDecision =>
                entry.id === after.id ? after : entry,
              ),
            }
          : current,
      );
      void queryClient.invalidateQueries({ queryKey: keys.pocDecisions(boardId, loopId) });
      onChanged();
    },
    [queryClient, boardId, loopId, onChanged],
  );

  const items = decisions.data?.items;
  const groups = useMemo(() => pocGroups(items ?? [], kept), [items, kept]);

  return (
    <Section title="POC decisions" level={2} className="max-w-4xl">
      {decisions.isPending ? (
        <p className="text-sm text-[var(--muted-foreground)]">Loading decisions…</p>
      ) : decisions.error ? (
        <p role="alert" className="text-sm text-[var(--destructive)]">
          {describeError(decisions.error, "The decisions could not be read.")}
        </p>
      ) : groups.length === 0 ? (
        <EmptyState message={POC_EMPTY} className="card-surface px-4 py-3.5" />
      ) : (
        <div className="grid gap-5">
          <p className="m-0 text-sm text-[var(--foreground)]">
            {waitingLine(decisions.data.counts.open)}
          </p>
          {groups.map((group) => {
            const list = (
              <ol aria-label={group.title} className="m-0 grid list-none gap-3 p-0">
                {group.items.map((item) => (
                  <li key={item.id}>
                    <PocDecisionItem
                      boardId={boardId}
                      loopId={loopId}
                      item={item}
                      canAnswer={canAnswer}
                      onAnswered={onAnswered}
                    />
                  </li>
                ))}
              </ol>
            );
            return group.id === "answered" ? (
              <Expander
                key={group.id}
                title={<h3 className="m-0 text-[inherit] font-[inherit]">{group.title}</h3>}
                hint={group.items.length}
              >
                {list}
              </Expander>
            ) : (
              <Section key={group.id} title={group.title} count={group.items.length} size="lg">
                {list}
              </Section>
            );
          })}
        </div>
      )}
    </Section>
  );
}
