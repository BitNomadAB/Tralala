import { useRef, type RefObject } from "react";
import { DropZone } from "@/components/ui/drop-zone";
import { Section } from "@/components/ui/section";
import { ATTACHMENT_EXTENSIONS, attachmentKindsText } from "@/lib/api/attachmentRules";
import { AttachmentRow, UploadList } from "./AttachmentItems";
import { useCardAttachments } from "./useCardAttachments";

const LINK =
  "rounded border-0 bg-transparent p-0 text-[13px] text-[var(--muted-foreground)] hover:text-[var(--primary)] focus-visible:outline-2 focus-visible:outline-[var(--ring)]";

/**
 * "Files": what is attached to a Ticket and, unless it is read-only, an Add file link and a drop
 * zone that take several files at once, each upload with its own result. The drop zone's picker is
 * `picker` when given, so the Ticket's own Add file opens the same one.
 */
export function TicketFiles({
  boardId,
  cardId,
  readOnly,
  currentActorId,
  onChanged,
  picker,
}: {
  boardId: string;
  cardId: string;
  readOnly: boolean;
  /** The person looking, so their own uploads read as "you". */
  currentActorId?: string | null | undefined;
  onChanged?: (() => void) | undefined;
  /** The file input, when something outside the section (the Ticket's Add file) opens it. */
  picker?: RefObject<HTMLInputElement | null> | undefined;
}) {
  const own = useRef<HTMLInputElement>(null);
  const input = picker ?? own;
  const files = useCardAttachments({ boardId, cardId, onChanged });

  return (
    <Section
      title="Files"
      count={files.attachments.length}
      trailing={
        readOnly ? undefined : (
          <button type="button" className={LINK} onClick={() => input.current?.click()}>
            Add file
          </button>
        )
      }
    >
      <div className="grid gap-2.5">
        {readOnly ? null : (
          <DropZone
            hint="Drop a file here, or use Add file."
            detail={attachmentKindsText()}
            dragHint="Drop the files to attach them."
            accept={ATTACHMENT_EXTENSIONS.join(",")}
            pickerLabel="Choose files to attach"
            inputRef={input}
            onFiles={files.addFiles}
          />
        )}

        {files.loading ? (
          <p className="m-0 text-xs text-[var(--muted-foreground)]">Loading files…</p>
        ) : files.attachments.length === 0 ? (
          files.listError ? null : (
            <p className="m-0 text-xs text-[var(--foreground-faint)]">No files yet</p>
          )
        ) : (
          <ul aria-label="Attached files" className="m-0 flex list-none flex-col gap-1 p-0">
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
          <p role="alert" className="m-0 text-xs text-[var(--destructive)]">
            {files.listError}
          </p>
        ) : null}
        {files.error ? (
          <p role="alert" className="m-0 text-xs text-[var(--destructive)]">
            {files.error}
          </p>
        ) : null}
      </div>
    </Section>
  );
}
