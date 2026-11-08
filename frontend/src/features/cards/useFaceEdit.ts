import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { ApiError, api } from "@/lib/api";
import { describeError } from "@/lib/describeError";
import { keys } from "@/lib/queries";
import type { Card, CardDetail } from "@/lib/types";
import {
  draftOf,
  faceCounts,
  faceErrors,
  faceOf,
  type FaceDraft,
  type FaceErrors,
} from "./faceLimits";
import { CONFLICT_TEXT } from "./useTicketActions";

const NO_ERRORS: FaceErrors = { fields: {}, other: [] };

/**
 * A person's edit of the Ticket's face: the draft opened from the face as it is, the live
 * counters, and Save, which sends the whole face with the card's version. A `422 face_invalid`
 * keeps the draft open with each message under its field; a `409` says to reload. Once saved, the
 * answer is written into the card's query and the draft closes.
 */
export function useFaceEdit({
  boardId,
  loopId,
  card,
  refresh,
}: {
  boardId: string;
  loopId: string;
  card: Card;
  refresh: () => void;
}) {
  const queryClient = useQueryClient();
  // Null while the face is read; the draft once the person clicked Edit.
  const [draft, setDraft] = useState<FaceDraft | null>(null);
  const [errors, setErrors] = useState<FaceErrors>(NO_ERRORS);

  const save = useMutation({
    mutationFn: (value: FaceDraft) =>
      api.updateFace(boardId, loopId, card.id, { version: card.version, ...faceOf(value) }),
    onMutate: () => {
      setErrors(NO_ERRORS);
    },
    onSuccess: (updated: Card) => {
      queryClient.setQueryData<CardDetail>(keys.card(boardId, loopId, card.id), (current) =>
        current ? { ...current, ...updated } : updated,
      );
      setDraft(null);
      refresh();
    },
    onError: (error: unknown) => {
      const refused = faceErrors(error);
      if (refused) {
        setErrors(refused);
        return;
      }
      const conflict = error instanceof ApiError && error.code === "version_conflict";
      setErrors({
        fields: {},
        other: [conflict ? CONFLICT_TEXT : describeError(error, "The face was not saved.")],
      });
    },
  });

  return {
    editing: draft !== null,
    draft,
    counts: draft ? faceCounts(draft) : null,
    errors,
    saving: save.isPending,
    open: () => {
      setErrors(NO_ERRORS);
      setDraft(draftOf(card.face, card.summary));
    },
    change: (field: keyof FaceDraft, value: string) => {
      setDraft((current) => (current ? { ...current, [field]: value } : current));
    },
    cancel: () => {
      setDraft(null);
      setErrors(NO_ERRORS);
    },
    save: () => {
      if (draft) save.mutate(draft);
    },
  };
}
