import { useNavigate } from "react-router-dom";
import { Button } from "@/components/ui/button";
import { EmptyState } from "@/components/ui/empty-state";
import { Section } from "@/components/ui/section";
import { loopHref } from "@/features/loops/loopNextAction";
import type { WaitingRow } from "./boardSummaries";

/**
 * What waits for the person, first: one row per Loop, across their boards, whose next step is a
 * decision only a person makes. Each row names the board and the Loop, says what it waits for and
 * offers the button that opens the Loop page where the decision is made. Rows appear as each
 * board answers; `pending` says some have not answered yet.
 */
export function WaitsForYou({
  rows,
  pending,
  failed,
}: {
  rows: readonly WaitingRow[];
  pending: boolean;
  failed: number;
}) {
  const navigate = useNavigate();
  return (
    <Section
      title="Waits for you"
      count={rows.length > 0 ? rows.length : undefined}
      size="lg"
      level={2}
    >
      {rows.length === 0 ? (
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
                </p>
                <p className="m-0 text-sm text-[var(--muted-foreground)]">{action.waiting}</p>
              </div>
              <Button
                size="sm"
                variant="secondary"
                aria-label={`${action.label ?? "Open Loop"}: ${loop.name}`}
                onClick={() => {
                  void navigate(loopHref(board.id, loop.id, action.tab));
                }}
              >
                {action.label ?? "Open Loop"}
              </Button>
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
