import { useQuery } from "@tanstack/react-query";
import { History, X } from "lucide-react";
import { useEffect, useRef } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { api } from "@/lib/api";
import { formatDateTime } from "@/lib/utils";

/**
 * The board's latest activity, a panel beside the Loop's tabs (below them on a narrow screen), so
 * it never covers what the keyboard focuses (WCAG 2.4.11). Opening it moves the focus to its
 * heading; Escape inside it or "Close activity" closes it, and the focus goes back to what opened
 * it, the "Loop actions" button (WCAG 2.4.3).
 */
export function ActivityPanel({ boardId, onClose }: { boardId: string; onClose: () => void }) {
  const { data, isLoading } = useQuery({
    queryKey: ["activity", boardId, "board"],
    queryFn: () => api.listActivity(boardId, { limit: 50 }),
  });
  const panel = useRef<HTMLElement>(null);
  const heading = useRef<HTMLHeadingElement>(null);

  useEffect(() => {
    const opener = document.activeElement;
    const node = panel.current;
    heading.current?.focus();
    return () => {
      // Give the focus back only when it was in the panel (now gone) or nowhere.
      const now = document.activeElement;
      const lost = now === null || now === document.body || (node?.contains(now) ?? false);
      if (lost && opener instanceof HTMLElement && opener.isConnected) opener.focus();
    };
  }, []);

  // Escape anywhere inside the panel closes it; a landmark takes no key handler of its own in JSX.
  useEffect(() => {
    const node = panel.current;
    if (!node) return undefined;
    function onKeyDown(event: KeyboardEvent) {
      if (event.key !== "Escape" || event.defaultPrevented) return;
      event.preventDefault();
      onClose();
    }
    node.addEventListener("keydown", onKeyDown);
    return () => {
      node.removeEventListener("keydown", onKeyDown);
    };
  }, [onClose]);

  return (
    <aside
      ref={panel}
      aria-label="Board activity"
      className="card-surface flex max-h-[50vh] w-full shrink-0 flex-col overflow-hidden lg:max-h-none lg:w-[360px]"
    >
      <header className="flex items-center gap-2 border-b border-[var(--border)] p-3">
        <History size={15} aria-hidden="true" className="text-[var(--muted-foreground)]" />
        <h2 ref={heading} tabIndex={-1} className="text-sm font-semibold focus:outline-none">
          Activity
        </h2>
        <Button
          size="icon"
          variant="ghost"
          className="ml-auto"
          aria-label="Close activity"
          onClick={onClose}
        >
          <X size={15} aria-hidden="true" />
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
                <div className="flex flex-wrap items-center gap-2">
                  <Badge tone={entry.actor_type === "agent" ? "brand" : "neutral"}>
                    {entry.actor_type}
                  </Badge>
                  <span className="text-xs font-medium">{entry.action}</span>
                  <span className="ml-auto text-xs text-[var(--muted-foreground)]">
                    {formatDateTime(entry.timestamp)}
                  </span>
                </div>
                <p className="mt-1 text-xs text-[var(--muted-foreground)]">
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
