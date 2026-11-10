import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Plus, Search, Upload } from "lucide-react";
import { useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Button } from "@/components/ui/button";
import { EmptyState } from "@/components/ui/empty-state";
import { Input, Select } from "@/components/ui/input";
import { Menu } from "@/components/ui/menu";
import { Section, SectionHeader } from "@/components/ui/section";
import { useToast } from "@/components/ui/useToast";
import { api } from "@/lib/api";
import { describeError } from "@/lib/describeError";
import { useBoards, useDiscussionInbox } from "@/lib/queries";
import type { Board } from "@/lib/types";
import { useDashboardTools } from "@/webmcp/useWebMcp";
import { BoardGrid } from "./BoardGrid";
import { groupBoards, useBoardSummaries, waitingRows } from "./boardSummaries";
import { DeleteBoardDialog } from "./DeleteBoardDialog";
import { NewBoardDialog } from "./NewBoardDialog";
import { useBoardLifecycle } from "./useBoardLifecycle";
import { WaitsForYou } from "./WaitsForYou";

/** The boards every request for "Waits for you" starts from: all of them, recent first. */
const ALL_BOARDS = { sort: "updated_at", order: "desc" } as const;

export function DashboardPage() {
  useDashboardTools();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const toast = useToast();
  const [query, setQuery] = useState("");
  const [status, setStatus] = useState("");
  const [sort, setSort] = useState("updated_at");
  const [creating, setCreating] = useState(false);
  const importInput = useRef<HTMLInputElement>(null);
  const lifecycle = useBoardLifecycle();

  const filters = useMemo(
    () => ({ q: query || undefined, status: status || undefined, sort, order: "desc" }),
    [query, status, sort],
  );
  const { data, isLoading, error } = useBoards(filters);
  // Unfiltered, so searching the tiles never hides what waits; with no filter set it is the same
  // query as the tiles', so the dashboard asks for its boards once.
  const everyBoard = useBoards(ALL_BOARDS);
  const boards = data?.items ?? [];
  const { inUse, readOnly } = groupBoards(boards);
  const allBoards = everyBoard.data?.items ?? [];
  const summaries = useBoardSummaries([...allBoards, ...boards]);
  const rows = waitingRows(allBoards, summaries);
  const inbox = useDiscussionInbox();
  const decisions = (inbox.data?.items ?? []).filter((row) => row.waits_for === "your_decision");
  const states = allBoards.flatMap((board) => {
    const entry = summaries.get(board.id);
    return board.status === "active" && entry ? [entry] : [];
  });

  const tiles = {
    summaries,
    onOpen: (board: Board) => {
      void navigate(`/boards/${board.id}`);
    },
    onLifecycle: lifecycle.run,
    onDelete: lifecycle.askDelete,
  };

  const importMutation = useMutation({
    mutationFn: (file: File) => api.importBoard(file),
    onSuccess: (board) => {
      void queryClient.invalidateQueries({ queryKey: ["boards"] });
      toast.push({ title: "Board imported", variant: "success" });
      void navigate(`/boards/${board.id}`);
    },
    onError: (mutationError) => {
      toast.push({
        title: "Import failed",
        description: describeError(mutationError, undefined),
        variant: "error",
      });
    },
  });

  return (
    <section className="flex flex-col gap-8">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-2xl font-semibold tracking-tight">Boards</h1>
        <div className="flex items-center gap-1.5">
          <input
            ref={importInput}
            type="file"
            accept="application/zip"
            className="sr-only"
            aria-label="Import board archive"
            onChange={(event) => {
              const file = event.target.files?.[0];
              if (file) importMutation.mutate(file);
              event.target.value = "";
            }}
          />
          <Menu
            label="More dashboard actions"
            items={[
              {
                label: "Import a board",
                icon: <Upload size={14} />,
                onSelect: () => importInput.current?.click(),
              },
            ]}
          />
          <Button onClick={() => setCreating(true)}>
            <Plus size={15} /> New board
          </Button>
        </div>
      </div>

      <WaitsForYou
        rows={rows}
        discussions={decisions}
        pending={everyBoard.isLoading || inbox.isLoading || states.some((entry) => entry.pending)}
        failed={states.filter((entry) => entry.failed).length}
      />

      <section aria-labelledby="dashboard-boards" className="flex flex-col gap-3">
        <SectionHeader id="dashboard-boards" title="Your boards" level={2} className="mb-0" />
        <div className="flex flex-wrap items-center gap-2">
          <div className="relative min-w-[220px] flex-1">
            <Search
              size={15}
              className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-[var(--muted-foreground)]"
            />
            <Input
              className="pl-9"
              placeholder="Search boards"
              aria-label="Search boards"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
            />
          </div>
          <Select
            aria-label="Filter by status"
            value={status}
            onChange={(event) => setStatus(event.target.value)}
            className="w-auto"
          >
            <option value="">All statuses</option>
            <option value="active">Active</option>
            <option value="error">Needs attention</option>
            <option value="migration_failed">Migration failed</option>
          </Select>
          <Select
            aria-label="Sort boards"
            value={sort}
            onChange={(event) => setSort(event.target.value)}
            className="w-auto"
          >
            <option value="updated_at">Recently updated</option>
            <option value="created_at">Newest</option>
            <option value="name">Name</option>
          </Select>
        </div>

        {isLoading ? (
          <p className="text-sm text-[var(--muted-foreground)]">Loading boards…</p>
        ) : error ? (
          <p role="alert" className="text-sm text-[var(--destructive)]">
            {describeError(error, "Could not load boards.")}
          </p>
        ) : boards.length === 0 ? (
          <EmptyState
            className="card-surface px-4 py-3.5"
            message={query || status ? "No board matches." : "No boards yet."}
            detail={query || status ? undefined : "A board holds the Loops of one project."}
          />
        ) : inUse.length === 0 ? (
          // Every board that matches is archived: they are listed under "Read only" below.
          <EmptyState
            className="card-surface px-4 py-3.5"
            message={query ? "No active board matches." : "No active boards."}
          />
        ) : (
          <BoardGrid label="Boards" boards={inUse} {...tiles} />
        )}
      </section>

      {readOnly.length > 0 ? (
        <Section title="Read only" count={readOnly.length} level={2}>
          <BoardGrid label="Read only boards" boards={readOnly} {...tiles} />
        </Section>
      ) : null}

      <NewBoardDialog open={creating} onOpenChange={setCreating} />
      <DeleteBoardDialog {...lifecycle.deleteDialog} />
    </section>
  );
}
