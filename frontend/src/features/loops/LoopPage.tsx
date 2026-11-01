import { useCallback, useMemo, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { useMutation, useQueries, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  DndContext,
  DragOverlay,
  KeyboardSensor,
  PointerSensor,
  closestCorners,
  useSensor,
  useSensors,
  type DragEndEvent,
  type DragStartEvent,
} from "@dnd-kit/core";
import { sortableKeyboardCoordinates } from "@dnd-kit/sortable";
import { ArrowLeft, Download, History, LayoutTemplate, Plus, Search } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent } from "@/components/ui/dialog";
import { Field, Input, Select, Textarea } from "@/components/ui/input";
import { useToast } from "@/components/ui/toast";
import { ApiError, api } from "@/lib/api";
import { keys, useBoard, useLists, useLoop } from "@/lib/queries";
import type { BoardList, Card, Priority } from "@/lib/types";
import { CardTile } from "@/features/board/CardTile";
import { ListColumn } from "@/features/board/ListColumn";
import { CardDialog } from "@/features/cards/CardDialog";
import { ActivityPanel } from "@/features/activity/ActivityPanel";
import { useLoopTools } from "@/webmcp/useWebMcp";
import { LoopHeader } from "./LoopHeader";

const LIST_LIMIT = 200;

export function LoopPage() {
  const { boardId = "", loopId = "" } = useParams();
  const queryClient = useQueryClient();
  const toast = useToast();
  const boardQuery = useBoard(boardId);
  const loopQuery = useLoop(boardId, loopId);
  const listsQuery = useLists(boardId, loopId);
  // A discussion or search result deep-links the Ticket it points at.
  const [searchParams, setSearchParams] = useSearchParams();
  const [selectedCardId, setSelectedCardId] = useState<string | null>(
    searchParams.get("card"),
  );
  const [retrying, setRetrying] = useState(false);
  const [showActivity, setShowActivity] = useState(false);
  const [addingList, setAddingList] = useState(false);
  const [listName, setListName] = useState("");
  const [activeCard, setActiveCard] = useState<Card | null>(null);
  const [templateOpen, setTemplateOpen] = useState(false);
  const [templateName, setTemplateName] = useState("");
  const [templateDescription, setTemplateDescription] = useState("");
  const [filters, setFilters] = useState<{ q: string; priority: "" | Priority; overdue: boolean }>({
    q: "",
    priority: "",
    overdue: false,
  });

  const lists = listsQuery.data ?? [];

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

  const filtersActive = Boolean(filters.q.trim() || filters.priority || filters.overdue);
  const searchQuery = useQuery({
    queryKey: keys.search(boardId, loopId, filters),
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
    queryClient.invalidateQueries({ queryKey: keys.lists(boardId, loopId) });
    queryClient.invalidateQueries({ queryKey: keys.loop(boardId, loopId) });
  }, [queryClient, boardId, loopId]);

  const invalidateCards = useCallback(() => {
    queryClient.invalidateQueries({ queryKey: keys.loopCardsPrefix(boardId, loopId) });
    queryClient.invalidateQueries({ queryKey: keys.readiness(boardId, loopId) });
    queryClient.invalidateQueries({ queryKey: keys.loop(boardId, loopId) });
    queryClient.invalidateQueries({ queryKey: keys.board(boardId) });
  }, [queryClient, boardId, loopId]);

  const createCardMutation = useMutation({
    mutationFn: ({ listId, title }: { listId: string; title: string }) =>
      api.createCard(boardId, loopId, { list_id: listId, title }),
    onSuccess: invalidateCards,
    onError: (error) =>
      toast.push({
        title: "Could not create ticket",
        description: error instanceof ApiError ? error.message : undefined,
        variant: "error",
      }),
  });

  const createListMutation = useMutation({
    mutationFn: (name: string) => api.createList(boardId, loopId, name),
    onSuccess: invalidateLists,
    onError: () => toast.push({ title: "Could not create column", variant: "error" }),
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
      queryClient.invalidateQueries({ queryKey: ["templates"] });
      toast.push({ title: "Template saved", variant: "success" });
    },
    onError: (error) =>
      toast.push({
        title: "Could not save template",
        description: error instanceof ApiError ? error.message : undefined,
        variant: "error",
      }),
  });

  const renameListMutation = useMutation({
    mutationFn: ({ listId, name }: { listId: string; name: string }) =>
      api.renameList(boardId, loopId, listId, name),
    onSuccess: invalidateLists,
  });

  const archiveListMutation = useMutation({
    mutationFn: (listId: string) => api.archiveList(boardId, loopId, listId),
    onSuccess: () => {
      invalidateLists();
      invalidateCards();
    },
  });

  const moveListMutation = useMutation({
    mutationFn: ({ listId, position }: { listId: string; position: number }) =>
      api.moveList(boardId, loopId, listId, position),
    onSuccess: invalidateLists,
    onError: () => {
      invalidateLists();
      toast.push({ title: "Could not reorder columns", variant: "error" });
    },
  });

  const moveCardMutation = useMutation({
    mutationFn: ({ card, listId, position }: { card: Card; listId: string; position: number }) =>
      api.moveCard(boardId, loopId, card.id, {
        version: card.version,
        list_id: listId,
        position,
      }),
    onSettled: invalidateCards,
    onError: (error) => {
      invalidateCards();
      toast.push({
        title: "Could not move ticket",
        description:
          error instanceof ApiError && error.code === "version_conflict"
            ? "The ticket changed elsewhere. The loop has been refreshed."
            : error instanceof ApiError
              ? error.message
              : undefined,
        variant: "error",
      });
    },
  });

  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 4 } }),
    useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates }),
  );

  function handleDragStart(event: DragStartEvent) {
    const data = event.active.data.current;
    if (data?.type === "card") {
      const card = Object.values(cardsByList)
        .flat()
        .find((item) => item.id === data.cardId);
      setActiveCard(card ?? null);
    }
  }

  function handleDragEnd(event: DragEndEvent) {
    setActiveCard(null);
    const activeData = event.active.data.current;
    const over = event.over;
    if (!over) return;

    if (activeData?.type === "list") {
      const fromIndex = lists.findIndex((list) => list.id === activeData.listId);
      const overId = over.data.current?.listId ?? over.id;
      const toIndex = lists.findIndex((list) => list.id === overId);
      if (fromIndex < 0 || toIndex < 0 || fromIndex === toIndex) return;
      moveListMutation.mutate({ listId: activeData.listId, position: toIndex });
      return;
    }

    if (activeData?.type !== "card") return;
    const cardId = String(activeData.cardId);
    const card = Object.values(cardsByList)
      .flat()
      .find((item) => item.id === cardId);
    if (!card) return;

    const overData = over.data.current as
      | { type?: string; listId?: string; cardId?: string }
      | undefined;
    const targetListId = overData?.listId;
    if (!targetListId) return;

    const targetCards = (cardsByList[targetListId] ?? []).filter((item) => item.id !== cardId);
    let index = targetCards.length;
    if (overData?.type === "card" && overData.cardId) {
      const overIndex = targetCards.findIndex((item) => item.id === overData.cardId);
      if (overIndex >= 0) index = overIndex;
    }

    const sourceCards = (cardsByList[card.list_id] ?? []).filter((item) => item.id !== cardId);

    queryClient.setQueryData<Card[]>(
      keys.listCards(boardId, loopId, card.list_id, LIST_LIMIT),
      sourceCards,
    );
    queryClient.setQueryData<Card[]>(
      keys.listCards(boardId, loopId, targetListId, LIST_LIMIT),
      () => {
        const next = [...targetCards];
        next.splice(index, 0, { ...card, list_id: targetListId });
        return next;
      },
    );

    moveCardMutation.mutate({ card, listId: targetListId, position: index });
  }

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
        {error instanceof ApiError ? error.message : "Loop unavailable."}
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

  return (
    <section className="flex h-[calc(100vh-7rem)] flex-col gap-3">
      <div className="flex flex-wrap items-center gap-2 text-xs text-[var(--muted-foreground)]">
        <Link to={`/boards/${board.id}`} className="inline-flex items-center gap-1 hover:underline">
          <ArrowLeft size={13} /> {board.name}
        </Link>
        <span aria-hidden>·</span>
        <Link
          to={`/boards/${board.id}/history`}
          className="inline-flex items-center gap-1 hover:underline"
        >
          <History size={13} /> History
        </Link>
        <span className="ml-auto flex flex-wrap items-center gap-2">
          <div className="relative">
            <Search
              size={14}
              className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-[var(--muted-foreground)]"
            />
            <Input
              className="h-8 w-44 pl-8"
              placeholder="Filter tickets"
              aria-label="Filter tickets"
              value={filters.q}
              onChange={(event) => setFilters((current) => ({ ...current, q: event.target.value }))}
            />
          </div>
          <Select
            aria-label="Filter by priority"
            className="h-8 w-auto"
            value={filters.priority}
            onChange={(event) =>
              setFilters((current) => ({
                ...current,
                priority: event.target.value as Priority | "",
              }))
            }
          >
            <option value="">Any priority</option>
            <option value="low">Low</option>
            <option value="medium">Medium</option>
            <option value="high">High</option>
            <option value="urgent">Urgent</option>
          </Select>
          <Button
            size="sm"
            variant={filters.overdue ? "primary" : "outline"}
            onClick={() => setFilters((current) => ({ ...current, overdue: !current.overdue }))}
            aria-pressed={filters.overdue}
          >
            Overdue
          </Button>
          <Button size="sm" variant="outline" onClick={() => setShowActivity((value) => !value)}>
            <History size={14} /> Activity
          </Button>
          <Button
            size="sm"
            variant="outline"
            disabled={readOnly}
            onClick={() => {
              setTemplateName(`${loop.name} template`);
              setTemplateDescription(board.description);
              setTemplateOpen(true);
            }}
          >
            <LayoutTemplate size={14} /> Save columns as template
          </Button>
          <a
            href={api.exportUrl(board.id)}
            className="inline-flex h-8 items-center gap-1.5 rounded-lg border border-[var(--border)] px-2.5 text-xs text-[var(--foreground)] hover:bg-[var(--surface-raised)]"
          >
            <Download size={14} /> Export board
          </a>
        </span>
      </div>

      <LoopHeader
        boardId={boardId}
        loop={loop}
        boardStatus={board.status}
        onChanged={() => {
          queryClient.invalidateQueries({ queryKey: keys.loop(boardId, loopId) });
          queryClient.invalidateQueries({ queryKey: keys.loopDocuments(boardId, loopId) });
          queryClient.invalidateQueries({ queryKey: keys.loopPlan(boardId, loopId) });
          queryClient.invalidateQueries({ queryKey: keys.readiness(boardId, loopId) });
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
            onClick={async () => {
              setRetrying(true);
              try {
                const report = await api.retryMigration(board.id);
                toast.push({ title: `Migration ${report.status}`, variant: "success" });
                queryClient.invalidateQueries();
              } catch (error) {
                toast.push({
                  title: "Migration failed",
                  description: error instanceof ApiError ? error.message : "See the server log.",
                  variant: "error",
                });
              } finally {
                setRetrying(false);
              }
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

      <div className="flex min-h-0 flex-1 gap-4">
        <DndContext
          sensors={sensors}
          collisionDetection={closestCorners}
          onDragStart={handleDragStart}
          onDragEnd={handleDragEnd}
          onDragCancel={() => setActiveCard(null)}
        >
          <div
            className="scrollbar-thin flex min-h-0 flex-1 items-start gap-3 overflow-x-auto pb-2"
            role="region"
            aria-label="Loop Kanban columns"
          >
            {lists.map((list: BoardList) => {
              const allCards = cardsByList[list.id] ?? [];
              const cards = matchingIds
                ? allCards.filter((card) => matchingIds.has(card.id))
                : allCards;
              return (
                <div key={list.id} className="h-full">
                  <ListColumn
                    list={list}
                    cards={cards}
                    onOpenCard={(card) => openCard(card.id)}
                    onCreateCard={async (title) => {
                      await createCardMutation.mutateAsync({ listId: list.id, title });
                    }}
                    onRename={(name) => renameListMutation.mutate({ listId: list.id, name })}
                    onArchive={() => archiveListMutation.mutate(list.id)}
                  />
                </div>
              );
            })}

            <div className="w-[260px] shrink-0">
              {addingList ? (
                <form
                  className="card-surface flex flex-col gap-2 p-3"
                  onSubmit={(event) => {
                    event.preventDefault();
                    if (!listName.trim()) return;
                    createListMutation.mutate(listName.trim());
                    setListName("");
                    setAddingList(false);
                  }}
                >
                  <Input
                    autoFocus
                    value={listName}
                    aria-label="New column name"
                    placeholder="Column name"
                    onChange={(event) => setListName(event.target.value)}
                    onKeyDown={(event) => {
                      if (event.key === "Escape") {
                        setAddingList(false);
                        setListName("");
                      }
                    }}
                  />
                  <div className="flex gap-1.5">
                    <Button size="sm" type="submit" disabled={!listName.trim()}>
                      Add column
                    </Button>
                    <Button size="sm" variant="ghost" onClick={() => setAddingList(false)}>
                      Cancel
                    </Button>
                  </div>
                </form>
              ) : (
                <Button
                  variant="secondary"
                  className="w-full justify-start"
                  onClick={() => setAddingList(true)}
                  disabled={readOnly}
                >
                  <Plus size={14} /> Add column
                </Button>
              )}
            </div>
          </div>
          <DragOverlay dropAnimation={null}>
            {activeCard ? <CardTile card={activeCard} overlay /> : null}
          </DragOverlay>
        </DndContext>
      </div>

      {showActivity ? (
        <ActivityPanel boardId={boardId} onClose={() => setShowActivity(false)} />
      ) : null}

      {selectedCardId ? (
        <CardDialog
          boardId={boardId}
          loopId={loopId}
          cardId={selectedCardId}
          lists={lists}
          onClose={closeCard}
          onConfirmHuman={async (version, note) => {
            await api.confirmHumanTicket(boardId, loopId, selectedCardId, { version, note });
            invalidateCards();
            queryClient.invalidateQueries({
              queryKey: keys.card(boardId, loopId, selectedCardId),
            });
          }}
        />
      ) : null}

      <Dialog open={templateOpen} onOpenChange={setTemplateOpen}>
        <DialogContent
          title="Save as template"
          description="Stores this Loop's column names and the board's labels for future Loops."
        >
          <form
            className="flex flex-col gap-3"
            onSubmit={(event) => {
              event.preventDefault();
              if (templateName.trim()) saveTemplateMutation.mutate();
            }}
          >
            <Field label="Template name" htmlFor="loop-template-name">
              <Input
                id="loop-template-name"
                value={templateName}
                onChange={(event) => setTemplateName(event.target.value)}
                required
                autoFocus
                maxLength={200}
              />
            </Field>
            <Field label="Description" htmlFor="loop-template-description">
              <Textarea
                id="loop-template-description"
                value={templateDescription}
                onChange={(event) => setTemplateDescription(event.target.value)}
                maxLength={20000}
              />
            </Field>
            <p className="text-[11px] text-[var(--muted-foreground)]">
              Captures {lists.length} columns. Tickets are not copied.
            </p>
            <div className="flex justify-end gap-2">
              <Button variant="ghost" onClick={() => setTemplateOpen(false)}>
                Cancel
              </Button>
              <Button
                type="submit"
                disabled={!templateName.trim() || saveTemplateMutation.isPending}
              >
                {saveTemplateMutation.isPending ? "Saving…" : "Save template"}
              </Button>
            </div>
          </form>
        </DialogContent>
      </Dialog>
    </section>
  );
}
