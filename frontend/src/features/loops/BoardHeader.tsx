import {
  Archive,
  ArchiveRestore,
  History,
  LayoutTemplate,
  Pencil,
  Plus,
  Trash2,
} from "lucide-react";
import { useNavigate } from "react-router-dom";
import { Button } from "@/components/ui/button";
import { Chip } from "@/components/ui/chip";
import { Menu, type MenuItem } from "@/components/ui/menu";
import type { BoardLifecycleAction } from "@/features/boards/BoardTile";
import type { Board } from "@/lib/types";

/**
 * The board page's head: the board's name as the page title, its description under it, a "Read
 * only" chip on an archived board, the quiet menu (edit, templates, history, archive or restore,
 * delete) and New Loop, the one primary button. `showNewLoop` is false while the empty list
 * carries New Loop itself, so the page has one.
 */
export function BoardHeader({
  board,
  showNewLoop,
  onNewLoop,
  onEdit,
  onLifecycle,
  onDelete,
}: {
  board: Board;
  showNewLoop: boolean;
  onNewLoop: () => void;
  onEdit: () => void;
  onLifecycle: (type: BoardLifecycleAction) => void;
  onDelete: () => void;
}) {
  const navigate = useNavigate();
  const archived = board.status === "archived";
  const items: MenuItem[] = [
    { label: "Edit board", icon: <Pencil size={14} />, onSelect: onEdit },
    {
      label: "Board templates",
      icon: <LayoutTemplate size={14} />,
      onSelect: () => {
        void navigate("/settings");
      },
    },
    {
      label: "Board history",
      icon: <History size={14} />,
      onSelect: () => {
        void navigate(`/boards/${board.id}/history`);
      },
    },
    archived
      ? {
          label: "Restore board",
          icon: <ArchiveRestore size={14} />,
          onSelect: () => onLifecycle("restore"),
        }
      : {
          label: "Archive board",
          icon: <Archive size={14} />,
          onSelect: () => onLifecycle("archive"),
        },
    {
      label: "Delete board",
      icon: <Trash2 size={14} />,
      danger: true,
      disabled: !archived,
      hint: archived ? undefined : "Archive the board first",
      onSelect: onDelete,
    },
  ];

  return (
    <header className="flex flex-wrap items-start gap-3">
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-2.5">
          <h1 className="truncate text-2xl font-semibold tracking-tight">{board.name}</h1>
          {archived ? <Chip>Archived</Chip> : null}
        </div>
        {board.description ? (
          <p className="m-0 mt-2 max-w-[62ch] text-[15.5px] leading-relaxed text-[var(--muted-foreground)]">
            {board.description}
          </p>
        ) : null}
      </div>
      <div className="flex items-center gap-1.5">
        <Menu label="Board actions" items={items} />
        {showNewLoop ? (
          <Button onClick={onNewLoop} disabled={board.status !== "active"}>
            <Plus size={15} /> New Loop
          </Button>
        ) : null}
      </div>
    </header>
  );
}
