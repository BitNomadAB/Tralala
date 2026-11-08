import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Button } from "@/components/ui/button";
import { useToast } from "@/components/ui/useToast";
import { api } from "@/lib/api";
import { describeError } from "@/lib/describeError";
import type { Board, Loop } from "@/lib/types";

/** Why the Loop page cannot be worked on: a board whose migration failed, or a read-only Loop. */
export function LoopNotices({
  board,
  loop,
  readOnly,
}: {
  board: Board;
  loop: Loop;
  readOnly: boolean;
}) {
  const queryClient = useQueryClient();
  const toast = useToast();
  const retry = useMutation({
    mutationFn: () => api.retryMigration(board.id),
    onSuccess: (report) => {
      toast.push({ title: `Migration ${report.status}`, variant: "success" });
      void queryClient.invalidateQueries();
    },
    onError: (error) => {
      toast.push({
        title: "Migration failed",
        description: describeError(error, "See the server log."),
        variant: "error",
      });
    },
  });

  return (
    <>
      {board.status === "migration_failed" ? (
        <div className="flex flex-wrap items-center gap-3 rounded-lg border border-[var(--warning)] p-2 text-xs text-[var(--warning)]">
          <span>This board needs an explicit development reset before it can be used.</span>
          <Button
            size="sm"
            variant="outline"
            disabled={retry.isPending}
            onClick={() => retry.mutate()}
          >
            {retry.isPending ? "Migrating…" : "Retry migration"}
          </Button>
        </div>
      ) : null}

      {readOnly ? (
        <div className="flex flex-wrap items-center gap-3 rounded-lg border border-[var(--warning)] p-2 text-xs text-[var(--warning)]">
          Read-only: this Loop is {loop.stage}
          {loop.stage === "completed" ? " and its history snapshot is immutable." : "."}
        </div>
      ) : null}
    </>
  );
}
