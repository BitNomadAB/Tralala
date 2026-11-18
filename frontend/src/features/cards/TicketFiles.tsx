import { useRef, type RefObject } from "react";
import { DropZone } from "@/components/ui/drop-zone";
import { Section } from "@/components/ui/section";
import { useAnnounce } from "@/components/ui/useAnnounce";
import { ATTACHMENT_EXTENSIONS, attachmentKindsText } from "@/lib/api/attachmentRules";
import { afterDeletedRow, rowOf } from "./afterDelete";
import { AttachmentRow, UploadList } from "./AttachmentItems";
import { useCardAttachments } from "./useCardAttachments";
import { focusTarget, useFocusAfter } from "./useFocusAfter";

const LINK =
  "rounded border-0 bg-transparent p-0 text-[13px] text-[var(--muted-foreground)] hover:text-[var(--primary)] focus-visible:outline-2 focus-visible:outline-[var(--ring)]";

/**
 * "Files": what is attached to a Ticket and, unless it is read-only, an Add file link and a drop
 * zone that take several files at once, each upload with its own result. The drop zone's picker is
 * `picker` when given, so the Ticket's own Add file opens the same one. Keep gives the focus back
 * to the file's delete button; a delete is announced and hands it to the next file (WCAG 2.4.3).
 */
export function TicketFiles({
  level,
  boardId,
  cardId,
  readOnly,
  currentActorId,
  onChanged,
  picker,
}: {
  /** The heading level of "Files"; h3 unless the host says otherwise. */
  level?: 2 | 3 | undefined;
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
  const announce = useAnnounce();
  const focusAfter = useFocusAfter();
  const body = useRef<HTMLDivElement>(null);
  const deleteButton = (attachmentId: string) =>
    focusTarget(rowOf(body.current, "attachment-id", attachmentId), "delete-file");
  // After a delete: the next file's delete button, else the one before, else the Files heading.
  const afterDeleted = (attachmentId: string) =>
    afterDeletedRow(
      body.current,
      { attribute: "attachment-id", id: attachmentId, target: "delete-file" },
      () => body.current?.closest("section")?.querySelector<HTMLElement>("h2, h3, h4"),
    );

  return (
    <Section
      title="Files"
      level={level}
      focusable
      count={files.attachments.length}
      trailing={
        readOnly ? undefined : (
          <button type="button" className={LINK} onClick={() => input.current?.click()}>
            Add file
          </button>
        )
      }
    >
      <div ref={body} className="grid gap-2.5">
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
                onKeep={() => {
                  files.keep();
                  focusAfter(() => deleteButton(attachment.id));
                }}
                onDelete={() => {
                  void files.confirmDelete(attachment.id).then((deleted) => {
                    if (!deleted) {
                      // The question closed with the refusal: back to the file's delete button.
                      focusAfter(() => deleteButton(attachment.id));
                      return;
                    }
                    announce(`${attachment.original_filename} deleted`);
                    focusAfter(() => afterDeleted(attachment.id));
                  });
                }}
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
