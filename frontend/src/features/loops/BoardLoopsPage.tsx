import { useQuery } from "@tanstack/react-query";
import { Plus } from "lucide-react";
import { useMemo, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { Button } from "@/components/ui/button";
import { EmptyState } from "@/components/ui/empty-state";
import { Expander } from "@/components/ui/expander";
import { Section } from "@/components/ui/section";
import { DeleteBoardDialog } from "@/features/boards/DeleteBoardDialog";
import { useBoardLifecycle } from "@/features/boards/useBoardLifecycle";
import { api } from "@/lib/api";
import { describeError } from "@/lib/describeError";
import { useAgents, useBoard, useLoopSummaries, useLoops } from "@/lib/queries";
import type { LoopSummary } from "@/lib/types";
import { BoardContext } from "./BoardContext";
import { BoardHeader } from "./BoardHeader";
import { BoardStatusNotice } from "./BoardStatusNotice";
import { EditBoardDialog } from "./EditBoardDialog";
import { LoopList } from "./LoopList";
import { isFinished } from "./loopNextAction";
import { NewLoopDialog } from "./NewLoopDialog";
import { useBoardEditing } from "./useBoardEditing";

/**
 * A board's Loops: what each waits for and the person's next action first, as rows; completed and
 * cancelled Loops folded away under "Completed (N)"; the board's agents and repositories under
 * their own expander.
 */
export function BoardLoopsPage() {
  const { boardId = "" } = useParams();
  const navigate = useNavigate();
  const boardQuery = useBoard(boardId);
  const loopsQuery = useLoops(boardId, true);
  const summariesQuery = useLoopSummaries(
    boardId,
    boardQuery.data?.status === "active" || boardQuery.data?.status === "archived",
  );
  const agentsQuery = useAgents();
  const repositoriesQuery = useQuery({
    queryKey: ["repositories"],
    queryFn: () => api.listRepositories(),
    staleTime: 60_000,
  });
  const [creating, setCreating] = useState(false);
  const editing = useBoardEditing(boardId);
  const lifecycle = useBoardLifecycle({
    onDeleted: () => {
      void navigate("/");
    },
  });
  const summaries = useMemo(
    () =>
      new Map<string, LoopSummary>(
        (summariesQuery.data?.loops ?? []).map((summary) => [summary.id, summary]),
      ),
    [summariesQuery.data],
  );

  if (boardQuery.isLoading) {
    return <p className="text-sm text-[var(--muted-foreground)]">Loading board…</p>;
  }
  if (boardQuery.error || !boardQuery.data) {
    return (
      <p role="alert" className="text-sm text-[var(--destructive)]">
        {describeError(boardQuery.error, "Board unavailable.")}
      </p>
    );
  }

  const board = boardQuery.data;
  const readOnly = board.status !== "active";
  const loops = loopsQuery.data ?? [];
  const active = loops.filter((loop) => !isFinished(loop.stage));
  const finished = loops.filter((loop) => isFinished(loop.stage));
  const empty = loopsQuery.isSuccess && loops.length === 0;

  return (
    <section className="flex flex-col gap-6">
      <BoardHeader
        board={board}
        showNewLoop={!empty}
        onNewLoop={() => setCreating(true)}
        onEdit={() => editing.open(board)}
        onLifecycle={(type) => lifecycle.run(type, board)}
        onDelete={() => lifecycle.askDelete(board)}
      />

      <BoardStatusNotice board={board} />

      <Section title="Current Loops" count={loopsQuery.isSuccess ? active.length : undefined}>
        {loopsQuery.isLoading ? (
          <p className="text-sm text-[var(--muted-foreground)]">Loading Loops…</p>
        ) : loopsQuery.error ? (
          <p role="alert" className="text-sm text-[var(--destructive)]">
            {describeError(loopsQuery.error, "Could not load the Loops.")}
          </p>
        ) : empty ? (
          <div className="card-surface flex flex-wrap items-center justify-between gap-3 px-4 py-3.5">
            <EmptyState message="No Loops yet. A Loop starts with its Info: what you want and why." />
            <Button onClick={() => setCreating(true)} disabled={readOnly}>
              <Plus size={15} /> New Loop
            </Button>
          </div>
        ) : active.length === 0 ? (
          <EmptyState className="card-surface px-4 py-3.5" message="No Loop is open right now." />
        ) : (
          <LoopList
            label="Current Loops"
            loops={active}
            summaries={summaries}
            boardId={boardId}
            readOnly={readOnly}
          />
        )}
      </Section>

      {finished.length > 0 ? (
        <Expander title={`Completed (${finished.length})`}>
          <LoopList
            label="Completed Loops"
            loops={finished}
            summaries={summaries}
            boardId={boardId}
            readOnly
            framed={false}
          />
        </Expander>
      ) : null}

      <Expander title="Agents and repositories">
        <BoardContext
          agentIds={board.agent_ids}
          repositoryIds={board.repository_ids}
          agents={agentsQuery.data ?? []}
          repositories={repositoriesQuery.data ?? []}
        />
      </Expander>

      <EditBoardDialog {...editing.dialog} />
      <DeleteBoardDialog {...lifecycle.deleteDialog} />
      <NewLoopDialog boardId={boardId} open={creating} onOpenChange={setCreating} />
    </section>
  );
}
