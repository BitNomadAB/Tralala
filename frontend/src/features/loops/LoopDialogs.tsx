import type { Board, Loop } from "@/lib/types";
import { LoopAgentsDialog } from "./LoopAgentsDialog";
import { LoopCancelDialog } from "./LoopCancelDialog";
import { LoopCompletionDialog } from "./LoopCompletionDialog";
import { LoopEditDialog } from "./LoopEditDialog";
import { SaveTemplateDialog } from "./SaveTemplateDialog";

/** The dialogs the Loop's header opens; each is a decision or an edit that asks first. */
export type LoopDialog = "edit" | "agents" | "completion" | "template" | "cancel";

/** The one open dialog of the header, mounted only while it is open so it starts afresh. */
export function LoopDialogs({
  open,
  onClose,
  board,
  loop,
  isHuman,
  columnCount,
  onChanged,
}: {
  open: LoopDialog | null;
  onClose: () => void;
  board: Board;
  loop: Loop;
  isHuman: boolean;
  columnCount: number;
  onChanged: () => void;
}) {
  switch (open) {
    case null:
      return null;
    case "edit":
      return (
        <LoopEditDialog boardId={board.id} loop={loop} onClose={onClose} onChanged={onChanged} />
      );
    case "agents":
      return <LoopAgentsDialog boardId={board.id} loop={loop} open onClose={onClose} />;
    case "completion":
      return (
        <LoopCompletionDialog
          boardId={board.id}
          loop={loop}
          open
          isHuman={isHuman}
          onClose={onClose}
          onChanged={onChanged}
        />
      );
    case "template":
      return (
        <SaveTemplateDialog
          boardId={board.id}
          loopId={loop.id}
          defaultName={`${loop.name} template`}
          defaultDescription={board.description}
          columnCount={columnCount}
          onClose={onClose}
        />
      );
    case "cancel":
      return (
        <LoopCancelDialog boardId={board.id} loop={loop} onClose={onClose} onChanged={onChanged} />
      );
  }
}
