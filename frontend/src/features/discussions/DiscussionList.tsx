import { ChevronLeft, MessagesSquare } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import type { Discussion, DiscussionBoard } from "@/lib/types";
import { formatDateTime } from "@/lib/utils";

/** The left column: every board by discussion activity, or the open board's threads. */
export function DiscussionList({
  activeBoardId,
  activeBoardName,
  boards,
  boardsLoading,
  discussions,
  discussionsLoading,
  selectedId,
  onSelectDiscussion,
  onOpenBoard,
  onBack,
}: {
  activeBoardId: string;
  activeBoardName: string | undefined;
  boards: DiscussionBoard[];
  boardsLoading: boolean;
  discussions: Discussion[];
  discussionsLoading: boolean;
  selectedId: string | null;
  onSelectDiscussion: (discussionId: string) => void;
  onOpenBoard: (boardId: string) => void;
  onBack: () => void;
}) {
  return (
    <div className="card-surface max-h-[70vh] overflow-y-auto p-2">
      {activeBoardId ? (
        <>
          <div className="flex items-center gap-1.5 border-b border-[var(--border)] px-1 pb-2">
            <Button size="sm" variant="ghost" onClick={onBack}>
              <ChevronLeft size={14} /> All boards
            </Button>
            <span className="truncate text-xs font-semibold">{activeBoardName ?? "Board"}</span>
          </div>
          {discussionsLoading ? (
            <p className="p-3 text-xs text-[var(--muted-foreground)]">Loading discussions…</p>
          ) : discussions.length === 0 ? (
            <p className="p-3 text-xs text-[var(--muted-foreground)]">
              No discussions yet. Reference an existing ticket to start one.
            </p>
          ) : (
            <ul className="flex flex-col gap-1 pt-1">
              {discussions.map((discussion) => (
                <li key={discussion.id}>
                  <button
                    type="button"
                    onClick={() => onSelectDiscussion(discussion.id)}
                    className={`w-full rounded-lg p-2.5 text-left hover:bg-[var(--surface-raised)] ${
                      selectedId === discussion.id ? "bg-[var(--surface-raised)]" : ""
                    }`}
                  >
                    <p className="flex items-center gap-1.5 text-sm font-medium">
                      <MessagesSquare size={14} className="text-[var(--muted-foreground)]" />
                      <span className="truncate">{discussion.title}</span>
                    </p>
                    <p className="mt-0.5 truncate text-[11px] text-[var(--muted-foreground)]">
                      {discussion.card_title ?? discussion.card_id}
                      {discussion.loop_name ? ` · ${discussion.loop_name}` : ""} ·{" "}
                      {discussion.message_count} messages · {discussion.participant_count} agents
                    </p>
                    <p className="mt-1 flex items-center gap-1.5 text-[11px] text-[var(--muted-foreground)]">
                      <Badge tone={discussion.status === "open" ? "neutral" : "brand"}>
                        {discussion.status}
                      </Badge>
                      {formatDateTime(discussion.last_activity_at)}
                    </p>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </>
      ) : boardsLoading ? (
        <p className="p-3 text-xs text-[var(--muted-foreground)]">Loading boards…</p>
      ) : boards.length === 0 ? (
        <p className="p-3 text-xs text-[var(--muted-foreground)]">
          No boards yet. Create a board to start a discussion.
        </p>
      ) : (
        <>
          <p className="px-2 pb-2 pt-1 text-[11px] text-[var(--muted-foreground)]">
            Boards by newest discussion activity.
          </p>
          <ul aria-label="Boards with discussions" className="flex flex-col gap-1">
            {boards.map((entry) => (
              <li key={entry.board_id}>
                <button
                  type="button"
                  aria-label={`Open discussions for ${entry.board_name}`}
                  onClick={() => onOpenBoard(entry.board_id)}
                  className="w-full rounded-lg p-2.5 text-left hover:bg-[var(--surface-raised)]"
                >
                  <p className="flex items-center gap-1.5 text-sm font-medium">
                    <MessagesSquare size={14} className="text-[var(--muted-foreground)]" />
                    <span className="truncate">{entry.board_name}</span>
                    {entry.status !== "active" ? (
                      <Badge tone="warning">{entry.status}</Badge>
                    ) : null}
                  </p>
                  <p className="mt-0.5 text-[11px] text-[var(--muted-foreground)]">
                    {entry.discussion_count === 0
                      ? "No discussions yet"
                      : `${entry.discussion_count} discussion${
                          entry.discussion_count === 1 ? "" : "s"
                        } · ${entry.open_count} open`}
                  </p>
                  <p className="mt-0.5 text-[11px] text-[var(--muted-foreground)]">
                    {entry.last_activity_at
                      ? `Last activity ${formatDateTime(entry.last_activity_at)}`
                      : "Waiting for the first thread"}
                  </p>
                </button>
              </li>
            ))}
          </ul>
        </>
      )}
    </div>
  );
}
