import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Archive, CircleCheck } from "lucide-react";
import { useCallback, useMemo, useState } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent } from "@/components/ui/dialog";
import { useToast } from "@/components/ui/useToast";
import { useCardEvents } from "@/features/cards/useCardEvents";
import { ApiError, api } from "@/lib/api";
import { describeError } from "@/lib/describeError";
import type { MarkdownOptions } from "@/lib/markdown";
import { keys, useActivity, useLabels } from "@/lib/queries";
import type { BoardList } from "@/lib/types";
import { formatDateTime, fromDateInputValue, toDateInputValue } from "@/lib/utils";
import { useCardTools } from "@/webmcp/useWebMcp";
import { CardChecklists } from "./CardChecklists";
import { CardComments } from "./CardComments";
import { CardDialogForm, type CardDraft } from "./CardDialogForm";
import { CardHistory } from "./CardHistory";
import { CardSummaryNote } from "./CardSummaryNote";
import { CardTicketSummary } from "./CardTicketSummary";
import { CardWorkSection } from "./CardWorkSection";
import { useCardChecklists } from "./useCardChecklists";
import { useCardComments } from "./useCardComments";

export function CardDialog({
  boardId,
  loopId,
  cardId,
  lists,
  onClose,
  onConfirmHuman,
  ticketHref,
}: {
  boardId: string;
  loopId: string;
  cardId: string;
  lists: BoardList[];
  onClose: () => void;
  onConfirmHuman?: (version: number, note: string) => Promise<void>;
  /** Links a Ticket key in the description to that Ticket; the page knows which exist. */
  ticketHref?: MarkdownOptions["ticketHref"];
}) {
  const queryClient = useQueryClient();
  const toast = useToast();
  const {
    data: card,
    isLoading,
    error,
  } = useQuery({
    queryKey: keys.card(boardId, loopId, cardId),
    queryFn: () => api.getCard(boardId, loopId, cardId),
  });
  const labelsQuery = useLabels(boardId);
  const activityQuery = useActivity(boardId, cardId);
  const [draft, setDraft] = useState<CardDraft | null>(null);
  const [preview, setPreview] = useState(false);

  // The draft starts from the card once it has loaded; set while rendering, not in an effect.
  if (card && !draft) {
    setDraft({
      title: card.title,
      description: card.description,
      priority: card.priority,
      due: toDateInputValue(card.due_at),
      labels: card.labels.map((label) => label.id),
    });
  }

  const refresh = useCallback(() => {
    void queryClient.invalidateQueries({ queryKey: keys.card(boardId, loopId, cardId) });
    void queryClient.invalidateQueries({ queryKey: keys.loopCardsPrefix(boardId, loopId) });
    void queryClient.invalidateQueries({ queryKey: keys.activity(boardId, cardId) });
    void queryClient.invalidateQueries({ queryKey: keys.activity(boardId) });
    void queryClient.invalidateQueries({ queryKey: keys.mentions(boardId, loopId, cardId) });
  }, [queryClient, boardId, loopId, cardId]);

  const live = useCardEvents(boardId, loopId, cardId, refresh);

  const onError = (mutationError: unknown) => {
    toast.push({
      title: "Change rejected",
      description:
        mutationError instanceof ApiError && mutationError.code === "version_conflict"
          ? "Someone else updated this card. Reload to see the latest version."
          : describeError(mutationError, undefined),
      variant: "error",
    });
    refresh();
  };

  const updateMutation = useMutation({
    mutationFn: (payload: Parameters<typeof api.updateCard>[3]) =>
      api.updateCard(boardId, loopId, cardId, payload),
    onSuccess: refresh,
    onError,
  });

  const moveMutation = useMutation({
    mutationFn: (listId: string) =>
      api.moveCard(boardId, loopId, cardId, {
        version: card?.version ?? 1,
        list_id: listId,
        position: 10_000,
      }),
    onSuccess: refresh,
    onError,
  });

  const archiveMutation = useMutation({
    mutationFn: () => api.archiveCard(boardId, loopId, cardId),
    onSuccess: () => {
      refresh();
      onClose();
      toast.push({ title: "Card archived", variant: "success" });
    },
    onError,
  });

  const checklists = useCardChecklists({ boardId, loopId, cardId, refresh, onError });
  const comments = useCardComments({ boardId, loopId, cardId, refresh, onError });

  useCardTools({
    boardId,
    loopId,
    cardId,
    onOpen: () => undefined,
    onClose,
  });

  const labelOptions = useMemo(() => labelsQuery.data ?? [], [labelsQuery.data]);

  const dirty =
    draft && card
      ? draft.title !== card.title ||
        draft.description !== card.description ||
        draft.priority !== card.priority ||
        draft.due !== toDateInputValue(card.due_at) ||
        draft.labels.slice().sort().join() !==
          card.labels
            .map((l) => l.id)
            .sort()
            .join()
      : false;

  function save() {
    if (!draft || !card) return;
    updateMutation.mutate({
      version: card.version,
      title: draft.title.trim(),
      description: draft.description,
      priority: draft.priority,
      due_at: draft.due ? (fromDateInputValue(draft.due) ?? undefined) : undefined,
      clear_due_at: draft.due === "",
      labels: draft.labels,
    });
  }

  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent
        title={card?.title ?? "Card"}
        description={
          card ? `Updated ${formatDateTime(card.updated_at)} · version ${card.version}` : undefined
        }
        className="w-[min(760px,96vw)]"
      >
        {isLoading || !draft ? (
          <p className="text-sm text-[var(--muted-foreground)]">Loading card…</p>
        ) : error || !card ? (
          <p role="alert" className="text-sm text-[var(--destructive)]">
            {describeError(error, "Card unavailable.")}
          </p>
        ) : (
          <div className="flex flex-col gap-4">
            <CardSummaryNote card={card} />
            <CardTicketSummary card={card} />
            <CardWorkSection boardId={boardId} loopId={loopId} card={card} onChanged={refresh} />
            <CardDialogForm
              draft={draft}
              onDraftChange={setDraft}
              preview={preview}
              onPreviewChange={setPreview}
              lists={lists}
              listId={card.list_id}
              onMove={(listId) => moveMutation.mutate(listId)}
              labelOptions={labelOptions}
              ticketHref={ticketHref}
            />

            <div className="flex flex-wrap items-center gap-2 border-y border-[var(--border)] py-3">
              <Button
                variant="secondary"
                size="sm"
                onClick={save}
                disabled={!dirty || updateMutation.isPending}
              >
                {updateMutation.isPending ? "Saving…" : "Save changes"}
              </Button>
              <Button
                variant="outline"
                size="sm"
                disabled={
                  !card.completed_at &&
                  ((card.kind !== "manual" && !card.ready) || card.waiting_for !== "nothing")
                }
                title={
                  !card.completed_at && card.waiting_for !== "nothing"
                    ? "Clear the wait first"
                    : !card.completed_at && card.blockers.length > 0
                      ? `Blocked by ${card.blockers
                          .map((blocker) => blocker.key ?? blocker.title ?? blocker.reason)
                          .join(", ")}`
                      : undefined
                }
                onClick={() => {
                  if (!card.completed_at && card.human_action_required && onConfirmHuman) {
                    void onConfirmHuman(card.version, "").then(onClose, onError);
                    return;
                  }
                  updateMutation.mutate({ version: card.version, completed: !card.completed_at });
                }}
              >
                <CircleCheck size={14} />
                {card.completed_at
                  ? "Mark incomplete"
                  : card.human_action_required
                    ? "Confirm human action"
                    : "Mark complete"}
              </Button>
              <Button variant="outline" size="sm" onClick={() => archiveMutation.mutate()}>
                <Archive size={14} /> Archive
              </Button>
              {card.completed_at ? (
                <Badge tone="success">Completed {formatDateTime(card.completed_at)}</Badge>
              ) : null}
            </div>

            <CardChecklists
              checklists={card.checklists ?? []}
              checklistTitle={checklists.checklistTitle}
              onChecklistTitleChange={checklists.setChecklistTitle}
              onAddChecklist={checklists.addChecklist}
              itemText={checklists.itemText}
              onItemTextChange={checklists.changeItemText}
              onAddItem={checklists.addItem}
              onToggleItem={checklists.toggleItem}
            />

            <CardComments
              live={live}
              mentions={comments.mentions}
              retrying={comments.retryMention.isPending}
              onRetryMention={(jobId) => comments.retryMention.mutate(jobId)}
              comments={card.comments ?? []}
              comment={comments.comment}
              onCommentChange={comments.changeComment}
              onCommentBlur={comments.closeSuggestions}
              suggestions={comments.suggestions}
              mentionIndex={comments.mentionIndex}
              onMentionIndexChange={comments.setMentionIndex}
              onChooseAgent={comments.chooseAgent}
              commentField={comments.commentField}
              onSubmitComment={(content) => comments.addComment.mutate(content)}
            />

            <CardHistory entries={activityQuery.data ?? []} />
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}
