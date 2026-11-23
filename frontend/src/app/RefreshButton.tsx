import { useQueryClient } from "@tanstack/react-query";
import { RefreshCw } from "lucide-react";
import { useState } from "react";
import { useMatch } from "react-router-dom";
import { HeldButton } from "@/components/ui/held-button";
import { useAnnounce } from "@/components/ui/useAnnounce";
import { cn } from "@/lib/utils";
import { useBoardChanges } from "./useBoardChanges";

/**
 * How long "Refresh" shows that it runs, at least: an answer from a server nearby arrives before
 * the eye has seen the button change.
 */
const REFRESH_SHOWN_MS = 500;

/**
 * "Refresh" in the header: reads again everything the page shows, without loading the page anew,
 * so a draft, an open Ticket and the place on the page stay. While it runs the button is held and
 * its icon turns; a screen reader hears "Page refreshed." unless a request failed, which the page
 * says itself.
 *
 * The same component follows the board of the page for changes made elsewhere (`useBoardChanges`),
 * which refreshes the listings by itself. The button is for the rest: a page without a board, and
 * what is deliberately not followed, an open Ticket and the planning documents.
 */
export function RefreshButton() {
  const queryClient = useQueryClient();
  const announce = useAnnounce();
  const [refreshing, setRefreshing] = useState(false);
  useBoardChanges(useMatch("/boards/:boardId/*")?.params.boardId);

  async function refresh() {
    setRefreshing(true);
    try {
      await Promise.all([
        queryClient.invalidateQueries(),
        new Promise((resolve) => window.setTimeout(resolve, REFRESH_SHOWN_MS)),
      ]);
    } finally {
      setRefreshing(false);
    }
    const failed = queryClient
      .getQueryCache()
      .findAll({ type: "active" })
      .some((query) => query.state.status === "error");
    if (!failed) announce("Page refreshed.");
  }

  return (
    <HeldButton
      variant="ghost"
      size="icon"
      aria-label="Refresh"
      title="Refresh"
      held={refreshing}
      onClick={() => {
        void refresh();
      }}
    >
      <RefreshCw
        size={15}
        aria-hidden="true"
        className={cn(refreshing && "motion-safe:animate-spin")}
      />
    </HeldButton>
  );
}
