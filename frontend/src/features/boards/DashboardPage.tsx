import { useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import {
  Archive,
  ArchiveRestore,
  Copy,
  Download,
  Plus,
  Search,
  Trash2,
  Upload,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent } from "@/components/ui/dialog";
import { RepositoryPicker } from "@/features/boards/RepositoryPicker";
import { Field, Input, Select, Textarea } from "@/components/ui/input";
import { useToast } from "@/components/ui/toast";
import { ApiError, api } from "@/lib/api";
import { useBoards, useTemplates } from "@/lib/queries";
import { formatDate } from "@/lib/utils";
import type { Board } from "@/lib/types";
import { useDashboardTools } from "@/webmcp/useWebMcp";

export function DashboardPage() {
  useDashboardTools();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const toast = useToast();
  const [query, setQuery] = useState("");
  const [status, setStatus] = useState("");
  const [sort, setSort] = useState("updated_at");
  const [creating, setCreating] = useState(false);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [templateId, setTemplateId] = useState("");
  const [repositoryIds, setRepositoryIds] = useState<string[]>([]);
  const [deleting, setDeleting] = useState<Board | null>(null);
  const [confirmName, setConfirmName] = useState("");
  const importInput = useRef<HTMLInputElement>(null);

  const filters = useMemo(
    () => ({ q: query || undefined, status: status || undefined, sort, order: "desc" }),
    [query, status, sort],
  );
  const { data, isLoading, error } = useBoards(filters);
  const { data: templates = [] } = useTemplates();
  const selectedTemplate = templates.find((template) => template.id === templateId) ?? null;

  const invalidate = () => queryClient.invalidateQueries({ queryKey: ["boards"] });

  const createMutation = useMutation({
    mutationFn: () =>
      api.createBoard({
        name: name.trim(),
        description: description.trim(),
        template_id: templateId || null,
        repository_ids: repositoryIds,
      }),
    onSuccess: (board) => {
      invalidate();
      setCreating(false);
      setName("");
      setDescription("");
      setTemplateId("");
      setRepositoryIds([]);
      toast.push({ title: "Board created", variant: "success" });
      navigate(`/boards/${board.id}`);
    },
    onError: (mutationError) =>
      toast.push({
        title: "Could not create board",
        description: mutationError instanceof ApiError ? mutationError.message : undefined,
        variant: "error",
      }),
  });

  const lifecycleMutation = useMutation({
    mutationFn: async (action: {
      type: "archive" | "restore" | "duplicate";
      board: Board;
    }) => {
      if (action.type === "archive") return api.archiveBoard(action.board.id);
      if (action.type === "restore") return api.restoreBoard(action.board.id);
      return api.duplicateBoard(action.board.id);
    },
    onSuccess: (_result, action) => {
      invalidate();
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
    onError: (mutationError) =>
      toast.push({
        title: "Action failed",
        description: mutationError instanceof ApiError ? mutationError.message : undefined,
        variant: "error",
      }),
  });

  const deleteMutation = useMutation({
    mutationFn: (board: Board) => api.deleteBoard(board.id, confirmName),
    onSuccess: () => {
      invalidate();
      setDeleting(null);
      setConfirmName("");
      toast.push({ title: "Board deleted", variant: "success" });
    },
    onError: (mutationError) =>
      toast.push({
        title: "Could not delete board",
        description: mutationError instanceof ApiError ? mutationError.message : undefined,
        variant: "error",
      }),
  });

  const importMutation = useMutation({
    mutationFn: (file: File) => api.importBoard(file),
    onSuccess: (board) => {
      invalidate();
      toast.push({ title: "Board imported", variant: "success" });
      navigate(`/boards/${board.id}`);
    },
    onError: (mutationError) =>
      toast.push({
        title: "Import failed",
        description: mutationError instanceof ApiError ? mutationError.message : undefined,
        variant: "error",
      }),
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
            <li key={board.id} className="card-surface flex flex-col gap-3 p-4">
              <div className="flex items-start justify-between gap-2">
                <div className="min-w-0">
                  <button
                    type="button"
                    onClick={() => navigate(`/boards/${board.id}`)}
                    className="truncate text-left text-sm font-semibold hover:text-[var(--primary)]"
                  >
                    {board.name}
                  </button>
                  <p className="mt-0.5 line-clamp-2 text-xs text-[var(--muted-foreground)]">
                    {board.description || "No description"}
                  </p>
                </div>
                <Badge tone={board.status === "active" ? "success" : board.status === "archived" ? "neutral" : "danger"}>
                  {board.status}
                </Badge>
              </div>
              <dl className="grid grid-cols-2 gap-1 text-[11px] text-[var(--muted-foreground)]">
                <div>
                  <dt className="uppercase tracking-wide">Lists</dt>
                  <dd className="text-[var(--foreground)]">{board.list_count}</dd>
                </div>
                <div>
                  <dt className="uppercase tracking-wide">Cards</dt>
                  <dd className="text-[var(--foreground)]">{board.card_count}</dd>
                </div>
                <div>
                  <dt className="uppercase tracking-wide">Created</dt>
                  <dd className="text-[var(--foreground)]">{formatDate(board.created_at)}</dd>
                </div>
                <div>
                  <dt className="uppercase tracking-wide">Updated</dt>
                  <dd className="text-[var(--foreground)]">{formatDate(board.updated_at)}</dd>
                </div>
              </dl>
              <div className="mt-auto flex flex-wrap items-center gap-1.5 border-t border-[var(--border)] pt-2">
                <Button size="sm" variant="secondary" onClick={() => navigate(`/boards/${board.id}`)}>
                  Open
                </Button>
                <Button
                  size="icon"
                  variant="ghost"
                  title="Duplicate board"
                  aria-label={`Duplicate ${board.name}`}
                  onClick={() => lifecycleMutation.mutate({ type: "duplicate", board })}
                >
                  <Copy size={14} />
                </Button>
                <a
                  href={api.exportUrl(board.id)}
                  className="inline-flex h-8 w-8 items-center justify-center rounded-lg text-[var(--muted-foreground)] hover:bg-[var(--surface-raised)] hover:text-[var(--foreground)]"
                  title="Export board"
                  aria-label={`Export ${board.name}`}
                >
                  <Download size={14} />
                </a>
                {board.status === "archived" ? (
                  <Button
                    size="icon"
                    variant="ghost"
                    title="Restore board"
                    aria-label={`Restore ${board.name}`}
                    onClick={() => lifecycleMutation.mutate({ type: "restore", board })}
                  >
                    <ArchiveRestore size={14} />
                  </Button>
                ) : (
                  <Button
                    size="icon"
                    variant="ghost"
                    title="Archive board"
                    aria-label={`Archive ${board.name}`}
                    onClick={() => lifecycleMutation.mutate({ type: "archive", board })}
                  >
                    <Archive size={14} />
                  </Button>
                )}
                <Button
                  size="icon"
                  variant="ghost"
                  title="Delete board"
                  aria-label={`Delete ${board.name}`}
                  disabled={board.status !== "archived"}
                  onClick={() => {
                    setDeleting(board);
                    setConfirmName("");
                  }}
                >
                  <Trash2 size={14} />
                </Button>
              </div>
            </li>
          ))}
        </ul>
      )}

      <Dialog
        open={creating}
        onOpenChange={(open) => {
          setCreating(open);
          if (!open) {
            setTemplateId("");
            setRepositoryIds([]);
          }
        }}
      >
        <DialogContent title="New board" description="A dedicated SQLite database is created for it.">
          <form
            className="flex flex-col gap-3"
            onSubmit={(event) => {
              event.preventDefault();
              createMutation.mutate();
            }}
          >
            <Field label="Name" htmlFor="board-name">
              <Input
                id="board-name"
                value={name}
                onChange={(event) => setName(event.target.value)}
                required
                autoFocus
                maxLength={200}
              />
            </Field>
            <Field label="Start from" htmlFor="board-template">
              <Select
                id="board-template"
                value={templateId}
                onChange={(event) => {
                  const next = event.target.value;
                  setTemplateId(next);
                  const template = templates.find((entry) => entry.id === next);
                  setDescription(template ? template.description : "");
                }}
              >
                <option value="">Blank board (Backlog → Done)</option>
                {templates.map((template) => (
                  <option key={template.id} value={template.id}>
                    {template.name}
                  </option>
                ))}
              </Select>
            </Field>
            {selectedTemplate ? (
              <div className="rounded-lg border border-[var(--border)] bg-[var(--surface-raised)] p-2 text-xs">
                <p className="text-[var(--muted-foreground)]">
                  {selectedTemplate.list_count > 0
                    ? `Lists: ${selectedTemplate.lists.join(" → ")}`
                    : "No lists saved; the default Backlog → Done lists are used."}
                </p>
                {selectedTemplate.labels.length > 0 ? (
                  <p className="mt-1 text-[var(--muted-foreground)]">
                    Labels: {selectedTemplate.labels.map((label) => label.name).join(", ")}
                  </p>
                ) : null}
              </div>
            ) : null}
            <RepositoryPicker selected={repositoryIds} onChange={setRepositoryIds} />
            <Field label="Description" htmlFor="board-description">
              <Textarea
                id="board-description"
                value={description}
                onChange={(event) => setDescription(event.target.value)}
                maxLength={20000}
              />
            </Field>
            <div className="flex justify-end gap-2">
              <Button variant="ghost" onClick={() => setCreating(false)}>
                Cancel
              </Button>
              <Button type="submit" disabled={createMutation.isPending || !name.trim()}>
                {createMutation.isPending ? "Creating…" : "Create board"}
              </Button>
            </div>
          </form>
        </DialogContent>
      </Dialog>

      <Dialog open={Boolean(deleting)} onOpenChange={(open) => !open && setDeleting(null)}>
        <DialogContent
          title="Delete board permanently"
          description="This deletes the board database and its backups. It cannot be undone."
        >
          <form
            className="flex flex-col gap-3"
            onSubmit={(event) => {
              event.preventDefault();
              if (deleting) deleteMutation.mutate(deleting);
            }}
          >
            <Field
              label={`Type "${deleting?.name ?? ""}" to confirm`}
              htmlFor="confirm-name"
            >
              <Input
                id="confirm-name"
                value={confirmName}
                onChange={(event) => setConfirmName(event.target.value)}
                autoFocus
              />
            </Field>
            <div className="flex justify-end gap-2">
              <Button variant="ghost" onClick={() => setDeleting(null)}>
                Cancel
              </Button>
              <Button
                variant="danger"
                type="submit"
                disabled={confirmName !== deleting?.name || deleteMutation.isPending}
              >
                Delete board
              </Button>
            </div>
          </form>
        </DialogContent>
      </Dialog>
    </section>
  );
}
