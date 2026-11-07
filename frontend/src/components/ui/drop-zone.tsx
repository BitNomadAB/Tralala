import { useRef, type ReactNode } from "react";
import { cn } from "@/lib/utils";
import { useFileDrop } from "./useFileDrop";

/**
 * A dashed area that takes files: drop them on it, or click it (or press Enter or Space on it) to
 * choose them in the browser's file picker. It marks a drag that carries files; text dragged from
 * the page is left alone. `onFiles` is called once per drop or choice, never with an empty list.
 */
export function DropZone({
  hint,
  detail,
  dragHint = "Drop the files here.",
  accept,
  multiple = true,
  disabled = false,
  pickerLabel = "Choose files",
  onFiles,
  className,
}: {
  /** The line it shows ("Drop a file here, or use Add file."). */
  hint: ReactNode;
  /** A small line under it (what is accepted, the size limit). */
  detail?: ReactNode;
  /** The line it shows while files are dragged over it. */
  dragHint?: ReactNode;
  /** The picker's filter, as the `accept` attribute of a file input (".pdf,.png"). */
  accept?: string | undefined;
  multiple?: boolean | undefined;
  disabled?: boolean | undefined;
  /** The accessible name of the hidden file input. */
  pickerLabel?: string | undefined;
  onFiles: (files: File[]) => void;
  className?: string | undefined;
}) {
  const input = useRef<HTMLInputElement>(null);
  const { dragging, handlers } = useFileDrop({ onFiles, disabled });

  return (
    <>
      <button
        type="button"
        disabled={disabled}
        data-dragging={dragging || undefined}
        onClick={() => input.current?.click()}
        className={cn(
          "grid w-full cursor-pointer justify-items-center gap-1 rounded-lg border border-dashed border-[var(--border)] bg-transparent p-[18px] text-center text-[14px] text-[var(--muted-foreground)] transition-colors hover:border-[var(--foreground-faint)] disabled:cursor-default disabled:opacity-50 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--ring)]",
          dragging && "border-[var(--primary)] bg-[var(--surface-raised)] text-[var(--foreground)]",
          className,
        )}
        {...handlers}
      >
        <span>{dragging ? dragHint : hint}</span>
        {detail === undefined ? null : (
          <small className="text-[12.5px] text-[var(--foreground-faint)]">{detail}</small>
        )}
      </button>
      <input
        ref={input}
        type="file"
        hidden
        multiple={multiple}
        accept={accept}
        aria-label={pickerLabel}
        disabled={disabled}
        onChange={(event) => {
          const chosen = Array.from(event.target.files ?? []);
          // Cleared, so choosing the same file again still reports a change.
          event.target.value = "";
          if (chosen.length > 0) onFiles(chosen);
        }}
      />
    </>
  );
}
