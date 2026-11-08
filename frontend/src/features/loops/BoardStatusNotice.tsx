import { useMutation, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useToast } from "@/components/ui/useToast";
import { api } from "@/lib/api";
import { describeError } from "@/lib/describeError";
import { keys } from "@/lib/queries";
import type { Board } from "@/lib/types";

/** Why a board in maintenance, in error or after a failed migration cannot be used, and a retry. */
export function BoardStatusNotice({ board }: { board: Board }) {
  const queryClient = useQueryClient();
  const toast = useToast();
  const retryMigration = useMutation({
    mutationFn: () => api.retryMigration(board.id),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: keys.board(board.id) });
      void queryClient.invalidateQueries({ queryKey: ["loops", board.id] });
      toast.push({ title: "Migration retried", variant: "success" });
    },
    onError: (error) => {
      toast.push({
        title: "Migration still fails",
        description: describeError(error, undefined),
        variant: "error",
      });
    },
  });

  if (board.status === "active" || board.status === "archived") return null;
  return (
    <div className="flex flex-col gap-2 rounded-lg border border-[var(--border)] bg-[var(--surface-raised)] p-3 text-xs">
      <p className="flex items-center gap-1.5 font-medium">
        <AlertTriangle size={13} className="text-[var(--destructive)]" />
        This board cannot be used while its status is {board.status}.
      </p>
      <p className="text-[var(--muted-foreground)]">
        {board.status === "migration_failed"
          ? "A schema upgrade stopped on this board. The Loop schema replaces the old lists and cards, so a database written before Loops cannot be converted in place; the server log names the board. Retrying only helps after the underlying problem is fixed."
          : "The board is in maintenance or error state; retrying the migration is safe."}{" "}
        The last backups and the export archive stay available.
      </p>
      <div className="flex flex-wrap items-center gap-2">
        <Button
          size="sm"
          variant="outline"
          onClick={() => retryMigration.mutate()}
          disabled={retryMigration.isPending}
        >
          Retry migration
        </Button>
        <a className="underline" href={api.exportUrl(board.id)} download={`${board.name}.zip`}>
          Download export archive
        </a>
      </div>
    </div>
  );
}
