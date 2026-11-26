import { Link } from "react-router-dom";
import { loopHref } from "./loopNextAction";
import { unansweredLine } from "./pocDecisions";

const LINK =
  "rounded text-[var(--primary)] hover:underline focus-visible:outline-2 focus-visible:outline-[var(--ring)]";

/**
 * The line the dialogs that close a Loop show while POC decisions are not answered: how many, that
 * they cannot be answered once the Loop is closed, and a link to the Decisions tab, which closes the
 * dialog (`onLeave`). It holds nothing up.
 */
export function PocUnanswered({
  boardId,
  loopId,
  open,
  onLeave,
}: {
  boardId: string;
  loopId: string;
  /** The Loop's open POC decisions. */
  open: number;
  onLeave: () => void;
}) {
  if (open === 0) return null;
  return (
    <p className="m-0 text-sm text-[var(--warning)]">
      {unansweredLine(open)}{" "}
      <Link className={LINK} to={loopHref(boardId, loopId, "decisions")} onClick={onLeave}>
        Open the Decisions tab
      </Link>
    </p>
  );
}
