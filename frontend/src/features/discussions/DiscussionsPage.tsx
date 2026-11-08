import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useState } from "react";
import { api } from "@/lib/api";
import { keys, useAgents } from "@/lib/queries";
import { DiscussionList } from "./DiscussionList";
import { DiscussionView } from "./DiscussionView";
import { NewDiscussionDialog } from "./NewDiscussionDialog";

/**
 * The Discussions page: the boards with discussions, a board's threads, and the selected thread in
 * the same view a Ticket shows it in. The view follows the thread's events and refreshes the list.
 */
export function DiscussionsPage() {
  const queryClient = useQueryClient();
  const { data: agents = [] } = useAgents();
  const [boardId, setBoardId] = useState("");
  const [selectedId, setSelectedId] = useState<string | null>(null);

  const activeBoard = boardId;

  const boardsQuery = useQuery({
    queryKey: keys.discussionBoards,
    queryFn: () => api.listDiscussionBoards(),
    // Keep the ordering fresh while the board list is open; a selected board refreshes on demand.
    refetchInterval: activeBoard ? false : 30_000,
  });
  const boards = boardsQuery.data ?? [];
  const activeBoardEntry = boards.find((entry) => entry.board_id === activeBoard) ?? null;

  const backToBoards = useCallback(() => {
    // The overview is one query for every board; refresh it when the list becomes visible instead
    // of on every thread event.
    void queryClient.invalidateQueries({ queryKey: keys.discussionBoards });
    setBoardId("");
    setSelectedId(null);
  }, [queryClient]);

  const discussionsQuery = useQuery({
    queryKey: keys.discussions(activeBoard),
    queryFn: () => api.listDiscussions(activeBoard),
    enabled: Boolean(activeBoard),
  });
  const discussions = discussionsQuery.data ?? [];

  return (
    <section className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center gap-2">
        <div>
          <h1 className="text-xl font-semibold">Discussions</h1>
          <p className="text-xs text-[var(--muted-foreground)]">
            Ticket-bound threads with human and AI participants. Discussion never executes changes.
          </p>
        </div>
        <div className="ml-auto flex flex-wrap items-center gap-2">
          <NewDiscussionDialog
            activeBoardId={activeBoard}
            boards={boards}
            agents={agents}
            onCreated={(target, discussionId) => {
              setBoardId(target);
              setSelectedId(discussionId);
            }}
          />
        </div>
      </div>

      <div className="grid min-h-0 gap-4 lg:grid-cols-[minmax(280px,360px)_1fr]">
        <DiscussionList
          activeBoardId={activeBoard}
          activeBoardName={activeBoardEntry?.board_name}
          boards={boards}
          boardsLoading={boardsQuery.isLoading}
          discussions={discussions}
          discussionsLoading={discussionsQuery.isLoading}
          selectedId={selectedId}
          onSelectDiscussion={setSelectedId}
          onOpenBoard={(target) => {
            setBoardId(target);
            setSelectedId(null);
          }}
          onBack={backToBoards}
        />

        <div className="card-surface flex min-h-[320px] min-w-0 flex-col">
          {!activeBoard ? (
            <p className="m-auto text-sm text-[var(--muted-foreground)]">
              Select a board to see its most recently active discussions.
            </p>
          ) : !selectedId ? (
            <p className="m-auto text-sm text-[var(--muted-foreground)]">
              Select a discussion to read the thread.
            </p>
          ) : (
            <DiscussionView
              key={selectedId}
              boardId={activeBoard}
              discussionId={selectedId}
              host="inline"
            />
          )}
        </div>
      </div>
    </section>
  );
}
