import { useQuery } from "@tanstack/react-query";
import { History, X } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { api } from "@/lib/api";
import { formatDateTime } from "@/lib/utils";

export function ActivityPanel({ boardId, onClose }: { boardId: string; onClose: () => void }) {
  const { data, isLoading } = useQuery({
    queryKey: ["activity", boardId, "board"],
    queryFn: () => api.listActivity(boardId, { limit: 50 }),
  });

  return (
    <aside
      aria-label="Board activity"
      className="card-surface fixed bottom-4 right-4 top-20 z-30 flex w-[min(360px,92vw)] flex-col overflow-hidden shadow-2xl"
    >
      <header className="flex items-center gap-2 border-b border-[var(--border)] p-3">
        <History size={15} className="text-[var(--muted-foreground)]" />
        <h2 className="text-sm font-semibold">Activity</h2>
        <Button size="icon" variant="ghost" className="ml-auto" aria-label="Close activity" onClick={onClose}>
          <X size={15} />
        </Button>
      </header>
      <div className="scrollbar-thin flex-1 overflow-y-auto p-3">
        {isLoading ? (
          <p className="text-xs text-[var(--muted-foreground)]">Loading activity…</p>
        ) : (data ?? []).length === 0 ? (
          <p className="text-xs text-[var(--muted-foreground)]">No activity yet.</p>
        ) : (
          <ul className="flex flex-col gap-2.5">
            {(data ?? []).map((entry) => (
              <li key={entry.id} className="border-b border-[var(--border)] pb-2 last:border-0">
                <div className="flex items-center gap-2">
                  <Badge tone={entry.actor_type === "agent" ? "brand" : "neutral"}>
                    {entry.actor_type}
                  </Badge>
                  <span className="text-xs font-medium">{entry.action}</span>
                  <span className="ml-auto text-[10px] text-[var(--muted-foreground)]">
                    {formatDateTime(entry.timestamp)}
                  </span>
                </div>
                <p className="mt-1 text-[11px] text-[var(--muted-foreground)]">
                  {entry.entity_type} · {entry.entity_id.slice(0, 8)}
                  {entry.actor_id ? ` · actor ${entry.actor_id.slice(0, 8)}` : ""}
                </p>
              </li>
            ))}
          </ul>
        )}
      </div>
    </aside>
  );
}
