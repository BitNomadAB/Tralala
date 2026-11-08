/**
 * What the server accepts as a Ticket attachment, checked before a file is sent so a person is not
 * made to wait for a refusal the client can already see. The server stays the authority: it also
 * checks the first bytes against the extension and the board's total, and its 422/413 is shown as
 * it words it.
 */

/**
 * Extension -> content type, as `ALLOWED_TYPES` in `backend/app/services/attachments.py`:
 * .docx .ppt .pptx .xlsx .pdf .txt .md .json .jpg .jpeg .png .gif.
 */
export const ATTACHMENT_TYPES: Readonly<Record<string, string>> = {
  ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
  ".ppt": "application/vnd.ms-powerpoint",
  ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
  ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
  ".pdf": "application/pdf",
  ".txt": "text/plain",
  ".md": "text/markdown",
  ".json": "application/json",
  ".jpg": "image/jpeg",
  ".jpeg": "image/jpeg",
  ".png": "image/png",
  ".gif": "image/gif",
};

/** The extensions in the order the server lists them, for the file picker and the reason. */
export const ATTACHMENT_EXTENSIONS: readonly string[] = Object.keys(ATTACHMENT_TYPES);

/**
 * One file's limit: `attachment_max_bytes` in `backend/app/core/config.py`, 8 MiB by default
 * (`TRALALA_ATTACHMENT_MAX_BYTES`), the same as the request ceiling. The board's total,
 * `board_attachment_max_bytes` (200 MiB, `TRALALA_BOARD_ATTACHMENT_MAX_BYTES`), depends on what
 * the board holds, so only the server can check it.
 */
export const ATTACHMENT_MAX_BYTES = 8 * 1024 * 1024;

/** The content types that show a thumbnail. */
const IMAGE_TYPES: ReadonlySet<string> = new Set(["image/jpeg", "image/png", "image/gif"]);

export function isImageType(contentType: string): boolean {
  return IMAGE_TYPES.has(contentType);
}

/**
 * A file name's extension as the server reads it: lower case, after the leading dots it strips
 * from a name ("" when there is none).
 */
export function extensionOf(name: string): string {
  const bare = name.replace(/^\.+/, "");
  const dot = bare.lastIndexOf(".");
  return dot > 0 ? bare.slice(dot).toLowerCase() : "";
}

/** A size in a readable unit: bytes below 1 KB, then KB or MB with one decimal (1 KB = 1024 B). */
export function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

/** Why the server would refuse this file, or null when it may be sent. */
export function attachmentRefusal(file: Pick<File, "name" | "size">): string | null {
  if (!Object.hasOwn(ATTACHMENT_TYPES, extensionOf(file.name))) {
    return `This type of file cannot be attached. Allowed: ${ATTACHMENT_EXTENSIONS.join(" ")}.`;
  }
  if (file.size === 0) return "The file is empty.";
  if (file.size > ATTACHMENT_MAX_BYTES) {
    return `The file is ${formatSize(file.size)}; the limit is ${formatSize(ATTACHMENT_MAX_BYTES)} per file.`;
  }
  return null;
}

/**
 * The `Content-Type` an upload declares: the file's own type, or the allowlist's for its
 * extension when the browser gives none (it often does not for .md).
 */
export function uploadContentType(file: Pick<File, "name" | "type">): string {
  return (file.type || ATTACHMENT_TYPES[extensionOf(file.name)]) ?? "application/octet-stream";
}

/** What a person calls each accepted extension, for the line under a drop zone. */
const KINDS: Readonly<Record<string, string>> = {
  ".docx": "documents",
  ".ppt": "presentations",
  ".pptx": "presentations",
  ".xlsx": "spreadsheets",
  ".pdf": "PDF",
  ".txt": "text",
  ".md": "Markdown",
  ".json": "JSON",
  ".jpg": "images",
  ".jpeg": "images",
  ".png": "images",
  ".gif": "images",
};

/**
 * The kinds of file the server accepts and the size limit, in words: "Documents, presentations,
 * spreadsheets, PDF, text, Markdown, JSON and images, up to 8 MB each." An extension without a
 * word of its own is named as it is.
 */
export function attachmentKindsText(): string {
  const kinds = [...new Set(ATTACHMENT_EXTENSIONS.map((ext) => KINDS[ext] ?? ext))];
  const last = kinds.pop() ?? "";
  const named = kinds.length > 0 ? `${kinds.join(", ")} and ${last}` : last;
  const size = formatSize(ATTACHMENT_MAX_BYTES).replace(".0 ", " ");
  return `${named.charAt(0).toUpperCase()}${named.slice(1)}, up to ${size} each.`;
}
