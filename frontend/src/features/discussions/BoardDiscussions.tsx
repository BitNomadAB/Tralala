import { Plus } from "lucide-react";
import { useId } from "react";
import { useNavigate } from "react-router-dom";
import { Button } from "@/components/ui/button";
import { EmptyState } from "@/components/ui/empty-state";
import { Section } from "@/components/ui/section";
import { Segmented, SegmentedPanel } from "@/components/ui/segmented";
import { describeError } from "@/lib/describeError";
import type { Discussion } from "@/lib/types";
import {
  BOARD_DISCUSSION_FILTERS,
  boardDiscussionAside,
  boardDiscussionMark,
  boardDiscussionMeta,
  noBoardDiscussion,
  type BoardDiscussionFilter,
} from "./boardDiscussionRules";
import { DiscussionRows, type DiscussionRowItem } from "./DiscussionRows";
import { boardDiscussionPath } from "./discussionRules";
import { NewDiscussionDialog } from "./NewDiscussionDialog";
import { useBoardDiscussions } from "./useBoardDiscussions";

function item(discussion: Discussion): DiscussionRowItem {
  return {
    id: discussion.id,
    mark: boardDiscussionMark(discussion),
    question: discussion.title,
    aside: boardDiscussionAside(discussion),
    meta: boardDiscussionMeta(discussion),
    unread: discussion.unread,
  };
}

/** The rows under one filter, or what is said while there are none. */
function FilterRows({
  boardId,
  filter,
  readOnly,
  state,
}: {
  boardId: string;
  filter: BoardDiscussionFilter;
  readOnly: boolean;
  state: ReturnType<typeof useBoardDiscussions>["query"];
}) {
  if (state.isLoading) {
    return <p className="m-0 text-sm text-[var(--muted-foreground)]">Reading the discussions…</p>;
  }
  if (state.error) {
    return (
      <p role="alert" className="m-0 text-sm text-[var(--destructive)]">
        {describeError(state.error, "Could not read the discussions.")}
      </p>
    );
  }
  const rows = (state.data ?? []).map(item);
  if (rows.length === 0) {
    return (
      <EmptyState
        className="card-surface px-4 py-3.5"
        message={noBoardDiscussion(filter, readOnly)}
      />
    );
  }
  return (
    <DiscussionRows
      rows={rows}
      label={filter === "open" ? "Open discussions" : "Closed discussions"}
      hrefFor={(row) => boardDiscussionPath(boardId, row.id)}
    />
  );
}

/**
 * The board's own discussions, the ones on no Ticket, beside its Loops: open or closed under the
 * filter, newest activity first, each row marked when something in it is new for the reader and
 * opening the discussion's page. "New discussion" starts one; an archived board's list can be
 * read, but nothing started.
 */
export function BoardDiscussions({ boardId, readOnly }: { boardId: string; readOnly: boolean }) {
  const navigate = useNavigate();
  const idBase = useId();
  const board = useBoardDiscussions(boardId);
  return (
    <Section
      title="Discussions"
      level={2}
      trailing={
        <div className="flex flex-wrap items-center gap-2">
          <Segmented
            label="Show discussions"
            value={board.filter}
            options={BOARD_DISCUSSION_FILTERS}
            onChange={board.setFilter}
            idBase={idBase}
          />
          {readOnly ? null : (
            <Button size="sm" variant="secondary" onClick={() => board.setCreating(true)}>
              <Plus size={15} aria-hidden="true" /> New discussion
            </Button>
          )}
        </div>
      }
    >
      {BOARD_DISCUSSION_FILTERS.map(({ value }) => (
        <SegmentedPanel key={value} idBase={idBase} value={value} active={board.filter}>
          {value === board.filter ? (
            <FilterRows boardId={boardId} filter={value} readOnly={readOnly} state={board.query} />
          ) : null}
        </SegmentedPanel>
      ))}
      {readOnly ? null : (
        <NewDiscussionDialog
          key={board.creating ? "open" : "closed"}
          open={board.creating}
          boardId={boardId}
          onClose={() => board.setCreating(false)}
          onCreated={(id) => {
            board.setCreating(false);
            void navigate(boardDiscussionPath(boardId, id));
          }}
        />
      )}
    </Section>
  );
}
