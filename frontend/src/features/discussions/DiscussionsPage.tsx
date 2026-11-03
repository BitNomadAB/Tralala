import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useState } from "react";
import { useToast } from "@/components/ui/useToast";
import { api } from "@/lib/api";
import { describeError } from "@/lib/describeError";
import { keys, useAgents } from "@/lib/queries";
import { DiscussionList } from "./DiscussionList";
import { DiscussionThread, type ReviewDecision } from "./DiscussionThread";
import { NewDiscussionDialog } from "./NewDiscussionDialog";
import { ReviewDiscussionDialog } from "./ReviewDiscussionDialog";
import { useDiscussionEvents } from "./useDiscussionEvents";

export function DiscussionsPage() {
  const queryClient = useQueryClient();
  const toast = useToast();
  const { data: agents = [] } = useAgents();
  const [boardId, setBoardId] = useState("");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [reply, setReply] = useState("");
  const [reviewing, setReviewing] = useState<null | { decision: ReviewDecision }>(null);

  const activeBoard = boardId;

  const boardsQuery = useQuery({
    queryKey: keys.discussionBoards,
    queryFn: () => api.listDiscussionBoards(),
    // Keep the ordering fresh while the board list is open; a selected board refreshes on demand.
    refetchInterval: activeBoard ? false : 30_000,
  });
  const boards = boardsQuery.data ?? [];
  const activeBoardEntry = boards.find((entry) => entry.board_id === activeBoard) ?? null;

  const invalidate = useCallback(() => {
    void queryClient.invalidateQueries({ queryKey: keys.discussions(activeBoard) });
    if (selectedId) {
      void queryClient.invalidateQueries({ queryKey: ["discussion", activeBoard, selectedId] });
    }
  }, [queryClient, activeBoard, selectedId]);

  const backToBoards = useCallback(() => {
    // The overview is one query for every board; refresh it when the list becomes visible instead
    // of on every thread event.
    void queryClient.invalidateQueries({ queryKey: keys.discussionBoards });
    setBoardId("");
    setSelectedId(null);
  }, [queryClient]);

  const live = useDiscussionEvents(activeBoard, selectedId, invalidate);

  const discussionsQuery = useQuery({
    queryKey: keys.discussions(activeBoard),
    queryFn: () => api.listDiscussions(activeBoard),
    enabled: Boolean(activeBoard),
  });
  const discussions = discussionsQuery.data ?? [];
  const detailQuery = useQuery({
    queryKey: ["discussion", activeBoard, selectedId],
    queryFn: () => api.getDiscussion(activeBoard, String(selectedId)),
    enabled: Boolean(activeBoard && selectedId),
    refetchInterval: (query) => (query.state.data?.run_state === "running" && !live ? 1500 : false),
  });

  const selected = detailQuery.data ?? discussions.find((item) => item.id === selectedId) ?? null;

  const replyMutation = useMutation({
    mutationFn: () =>
      api.postDiscussionMessage(activeBoard, String(selectedId), { content: reply.trim() }),
    onSuccess: (discussion) => {
      setReply("");
      invalidate();
      if (discussion.auto_run === "already_running") {
        toast.push({
          title: "A run is already active",
          description: "Your message is saved and joins the conversation; no second run starts.",
          variant: "info",
        });
      } else if (discussion.auto_run === "thread_closed") {
        toast.push({
          title: "The discussion is closed",
          description: "The message is saved, but a closed thread does not start a run.",
          variant: "warning",
        });
      } else if (discussion.auto_run === "no_participants") {
        toast.push({
          title: "No AI participants",
          description: "The message is saved; add participants before agents can answer.",
          variant: "warning",
        });
      }
    },
    onError: (error) => {
      toast.push({
        title: "Could not post message",
        description: describeError(error, undefined),
        variant: "error",
      });
    },
  });

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

        <div className="card-surface flex max-h-[70vh] min-h-[320px] flex-col p-4">
          {!activeBoard ? (
            <p className="m-auto text-sm text-[var(--muted-foreground)]">
              Select a board to see its most recently active discussions.
            </p>
          ) : !selected ? (
            <p className="m-auto text-sm text-[var(--muted-foreground)]">
              Select a discussion to read the thread.
            </p>
          ) : (
            <DiscussionThread
              boardId={activeBoard}
              discussion={selected}
              live={live}
              onReview={(decision) => setReviewing({ decision })}
              onChanged={invalidate}
              reply={reply}
              onReplyChange={setReply}
              sending={replyMutation.isPending}
              onSend={() => replyMutation.mutate()}
            />
          )}
        </div>
      </div>

      <ReviewDiscussionDialog
        boardId={activeBoard}
        discussionId={selectedId}
        decision={reviewing?.decision ?? null}
        onClose={() => setReviewing(null)}
        onReviewed={invalidate}
      />
    </section>
  );
}
