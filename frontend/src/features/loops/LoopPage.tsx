import { useMutation, useQueries, useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useMemo, useState } from "react";
import { useParams, useSearchParams } from "react-router-dom";
import { Button } from "@/components/ui/button";
import { useToast } from "@/components/ui/useToast";
import { ActivityPanel } from "@/features/activity/ActivityPanel";
import { TicketModal } from "@/features/cards/TicketModal";
import { api } from "@/lib/api";
import { describeError } from "@/lib/describeError";
import { keys, useBoard, useLists, useLoop } from "@/lib/queries";
import type { Card } from "@/lib/types";
import { useLoopTools } from "@/webmcp/useWebMcp";
import { AddColumnForm } from "./AddColumnForm";
import { LoopHeader } from "./LoopHeader";
import { LoopKanban } from "./LoopKanban";
import { LoopToolbar, type TicketFilters } from "./LoopToolbar";
import { LIST_LIMIT } from "./loopUi";
import { SaveTemplateDialog } from "./SaveTemplateDialog";
import { ticketHrefResolver } from "./ticketLinks";

export function LoopPage() {
  const { boardId = "", loopId = "" } = useParams();
  const queryClient = useQueryClient();
  const toast = useToast();
  const boardQuery = useBoard(boardId);
  const loopQuery = useLoop(boardId, loopId);
  const listsQuery = useLists(boardId, loopId);
  // A discussion or search result deep-links the Ticket it points at.
  const [searchParams, setSearchParams] = useSearchParams();
  const [selectedCardId, setSelectedCardId] = useState<string | null>(searchParams.get("card"));
  const [retrying, setRetrying] = useState(false);
  const [showActivity, setShowActivity] = useState(false);
  const [addingList, setAddingList] = useState(false);
  const [listName, setListName] = useState("");
  const [templateOpen, setTemplateOpen] = useState(false);
  const [templateName, setTemplateName] = useState("");
  const [templateDescription, setTemplateDescription] = useState("");
  const [filters, setFilters] = useState<TicketFilters>({
    q: "",
    priority: "",
    overdue: false,
  });

  const lists = useMemo(() => listsQuery.data ?? [], [listsQuery.data]);

  const openCard = useCallback((id: string) => setSelectedCardId(id), []);
  const closeCard = useCallback(() => {
    setSelectedCardId(null);
    if (searchParams.has("card")) {
      const next = new URLSearchParams(searchParams);
      next.delete("card");
      setSearchParams(next, { replace: true });
    }
  }, [searchParams, setSearchParams]);

  const cardQueries = useQueries({
    queries: lists.map((list) => ({
      queryKey: keys.listCards(boardId, loopId, list.id, LIST_LIMIT),
      queryFn: () => api.listCards(boardId, loopId, { list_id: list.id, limit: LIST_LIMIT }),
      enabled: Boolean(boardId && loopId),
    })),
  });

  const cardsByList = useMemo(() => {
    const map: Record<string, Card[]> = {};
    lists.forEach((list, index) => {
      map[list.id] = cardQueries[index]?.data ?? [];
    });
    return map;
  }, [lists, cardQueries]);

  // A Ticket key in a description links to that Ticket when this Loop has it; others stay text.
  const ticketHref = useMemo(
    () => ticketHrefResolver(boardId, loopId, Object.values(cardsByList).flat()),
    [boardId, loopId, cardsByList],
  );

  const filtersActive = Boolean(filters.q.trim() || filters.priority || filters.overdue);
  const searchQuery = useQuery({
    queryKey: keys.search(boardId, loopId, { ...filters }),
    queryFn: () =>
      api.searchCards(boardId, loopId, {
        q: filters.q.trim() || undefined,
        priority: filters.priority || undefined,
        overdue: filters.overdue || undefined,
        limit: 200,
      }),
    enabled: Boolean(boardId && loopId) && filtersActive,
  });

  const matchingIds = useMemo(() => {
    if (!filtersActive) return null;
    return new Set((searchQuery.data?.items ?? []).map((card) => card.id));
  }, [filtersActive, searchQuery.data]);

  const invalidateLists = useCallback(() => {
    void queryClient.invalidateQueries({ queryKey: keys.lists(boardId, loopId) });
    void queryClient.invalidateQueries({ queryKey: keys.loop(boardId, loopId) });
  }, [queryClient, boardId, loopId]);

  const invalidateCards = useCallback(() => {
    void queryClient.invalidateQueries({ queryKey: keys.loopCardsPrefix(boardId, loopId) });
    void queryClient.invalidateQueries({ queryKey: keys.readiness(boardId, loopId) });
    void queryClient.invalidateQueries({ queryKey: keys.loop(boardId, loopId) });
    void queryClient.invalidateQueries({ queryKey: keys.board(boardId) });
  }, [queryClient, boardId, loopId]);

  const createListMutation = useMutation({
    mutationFn: (name: string) => api.createList(boardId, loopId, name),
    onSuccess: invalidateLists,
    onError: () => {
      toast.push({ title: "Could not create column", variant: "error" });
    },
  });

  const saveTemplateMutation = useMutation({
    mutationFn: () =>
      api.saveBoardAsTemplate(boardId, loopId, {
        name: templateName.trim(),
        description: templateDescription,
      }),
    onSuccess: () => {
      setTemplateOpen(false);
      setTemplateName("");
      setTemplateDescription("");
      void queryClient.invalidateQueries({ queryKey: ["templates"] });
      toast.push({ title: "Template saved", variant: "success" });
    },
    onError: (error) => {
      toast.push({
        title: "Could not save template",
        description: describeError(error, undefined),
        variant: "error",
      });
    },
  });

  useLoopTools({
    boardId,
    loopId,
    loopName: loopQuery.data?.name ?? "",
    lists,
    cardsByList,
    onOpenCard: openCard,
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

  async function retryMigration() {
    setRetrying(true);
    try {
      const report = await api.retryMigration(board.id);
      toast.push({ title: `Migration ${report.status}`, variant: "success" });
      void queryClient.invalidateQueries();
    } catch (error) {
      toast.push({
        title: "Migration failed",
        description: describeError(error, "See the server log."),
        variant: "error",
      });
    } finally {
      setRetrying(false);
    }
  }

  return (
    <section className="flex h-[calc(100vh-7rem)] flex-col gap-3">
      <LoopToolbar
        board={board}
        filters={filters}
        onFiltersChange={setFilters}
        onToggleActivity={() => setShowActivity((value) => !value)}
        readOnly={readOnly}
        onSaveTemplate={() => {
          setTemplateName(`${loop.name} template`);
          setTemplateDescription(board.description);
          setTemplateOpen(true);
        }}
      />

      <LoopHeader
        boardId={boardId}
        loop={loop}
        boardStatus={board.status}
        onChanged={() => {
          void queryClient.invalidateQueries({ queryKey: keys.loop(boardId, loopId) });
          void queryClient.invalidateQueries({ queryKey: keys.loopDocuments(boardId, loopId) });
          void queryClient.invalidateQueries({ queryKey: keys.loopPlan(boardId, loopId) });
          void queryClient.invalidateQueries({ queryKey: keys.readiness(boardId, loopId) });
          invalidateCards();
        }}
      />

      {board.status === "migration_failed" ? (
        <div className="flex flex-wrap items-center gap-3 rounded-lg border border-[var(--warning)] p-2 text-xs text-[var(--warning)]">
          <span>This board needs an explicit development reset before it can be used.</span>
          <Button
            size="sm"
            variant="outline"
            disabled={retrying}
            onClick={() => {
              void retryMigration();
            }}
          >
            {retrying ? "Migrating…" : "Retry migration"}
          </Button>
        </div>
      ) : null}

      {readOnly ? (
        <div className="flex flex-wrap items-center gap-3 rounded-lg border border-[var(--warning)] p-2 text-xs text-[var(--warning)]">
          Read-only: this Loop is {loop.stage}
          {loop.stage === "completed" ? " and its history snapshot is immutable." : "."}
        </div>
      ) : null}

      <LoopKanban
        boardId={boardId}
        loopId={loopId}
        lists={lists}
        cardsByList={cardsByList}
        matchingIds={matchingIds}
        onOpenCard={openCard}
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

      {showActivity ? (
        <ActivityPanel boardId={boardId} onClose={() => setShowActivity(false)} />
      ) : null}

      {selectedCardId ? (
        <TicketModal
          boardId={boardId}
          loopId={loopId}
          cardId={selectedCardId}
          onClose={closeCard}
          ticketHref={ticketHref}
        />
      ) : null}

      <SaveTemplateDialog
        open={templateOpen}
        onOpenChange={setTemplateOpen}
        name={templateName}
        onNameChange={setTemplateName}
        description={templateDescription}
        onDescriptionChange={setTemplateDescription}
        columnCount={lists.length}
        saving={saveTemplateMutation.isPending}
        onSave={() => saveTemplateMutation.mutate()}
      />
    </section>
  );
}
