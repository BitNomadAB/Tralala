import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Plus, Search, Upload } from "lucide-react";
import { useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Button } from "@/components/ui/button";
import { Input, Select } from "@/components/ui/input";
import { useToast } from "@/components/ui/useToast";
import { ApiError, api } from "@/lib/api";
import { useBoards } from "@/lib/queries";
import type { Board } from "@/lib/types";
import { useDashboardTools } from "@/webmcp/useWebMcp";
import { BoardTile, type BoardLifecycleAction } from "./BoardTile";
import { DeleteBoardDialog } from "./DeleteBoardDialog";
import { NewBoardDialog } from "./NewBoardDialog";

export function DashboardPage() {
  useDashboardTools();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const toast = useToast();
  const [query, setQuery] = useState("");
  const [status, setStatus] = useState("");
  const [sort, setSort] = useState("updated_at");
  const [creating, setCreating] = useState(false);
  const [deleting, setDeleting] = useState<Board | null>(null);
  const [confirmName, setConfirmName] = useState("");
  const importInput = useRef<HTMLInputElement>(null);

  const filters = useMemo(
    () => ({ q: query || undefined, status: status || undefined, sort, order: "desc" }),
    [query, status, sort],
  );
  const { data, isLoading, error } = useBoards(filters);
  const invalidate = () => queryClient.invalidateQueries({ queryKey: ["boards"] });

  const lifecycleMutation = useMutation({
    mutationFn: async (action: { type: BoardLifecycleAction; board: Board }) => {
      if (action.type === "archive") return api.archiveBoard(action.board.id);
      if (action.type === "restore") return api.restoreBoard(action.board.id);
      return api.duplicateBoard(action.board.id);
    },
    onSuccess: (_result, action) => {
      void invalidate();
      toast.push({
        title:
          action.type === "archive"
            ? "Board archived"
            : action.type === "restore"
              ? "Board restored"
              : "Board duplicated",
        variant: "success",
      });
    },
    onError: (mutationError) => {
      toast.push({
        title: "Action failed",
        description: mutationError instanceof ApiError ? mutationError.message : undefined,
        variant: "error",
      });
    },
  });

  const deleteMutation = useMutation({
    mutationFn: (board: Board) => api.deleteBoard(board.id, confirmName),
    onSuccess: () => {
      void invalidate();
      setDeleting(null);
      setConfirmName("");
      toast.push({ title: "Board deleted", variant: "success" });
    },
    onError: (mutationError) => {
      toast.push({
        title: "Could not delete board",
        description: mutationError instanceof ApiError ? mutationError.message : undefined,
        variant: "error",
      });
    },
  });

  const importMutation = useMutation({
    mutationFn: (file: File) => api.importBoard(file),
    onSuccess: (board) => {
      void invalidate();
      toast.push({ title: "Board imported", variant: "success" });
      void navigate(`/boards/${board.id}`);
    },
    onError: (mutationError) => {
      toast.push({
        title: "Import failed",
        description: mutationError instanceof ApiError ? mutationError.message : undefined,
        variant: "error",
      });
    },
  });

  const boards = data?.items ?? [];

  return (
    <section className="flex flex-col gap-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold">Boards</h1>
          <p className="text-xs text-[var(--muted-foreground)]">
            Each board is an independent SQLite database.
          </p>
        </div>
        <div className="flex items-center gap-2">
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
          <Button variant="outline" onClick={() => importInput.current?.click()}>
            <Upload size={15} /> Import
          </Button>
          <Button onClick={() => setCreating(true)}>
            <Plus size={15} /> New board
          </Button>
        </div>
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <div className="relative flex-1 min-w-[220px]">
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
          <option value="archived">Archived</option>
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
          {error instanceof ApiError ? error.message : "Could not load boards."}
        </p>
      ) : boards.length === 0 ? (
        <div className="card-surface flex flex-col items-center gap-2 p-10 text-center">
          <p className="text-sm font-medium">No boards yet</p>
          <p className="text-xs text-[var(--muted-foreground)]">
            Create your first board to get Backlog → Todo → In Progress → Review → Done.
          </p>
        </div>
      ) : (
        <ul className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
          {boards.map((board) => (
            <BoardTile
              key={board.id}
              board={board}
              onOpen={() => {
                void navigate(`/boards/${board.id}`);
              }}
              onLifecycle={(type) => lifecycleMutation.mutate({ type, board })}
              onDelete={() => {
                setDeleting(board);
                setConfirmName("");
              }}
            />
          ))}
        </ul>
      )}

      <NewBoardDialog open={creating} onOpenChange={setCreating} />

      <DeleteBoardDialog
        board={deleting}
        confirmName={confirmName}
        onConfirmNameChange={setConfirmName}
        deleting={deleteMutation.isPending}
        onDelete={(board) => deleteMutation.mutate(board)}
        onClose={() => setDeleting(null)}
      />
    </section>
  );
}
