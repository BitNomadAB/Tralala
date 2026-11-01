import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, ArrowRight, History, Plus } from "lucide-react";
import { Badge, type BadgeTone } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent } from "@/components/ui/dialog";
import { Field, Input, Textarea } from "@/components/ui/input";
import { useToast } from "@/components/ui/toast";
import { ApiError, api } from "@/lib/api";
import { keys, useBoard, useLoops } from "@/lib/queries";
import type { Loop, LoopStage } from "@/lib/types";

const STAGE_TONES: Record<LoopStage, BadgeTone> = {
  draft: "neutral",
  analysis_review: "brand",
  planning: "brand",
  roadmap_review: "brand",
  ready: "success",
  in_progress: "brand",
  replanning: "warning",
  awaiting_qa: "warning",
  completed: "success",
  cancelled: "neutral",
};

export function BoardLoopsPage() {
  const { boardId = "" } = useParams();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const toast = useToast();
  const boardQuery = useBoard(boardId);
  const loopsQuery = useLoops(boardId, true);
  const [creating, setCreating] = useState(false);
  const [name, setName] = useState("");
  const [goal, setGoal] = useState("");
  const [showCompleted, setShowCompleted] = useState(true);

  const createLoop = useMutation({
    mutationFn: () => api.createLoop(boardId, { name: name.trim(), goal }),
    onSuccess: (loop) => {
      setCreating(false);
      setName("");
      setGoal("");
      queryClient.invalidateQueries({ queryKey: ["loops", boardId] });
      queryClient.invalidateQueries({ queryKey: keys.board(boardId) });
      toast.push({ title: "Loop created", variant: "success" });
      navigate(`/boards/${boardId}/loops/${loop.id}`);
    },
    onError: (error) =>
      toast.push({
        title: "Could not create the Loop",
        description: error instanceof ApiError ? error.message : undefined,
        variant: "error",
      }),
  });

  if (boardQuery.isLoading) {
    return <p className="text-sm text-[var(--muted-foreground)]">Loading board…</p>;
  }
  if (boardQuery.error || !boardQuery.data) {
    return (
      <p role="alert" className="text-sm text-[var(--destructive)]">
        {boardQuery.error instanceof ApiError ? boardQuery.error.message : "Board unavailable."}
      </p>
    );
  }

  const board = boardQuery.data;
  const loops = loopsQuery.data ?? [];
  const active = loops.filter((loop) => loop.stage !== "completed" && loop.stage !== "cancelled");
  const finished = loops.filter((loop) => loop.stage === "completed" || loop.stage === "cancelled");

  return (
    <section className="flex flex-col gap-4">
      <div className="flex flex-wrap items-start gap-3">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <h1 className="truncate text-lg font-semibold">{board.name}</h1>
            <Badge
              tone={
                board.status === "active"
                  ? "success"
                  : board.status === "archived"
                    ? "neutral"
                    : "danger"
              }
            >
              {board.status}
            </Badge>
          </div>
          <p className="text-xs text-[var(--muted-foreground)]">
            {board.description || "No description"} · {active.length} active Loops ·{" "}
            {finished.length} completed
          </p>
        </div>
        <div className="ml-auto flex flex-wrap items-center gap-2">
          <Link
            to={`/boards/${board.id}/history`}
            className="inline-flex h-8 items-center gap-1.5 rounded-lg border border-[var(--border)] px-2.5 text-xs text-[var(--foreground)] hover:bg-[var(--surface-raised)]"
          >
            <History size={14} /> Board history
          </Link>
          <Button
            size="sm"
            onClick={() => setCreating(true)}
            disabled={board.status !== "active"}
          >
            <Plus size={14} /> New Loop
          </Button>
        </div>
      </div>

      <LoopList loops={active} boardId={boardId} empty="This board has no active Loops yet." />

      {finished.length > 0 ? (
        <div className="flex flex-col gap-2">
          <div className="flex items-center gap-2">
            <h2 className="text-sm font-medium text-[var(--muted-foreground)]">Completed</h2>
            <Button size="sm" variant="ghost" onClick={() => setShowCompleted((value) => !value)}>
              {showCompleted ? "Hide" : "Show"}
            </Button>
          </div>
          {showCompleted ? (
            <LoopList loops={finished} boardId={boardId} empty="Nothing completed yet." />
          ) : null}
        </div>
      ) : null}

      <Dialog open={creating} onOpenChange={setCreating}>
        <DialogContent
          title="New Loop"
          description="A Loop owns its own Kanban and planning documents. It starts empty."
        >
          <form
            className="flex flex-col gap-3"
            onSubmit={(event) => {
              event.preventDefault();
              if (name.trim()) createLoop.mutate();
            }}
          >
            <Field label="Name" htmlFor="loop-name">
              <Input
                id="loop-name"
                value={name}
                onChange={(event) => setName(event.target.value)}
                required
                autoFocus
                maxLength={200}
              />
            </Field>
            <Field label="Broad goal" htmlFor="loop-goal">
              <Textarea
                id="loop-goal"
                rows={3}
                value={goal}
                onChange={(event) => setGoal(event.target.value)}
                maxLength={20000}
              />
            </Field>
            <div className="flex justify-end gap-2">
              <Button variant="ghost" type="button" onClick={() => setCreating(false)}>
                Cancel
              </Button>
              <Button type="submit" disabled={!name.trim() || createLoop.isPending}>
                {createLoop.isPending ? "Creating…" : "Create Loop"}
              </Button>
            </div>
          </form>
        </DialogContent>
      </Dialog>
    </section>
  );
}

function LoopList({
  loops,
  boardId,
  empty,
}: {
  loops: Loop[];
  boardId: string;
  empty: string;
}) {
  if (loops.length === 0) {
    return (
      <p className="rounded-lg border border-dashed border-[var(--border)] p-4 text-xs text-[var(--muted-foreground)]">
        {empty}
      </p>
    );
  }
  return (
    <ul className="grid gap-2 md:grid-cols-2">
      {loops.map((loop) => (
        <li key={loop.id}>
          <Link
            to={`/boards/${boardId}/loops/${loop.id}`}
            className="card-surface flex h-full flex-col gap-2 p-3 transition hover:border-[var(--primary)]"
          >
            <div className="flex flex-wrap items-center gap-2">
              <span className="font-mono text-[11px] text-[var(--muted-foreground)]">
                {loop.key}
              </span>
              <span className="text-sm font-medium">{loop.name}</span>
              <Badge tone={STAGE_TONES[loop.stage]}>{loop.stage.replace("_", " ")}</Badge>
              <ArrowRight size={14} className="ml-auto text-[var(--muted-foreground)]" />
            </div>
            {loop.goal ? (
              <p className="line-clamp-2 text-xs text-[var(--muted-foreground)]">{loop.goal}</p>
            ) : null}
            <div className="mt-auto flex flex-wrap items-center gap-2 text-[11px] text-[var(--muted-foreground)]">
              <span>
                {loop.progress.ticket_completed}/{loop.progress.ticket_total} tickets
              </span>
              {loop.plan ? <span>· {loop.plan.phase_count} phases</span> : null}
              {loop.qa ? (
                <span>
                  · QA {loop.qa.status.replace("_", " ")}
                  {loop.qa.open ? " (open)" : ""}
                </span>
              ) : null}
              {loop.warnings.length > 0 ? (
                <Badge tone="warning">
                  <AlertTriangle size={11} /> {loop.warnings.length}
                </Badge>
              ) : null}
            </div>
          </Link>
        </li>
      ))}
    </ul>
  );
}
