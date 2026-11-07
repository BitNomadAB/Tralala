import {
  CircleAlert,
  CircleCheck,
  Download,
  File as FileIcon,
  FileBraces,
  FileImage,
  FileSpreadsheet,
  FileText,
  LoaderCircle,
  Presentation,
  Trash,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { api } from "@/lib/api";
import { formatSize, isImageType } from "@/lib/api/attachmentRules";
import type { Attachment } from "@/lib/types";
import { formatDateTime } from "@/lib/utils";
import { uploaderText, type UploadEntry } from "./useCardAttachments";

/** The icon a file that shows no thumbnail gets, by the type the server stored. */
function FileTypeIcon({ contentType }: { contentType: string }) {
  const props = { size: 20, "aria-hidden": true } as const;
  if (contentType.startsWith("image/")) return <FileImage {...props} />;
  if (contentType === "application/json") return <FileBraces {...props} />;
  if (contentType.includes("spreadsheet")) return <FileSpreadsheet {...props} />;
  if (contentType.includes("presentation") || contentType.includes("powerpoint")) {
    return <Presentation {...props} />;
  }
  if (
    contentType.startsWith("text/") ||
    contentType.includes("pdf") ||
    contentType.includes("wordprocessing")
  ) {
    return <FileText {...props} />;
  }
  return <FileIcon {...props} />;
}

/**
 * One attached file: a thumbnail for an image (it opens the file in a new tab) or an icon by
 * type, the name, size, who uploaded it and when, a download link, and a delete that asks once.
 */
export function AttachmentRow({
  boardId,
  attachment,
  currentActorId,
  readOnly,
  confirming,
  deleting,
  onAskDelete,
  onKeep,
  onDelete,
}: {
  boardId: string;
  attachment: Attachment;
  currentActorId: string | null | undefined;
  readOnly: boolean;
  confirming: boolean;
  deleting: boolean;
  onAskDelete: () => void;
  onKeep: () => void;
  onDelete: () => void;
}) {
  const name = attachment.original_filename;
  const href = api.attachmentDownloadUrl(boardId, attachment.id);
  return (
    <li className="flex flex-col gap-2 rounded-md bg-[var(--surface-raised)] p-2 text-xs">
      <div className="flex items-center gap-2">
        {isImageType(attachment.content_type) ? (
          <a
            href={href}
            target="_blank"
            rel="noopener noreferrer"
            aria-label={`Open ${name} in a new tab`}
            className="shrink-0"
          >
            <img
              src={href}
              alt=""
              className="h-10 w-10 rounded border border-[var(--border)] object-cover"
            />
          </a>
        ) : (
          <span className="flex h-10 w-10 shrink-0 items-center justify-center text-[var(--muted-foreground)]">
            <FileTypeIcon contentType={attachment.content_type} />
          </span>
        )}
        <div className="min-w-0 flex-1">
          <p className="truncate font-medium" title={name}>
            {name}
          </p>
          <p className="text-[var(--muted-foreground)]">
            {formatSize(attachment.size_bytes)} · Uploaded by{" "}
            {uploaderText(attachment.uploaded_by_actor_id, currentActorId)} ·{" "}
            {formatDateTime(attachment.created_at)}
          </p>
        </div>
        <a
          href={href}
          download={name}
          aria-label={`Download ${name}`}
          className="inline-flex h-8 items-center gap-1 rounded-lg px-2 text-[var(--muted-foreground)] hover:bg-[var(--surface)] hover:text-[var(--foreground)]"
        >
          <Download size={14} aria-hidden="true" /> Download
        </a>
        {readOnly || confirming ? null : (
          <Button variant="ghost" size="sm" aria-label={`Delete ${name}`} onClick={onAskDelete}>
            <Trash size={14} aria-hidden="true" />
          </Button>
        )}
      </div>
      {confirming && !readOnly ? (
        <div className="flex flex-wrap items-center gap-2">
          <span>Delete {name}?</span>
          <Button variant="danger" size="sm" disabled={deleting} onClick={onDelete}>
            {deleting ? "Deleting…" : "Delete"}
          </Button>
          <Button variant="outline" size="sm" disabled={deleting} onClick={onKeep}>
            Keep
          </Button>
        </div>
      ) : null}
    </li>
  );
}

const UPLOAD_TEXT: Record<UploadEntry["status"], string> = {
  waiting: "Waiting",
  uploading: "Uploading…",
  uploaded: "Uploaded",
  refused: "Not sent",
  failed: "Not uploaded",
};

function UploadIcon({ status }: { status: UploadEntry["status"] }) {
  if (status === "uploaded") {
    return <CircleCheck size={14} aria-hidden="true" className="text-[var(--success)]" />;
  }
  if (status === "refused" || status === "failed") {
    return <CircleAlert size={14} aria-hidden="true" className="text-[var(--destructive)]" />;
  }
  return <LoaderCircle size={14} aria-hidden="true" className="animate-spin" />;
}

/** The files a person added in this dialog, each with its own state and its own result. */
export function UploadList({
  uploads,
  busy,
  onClear,
}: {
  uploads: readonly UploadEntry[];
  busy: boolean;
  onClear: () => void;
}) {
  if (uploads.length === 0) return null;
  return (
    <div className="flex flex-col gap-1">
      <ul aria-label="Uploads" aria-live="polite" className="flex flex-col gap-1 text-xs">
        {uploads.map((entry) => (
          <li key={entry.key} className="flex items-start gap-2">
            <span className="mt-0.5">
              <UploadIcon status={entry.status} />
            </span>
            <span className="min-w-0 flex-1">
              <span className="font-medium">{entry.name}</span>: {UPLOAD_TEXT[entry.status]}
              {entry.message ? (
                <span
                  className={
                    entry.status === "refused" || entry.status === "failed"
                      ? "block text-[var(--destructive)]"
                      : "block"
                  }
                >
                  {entry.message}
                </span>
              ) : null}
            </span>
          </li>
        ))}
      </ul>
      {busy ? null : (
        <div>
          <Button variant="ghost" size="sm" onClick={onClear}>
            Clear the list of uploads
          </Button>
        </div>
      )}
    </div>
  );
}
