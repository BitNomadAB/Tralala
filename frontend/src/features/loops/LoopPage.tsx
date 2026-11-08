import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useCallback, useMemo, useState } from "react";
import { useParams } from "react-router-dom";
import { Tab, TabList, TabPanel, Tabs } from "@/components/ui/tabs";
import { useToast } from "@/components/ui/useToast";
import { ActivityPanel } from "@/features/activity/ActivityPanel";
import { TicketModal } from "@/features/cards/TicketModal";
import { api } from "@/lib/api";
import { describeError } from "@/lib/describeError";
import { keys, useBoard, useLists, useLoop, useLoopSummaries } from "@/lib/queries";
import { cn } from "@/lib/utils";
import { useLoopTools } from "@/webmcp/useWebMcp";
import { AddColumnForm } from "./AddColumnForm";
import { KanbanFilters } from "./KanbanFilters";
import { LoopHeader } from "./LoopHeader";
import { LoopKanban } from "./LoopKanban";
import { LoopNotesPanel } from "./LoopNotesPanel";
import { LoopNotices } from "./LoopNotices";
import { LoopPlanTab } from "./LoopPlanTab";
import { LoopToolbar } from "./LoopToolbar";
import { NO_FILTERS, useLoopCards, type TicketFilters } from "./useLoopCards";
import { parseTab, useLoopView } from "./useLoopView";
import { useTicketDialog } from "./useTicketDialog";

/**
 * The Loop page: the header with the person's next decision, then the tabs Kanban, Plan and Notes
 * (`?tab=`, the Kanban when absent). `?card=` opens a Ticket over whichever tab is shown, and
 * `?discussion=` one of its discussions in the same dialog.
 */
