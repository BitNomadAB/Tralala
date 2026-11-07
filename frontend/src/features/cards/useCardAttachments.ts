import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useRef, useState } from "react";
import { ApiError, api } from "@/lib/api";
import { attachmentRefusal } from "@/lib/api/attachmentRules";
import { describeError } from "@/lib/describeError";
import { keys } from "@/lib/queries";
import type { Attachment } from "@/lib/types";

/** What the server could not be asked: the request never came back. */
export const NETWORK_HINT = "The server could not be reached. Check the connection and try again.";

/**
 * What a refused or failed attachment request reads as: a 409 is the Ticket's Loop refusing
 * writes, a 422/413 is the server's own words, anything that is not the API's is the network.
 */
export function attachmentErrorText(error: unknown): string {
  if (error instanceof ApiError) {
    return error.status === 409 ? "This Ticket is read-only." : describeError(error);
  }
  return NETWORK_HINT;
}

/** Who uploaded a file: "you" for the person looking, else the actor id the entry carries. */
export function uploaderText(actorId: string, currentActorId: string | null | undefined): string {
  return currentActorId && actorId === currentActorId ? "you" : actorId;
}

/** One file a person chose or dropped, from the moment it is checked until it has its answer. */
export interface UploadEntry {
  key: string;
  name: string;
  status: "waiting" | "uploading" | "uploaded" | "refused" | "failed";
  /** The reason for `refused` (checked here) or `failed` (the server's answer). */
  message: string | null;
}

/**
 * A Ticket's files: the list from its query, uploads one after another with a result each, and a
 * delete that asks once. A successful change writes into the list's query at once and calls
 * `onChanged`, so the dialog refetches what records it (the Ticket's activity).
 */
export function useCardAttachments({
  boardId,
  cardId,
  onChanged,
}: {
  boardId: string;
  cardId: string;
  onChanged?: (() => void) | undefined;
}) {
  const queryClient = useQueryClient();
  const queryKey = keys.attachments(boardId, cardId);
  const list = useQuery({
    queryKey,
    queryFn: () => api.listAttachments(boardId, cardId),
    enabled: Boolean(boardId && cardId),
  });
  const [uploads, setUploads] = useState<UploadEntry[]>([]);
  const [confirming, setConfirming] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  // Files added while others are still uploading wait behind them, so the order is the person's.
  const queue = useRef<Promise<void>>(Promise.resolve());
  const counter = useRef(0);

  const upload = useMutation({
    mutationFn: (file: File) => api.uploadAttachment(boardId, cardId, file),
    onSuccess: (row: Attachment) => {
      queryClient.setQueryData<Attachment[]>(queryKey, (current) => [...(current ?? []), row]);
      onChanged?.();
    },
  });

  const remove = useMutation({
    mutationFn: (attachmentId: string) => api.deleteAttachment(boardId, attachmentId),
    onMutate: () => {
      setError(null);
    },
    onSuccess: (_answer, attachmentId) => {
      setConfirming(null);
      queryClient.setQueryData<Attachment[]>(queryKey, (current) =>
        (current ?? []).filter((row) => row.id !== attachmentId),
      );
      onChanged?.();
    },
    onError: (mutationError: unknown) => {
      setConfirming(null);
      setError(attachmentErrorText(mutationError));
    },
  });

  function update(key: string, changes: Partial<UploadEntry>) {
    setUploads((current) =>
      current.map((entry) => (entry.key === key ? { ...entry, ...changes } : entry)),
    );
  }

  async function send(key: string, file: File) {
    update(key, { status: "uploading" });
    try {
      await upload.mutateAsync(file);
      update(key, { status: "uploaded" });
    } catch (uploadError) {
      update(key, { status: "failed", message: attachmentErrorText(uploadError) });
    }
  }

  /** Checks every file, then sends the ones that pass, one after another. */
  function addFiles(files: readonly File[]) {
    const checked = files.map((file) => {
      counter.current += 1;
      const refusal = attachmentRefusal(file);
      const entry: UploadEntry = {
        key: `upload-${counter.current}`,
        name: file.name,
        status: refusal ? "refused" : "waiting",
        message: refusal,
      };
      return { entry, file };
    });
    setUploads((current) => [...current, ...checked.map(({ entry }) => entry)]);
    for (const { entry, file } of checked) {
      if (entry.status === "waiting") {
        queue.current = queue.current.then(() => send(entry.key, file));
      }
    }
  }

  const busy = uploads.some((entry) => entry.status === "waiting" || entry.status === "uploading");

  return {
    attachments: list.data ?? [],
    loading: list.isLoading,
    listError: list.error ? attachmentErrorText(list.error) : null,
    uploads,
    busy,
    addFiles,
    /** Drops the entries that have their answer; the uploaded ones are in the list. */
    clearFinished: () => {
      setUploads((current) =>
        current.filter((entry) => entry.status === "waiting" || entry.status === "uploading"),
      );
    },
    error,
    confirming,
    askDelete: (attachmentId: string) => {
      setError(null);
      setConfirming(attachmentId);
    },
    keep: () => {
      setConfirming(null);
    },
    confirmDelete: (attachmentId: string) => {
      remove.mutate(attachmentId);
    },
    deleting: remove.isPending,
  };
}
