import { useState, type DragEvent } from "react";

/** Whether a drag carries files (not text or a link dragged from the page). */
export function carriesFiles(types: Iterable<string>): boolean {
  return Array.from(types).includes("Files");
}

/**
 * The browser's own drag events for an area that takes files: `dragging` while files are over it,
 * and `onFiles` with what was dropped. Text or a link dragged from the page is left alone. When
 * `disabled`, the handlers are empty, so the browser's default applies.
 */
export function useFileDrop({
  onFiles,
  disabled = false,
}: {
  onFiles: (files: File[]) => void;
  disabled?: boolean | undefined;
}) {
  const [dragging, setDragging] = useState(false);
  const handlers = disabled
    ? {}
    : {
        onDragEnter: (event: DragEvent<HTMLElement>) => {
          if (!carriesFiles(event.dataTransfer.types)) return;
          event.preventDefault();
          setDragging(true);
        },
        onDragOver: (event: DragEvent<HTMLElement>) => {
          if (!carriesFiles(event.dataTransfer.types)) return;
          // Without this the browser opens the dropped file instead of handing it to the page.
          event.preventDefault();
          event.dataTransfer.dropEffect = "copy";
        },
        onDragLeave: (event: DragEvent<HTMLElement>) => {
          const next = event.relatedTarget;
          if (next instanceof Node && event.currentTarget.contains(next)) return;
          setDragging(false);
        },
        onDrop: (event: DragEvent<HTMLElement>) => {
          event.preventDefault();
          setDragging(false);
          const dropped = Array.from(event.dataTransfer.files);
          if (dropped.length > 0) onFiles(dropped);
        },
      };
  return { dragging: dragging && !disabled, handlers };
}