export function LoopPage() {
  const { boardId = "", loopId = "" } = useParams();
  const queryClient = useQueryClient();
  const toast = useToast();
  const boardQuery = useBoard(boardId);
  const loopQuery = useLoop(boardId, loopId);
  const listsQuery = useLists(boardId, loopId);
  const summaries = useLoopSummaries(boardId);
  const view = useLoopView(loopQuery.data?.stage ?? "draft");
  // A search result or a discussion deep-links the Ticket it points at.
  const dialog = useTicketDialog();
  const [showActivity, setShowActivity] = useState(false);
  const [addingList, setAddingList] = useState(false);
  const [listName, setListName] = useState("");
  const [filters, setFilters] = useState<TicketFilters>(NO_FILTERS);
  // A tab's content is mounted the first time it is shown and kept, so a run the Plan tab follows
  // or a draft of Info survives a look at the Kanban.
  const [seen, setSeen] = useState<ReadonlySet<string>>(() => new Set([view.tab]));
  if (!seen.has(view.tab)) setSeen(new Set([...seen, view.tab]));

  const lists = useMemo(() => listsQuery.data ?? [], [listsQuery.data]);
  const { cardsByList, ticketHref, matchingIds } = useLoopCards({
    boardId,
    loopId,
    lists,
    filters,
  });

  const invalidateLists = useCallback(() => {
    void queryClient.invalidateQueries({ queryKey: keys.lists(boardId, loopId) });
    void queryClient.invalidateQueries({ queryKey: keys.loop(boardId, loopId) });
  }, [queryClient, boardId, loopId]);

  const invalidateCards = useCallback(() => {
    void queryClient.invalidateQueries({ queryKey: keys.loopCardsPrefix(boardId, loopId) });
    void queryClient.invalidateQueries({ queryKey: keys.readiness(boardId, loopId) });
    void queryClient.invalidateQueries({ queryKey: keys.loop(boardId, loopId) });
    void queryClient.invalidateQueries({ queryKey: keys.loopSummaries(boardId) });
    void queryClient.invalidateQueries({ queryKey: keys.board(boardId) });
  }, [queryClient, boardId, loopId]);

  const onLoopChanged = useCallback(() => {
    void queryClient.invalidateQueries({ queryKey: keys.loopDocuments(boardId, loopId) });
    void queryClient.invalidateQueries({ queryKey: keys.loopPlan(boardId, loopId) });
    invalidateCards();
  }, [queryClient, boardId, loopId, invalidateCards]);

  const createListMutation = useMutation({
    mutationFn: (name: string) => api.createList(boardId, loopId, name),
    onSuccess: invalidateLists,
    onError: () => {
      toast.push({ title: "Could not create column", variant: "error" });
    },
  });

  useLoopTools({
    boardId,
    loopId,
    loopName: loopQuery.data?.name ?? "",
    lists,
    cardsByList,
    onOpenCard: dialog.openCard,
  });

  if (boardQuery.isLoading || loopQuery.isLoading) {
    return <p className="text-sm text-[var(--muted-foreground)]">Loading loop…</p>;
  }

  if (boardQuery.error || !boardQuery.data || loopQuery.error || !loopQuery.data) {
    const error = boardQuery.error ?? loopQuery.error;
    return (
      <p role="alert" className="text-sm text-[var(--destructive)]">
        {describeError(error, "Loop unavailable.")}
      </p>
    );
  }

  const board = boardQuery.data;
  const loop = loopQuery.data;
  const readOnly =
    board.status !== "active" ||
    loop.stage === "completed" ||
    loop.stage === "cancelled" ||
    loop.archived_at !== null;
  const kanban = view.tab === "kanban";

  return (
    <section
      className={cn(
        "flex flex-col gap-3",
        kanban ? "h-[calc(100vh-7rem)]" : "min-h-[calc(100vh-7rem)]",
      )}
    >
      <LoopToolbar board={board} />

      <LoopHeader
        board={board}
        loop={loop}
        summary={summaries.data?.loops.find((entry) => entry.id === loop.id)}
        view={view}
        readOnly={readOnly}
        columnCount={lists.length}
        onChanged={onLoopChanged}
        onToggleActivity={() => setShowActivity((value) => !value)}
      />

      <LoopNotices board={board} loop={loop} readOnly={readOnly} />

      <Tabs
        value={view.tab}
        onChange={(tab) => view.show(parseTab(tab))}
        className="flex min-h-0 flex-1 flex-col"
      >
        <TabList label="Loop views" className="mb-1">
          <Tab value="kanban">Kanban</Tab>
          <Tab value="plan">Plan</Tab>
          <Tab value="notes">Notes</Tab>
        </TabList>
        <TabPanel value="kanban" className="flex min-h-0 flex-1 flex-col gap-3">
          <KanbanFilters filters={filters} onFiltersChange={setFilters} />
          <LoopKanban
            boardId={boardId}
            loopId={loopId}
            lists={lists}
            cardsByList={cardsByList}
            matchingIds={matchingIds}
            readOnly={readOnly}
            onOpenCard={dialog.openCard}
            onListsChanged={invalidateLists}
            onCardsChanged={invalidateCards}
          >
            <AddColumnForm
              adding={addingList}
              onAddingChange={setAddingList}
              name={listName}
              onNameChange={setListName}
              readOnly={readOnly}
              onCreate={(name) => createListMutation.mutate(name)}
            />
          </LoopKanban>
        </TabPanel>
        <TabPanel value="plan" className="pt-2">
          {seen.has("plan") ? (
            <LoopPlanTab
              boardId={boardId}
              loop={loop}
              doc={view.doc}
              onDocChange={(doc) => view.show("plan", doc)}
              readOnly={readOnly}
              onChanged={onLoopChanged}
            />
          ) : null}
        </TabPanel>
        <TabPanel value="notes" className="pt-2">
          {seen.has("notes") ? (
            <LoopNotesPanel boardId={boardId} loop={loop} readOnly={readOnly} />
          ) : null}
        </TabPanel>
      </Tabs>

      {showActivity ? (
        <ActivityPanel boardId={boardId} onClose={() => setShowActivity(false)} />
      ) : null}

      {dialog.open ? (
        <TicketModal
          boardId={boardId}
          loopId={loopId}
          cardId={dialog.cardId}
          discussionId={dialog.discussionId}
          onClose={dialog.close}
          onBackToTicket={dialog.backToTicket}
          ticketHref={ticketHref}
        />
      ) : null}
    </section>
  );
}
