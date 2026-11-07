import { Paperclip } from "lucide-react";
import { useId, useRef, useState, type DragEvent } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { ATTACHMENT_EXTENSIONS, ATTACHMENT_MAX_BYTES, formatSize } from "@/lib/api/attachmentRules";
import { cn } from "@/lib/utils";
import { AttachmentRow, UploadList } from "./AttachmentItems";
import { useCardAttachments } from "./useCardAttachments";

/** Whether a drag carries files (not text or a link dragged from the page). */
function carriesFiles(event: DragEvent<HTMLElement>): boolean {
  return Array.from(event.dataTransfer.types).includes("Files");
}

/**
 * "Files": what is attached to a Ticket, and, unless the Ticket is read-only, an Add file button
 * and a drop zone over the whole section that take several files at once. Drag and drop is the
 * browser's own drag events; nothing else is needed for it.
 */
export function CardAttachments({
  boardId,
  cardId,
  readOnly,
  currentActorId,
  onChanged,
}: {
  boardId: string;
  cardId: string;
  readOnly: boolean;
  /** The person looking, so their own uploads read as "you". */
  currentActorId?: string | null | undefined;
  onChanged?: (() => void) | undefined;
}) {
  const headingId = useId();
  const input = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = useState(false);
  const files = useCardAttachments({ boardId, cardId, onChanged });

  const dropHandlers = readOnly
    ? {}
    : {
        onDragEnter: (event: DragEvent<HTMLElement>) => {
          if (!carriesFiles(event)) return;
          event.preventDefault();
          setDragging(true);
        },
        onDragOver: (event: DragEvent<HTMLElement>) => {
          if (!carriesFiles(event)) return;
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
          if (dropped.length > 0) files.addFiles(dropped);
        },
      };

  return (
    <section
      aria-labelledby={headingId}
      className={cn(
        "flex flex-col gap-2 rounded-lg border border-[var(--border)] p-3",
        dragging && "border-dashed border-[var(--primary)] bg-[var(--surface-raised)]",
      )}
      {...dropHandlers}
    >
      <div className="flex flex-wrap items-center gap-2">
        <h3 id={headingId} className="text-sm font-semibold">
          Files
        </h3>
        {files.attachments.length > 0 ? <Badge>{files.attachments.length}</Badge> : null}
        {readOnly ? null : (
          <>
            <Button
              variant="outline"
              size="sm"
              className="ml-auto"
              onClick={() => input.current?.click()}
            >
              <Paperclip size={14} aria-hidden="true" /> Add file
            </Button>
            <input
              ref={input}
              type="file"
              multiple
              hidden
              aria-label="Choose files to attach"
              accept={ATTACHMENT_EXTENSIONS.join(",")}
              onChange={(event) => {
                const chosen = Array.from(event.target.files ?? []);
                // Cleared, so choosing the same file again still reports a change.
                event.target.value = "";
                if (chosen.length > 0) files.addFiles(chosen);
              }}
            />
          </>
        )}
      </div>
      {readOnly ? null : (
        <p className="text-xs text-[var(--muted-foreground)]">
          {dragging
            ? "Drop the files to attach them."
            : `Drop files here or use Add file: ${ATTACHMENT_EXTENSIONS.join(" ")}, up to ${formatSize(ATTACHMENT_MAX_BYTES)} each.`}
        </p>
      )}

      {files.loading ? (
        <p className="text-xs text-[var(--muted-foreground)]">Loading files…</p>
      ) : files.attachments.length === 0 ? (
        files.listError ? null : (
          <p className="text-xs text-[var(--muted-foreground)]">No files yet</p>
        )
      ) : (
        <ul aria-label="Attached files" className="flex flex-col gap-1">
          {files.attachments.map((attachment) => (
            <AttachmentRow
              key={attachment.id}
              boardId={boardId}
              attachment={attachment}
              currentActorId={currentActorId}
              readOnly={readOnly}
              confirming={files.confirming === attachment.id}
              deleting={files.deleting}
              onAskDelete={() => files.askDelete(attachment.id)}
              onKeep={files.keep}
              onDelete={() => files.confirmDelete(attachment.id)}
            />
          ))}
        </ul>
      )}

      <UploadList uploads={files.uploads} busy={files.busy} onClear={files.clearFinished} />

      {files.listError ? (
        <p role="alert" className="text-xs text-[var(--destructive)]">
          {files.listError}
        </p>
      ) : null}
      {files.error ? (
        <p role="alert" className="text-xs text-[var(--destructive)]">
          {files.error}
        </p>
      ) : null}
    </section>
  );
}
