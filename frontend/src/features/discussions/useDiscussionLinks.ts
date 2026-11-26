import { useNavigate } from "react-router-dom";
import { useToast } from "@/components/ui/useToast";
import { ticketPagePath } from "@/features/cards/ticketRules";
import type { Discussion } from "@/lib/types";
import { clipboard } from "@/lib/utils";
import { boardPagePath, discussionAddress, ticketOnLoopPath } from "./discussionRules";

/**
 * Where the view's links go: the discussion's own page ("Open as page", "Copy link"), and Back,
 * to the Ticket (its page from the page, over the Kanban from the dialog, or `onBack` in the
 * Ticket's dialog) or, for a discussion on the board, to the board. A thread whose Ticket the API
 * could not place in a Loop has no page and no way back.
 */
export function useDiscussionLinks({
  boardId,
  loopId,
  discussion,
  host,
  onBack,
}: {
  boardId: string;
  loopId: string | null;
  discussion: Discussion;
  host: "modal" | "page";
  onBack: ((cardId: string) => void) | undefined;
}) {
  const navigate = useNavigate();
  const toast = useToast();
  const cardId = discussion.card_id;
  const pagePath =
    cardId === null || loopId ? discussionAddress(boardId, loopId, cardId, discussion.id) : null;

  let back: (() => void) | undefined;
  if (cardId === null) {
    back = () => void navigate(boardPagePath(boardId));
  } else if (onBack) {
    back = () => onBack(cardId);
  } else if (loopId) {
    const to =
      host === "page"
        ? ticketPagePath(boardId, loopId, cardId)
        : ticketOnLoopPath(boardId, loopId, cardId);
    back = () => void navigate(to);
  }

  function copyLink() {
    const target = clipboard();
    if (!target || pagePath === null) {
      toast.push({ title: "This browser does not allow copying here", variant: "warning" });
      return;
    }
    target.writeText(`${window.location.origin}${pagePath}`).then(
      () => toast.push({ title: "Link copied", variant: "success" }),
      () => toast.push({ title: "Could not copy", variant: "error" }),
    );
  }

  return {
    pagePath,
    back,
    copyLink,
    openPage: pagePath === null ? undefined : () => void navigate(pagePath),
  };
}
