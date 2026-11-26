import { ButtonLink } from "@/components/ui/button-link";
import { EmptyState } from "@/components/ui/empty-state";
import { Section } from "@/components/ui/section";
import { inboxPath, WAITS_ON_DISCUSSION } from "@/features/discussions/inboxRules";
import { loopHref } from "@/features/loops/loopNextAction";
import { WithoutPlanChip } from "@/features/loops/WithoutPlanChip";
import type { DiscussionInboxRow } from "@/lib/types";
import type { WaitingRow } from "./boardSummaries";

/**
 * What waits for the person, first: one row per Loop, across their boards, whose next step is a
 * decision only a person makes. Each row names the board and the Loop (marked "Without a plan" when
 * it runs without one), says what it waits for and offers the link that opens the Loop page where
 * the decision is made. After the Loops come the discussions that wait for the person's decision,
 * each opening the discussion on its Ticket or on its board. Rows appear as each board answers;
 * `pending` says some have not answered yet.
 */
export function WaitsForYou({
  rows,
  discussions,
  pending,
  failed,
}: {
  rows: readonly WaitingRow[];
  /** Inbox rows that wait for the person's decision. */
  discussions: readonly DiscussionInboxRow[];
  pending: boolean;
  failed: number;
}) {
  const count = rows.length + discussions.length;
  return (
    <Section title="Waits for you" count={count > 0 ? count : undefined} size="lg" level={2}>
      {count === 0 ? (
        <EmptyState
          message={pending ? "Looking through your boards…" : "Nothing waits for you."}
          className="card-surface px-4 py-3.5"
        />
      ) : (
        <ul
          aria-label="Waits for you"
          className="card-surface divide-y divide-[var(--border-soft)] overflow-hidden"
        >
          {rows.map(({ board, loop, action }) => (
            <li key={loop.id} className="flex flex-wrap items-center gap-x-4 gap-y-2 px-4 py-3">
              <div className="min-w-0 flex-1">
                <p className="m-0 text-xs text-[var(--foreground-faint)]">{board.name}</p>
                <p className="m-0 flex flex-wrap items-baseline gap-x-2 text-[15px]">
                  <span className="font-semibold text-[var(--foreground)]">{loop.name}</span>
                  <span className="font-mono text-xs text-[var(--foreground-faint)]">
                    {loop.key}
                  </span>
                  {loop.without_plan ? <WithoutPlanChip /> : null}
                </p>
                <p className="m-0 text-sm text-[var(--muted-foreground)]">{action.waiting}</p>
              </div>
              <ButtonLink
                to={loopHref(board.id, loop.id, action.tab)}
                size="sm"
                variant="secondary"
                aria-label={`${action.label ?? "Open Loop"}: ${loop.name}`}
              >
                {action.label ?? "Open Loop"}
              </ButtonLink>
            </li>
          ))}
          {discussions.map((discussion) => (
            <li
              key={`${discussion.board_id}/${discussion.discussion_id}`}
              className="flex flex-wrap items-center gap-x-4 gap-y-2 px-4 py-3"
            >
              <div className="min-w-0 flex-1">
                <p className="m-0 text-xs text-[var(--foreground-faint)]">
                  {discussion.board_name}
                  {discussion.ticket_key ? (
                    <span className="font-mono"> · {discussion.ticket_key}</span>
                  ) : null}
                </p>
                <p className="m-0 text-[15px] font-semibold text-[var(--foreground)]">
                  {discussion.question}
                </p>
                <p className="m-0 text-sm text-[var(--muted-foreground)]">{WAITS_ON_DISCUSSION}</p>
              </div>
              <ButtonLink
                to={inboxPath(discussion)}
                size="sm"
                variant="secondary"
                aria-label={`Open discussion: ${discussion.question}`}
              >
                Open discussion
              </ButtonLink>
            </li>
          ))}
        </ul>
      )}
      {failed > 0 ? (
        <p className="mt-2 text-xs text-[var(--foreground-faint)]">
          {failed === 1 ? "1 board" : `${failed} boards`} could not be read; their Loops are not
          listed.
        </p>
      ) : null}
    </Section>
  );
}
