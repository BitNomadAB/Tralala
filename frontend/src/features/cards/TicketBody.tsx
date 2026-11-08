import { useState, type RefObject } from "react";
import type { MarkdownOptions } from "@/lib/markdown";
import type { ActivityEntry, CardDetail } from "@/lib/types";
import { CardAttachments } from "./CardAttachments";
import { CardComments } from "./CardComments";
import { CardDialogForm } from "./CardDialogForm";
import { CardHistory } from "./CardHistory";
import { CardSummaryNote } from "./CardSummaryNote";
import { CardTicketSummary } from "./CardTicketSummary";
import type { useCardComments } from "./useCardComments";

/**
 * The Ticket's main column as it reads until its redesign: the summary and plan text, the
 * description with its Markdown field, the files, the comments and the history.
 */
export function TicketBody({
  boardId,
  card,
  readOnly,
  actorId,
  live,
  comments,
  history,
  ticketHref,
  picker,
  onSaveDescription,
  refresh,
}: {
  boardId: string;
  card: CardDetail;
  readOnly: boolean;
  actorId: string | undefined;
  live: boolean;
  comments: ReturnType<typeof useCardComments>;
  history: ActivityEntry[];
  ticketHref?: MarkdownOptions["ticketHref"];
  /** The hidden file input, which the head's Add file opens. */
  picker: RefObject<HTMLInputElement | null>;
  onSaveDescription: (description: string) => Promise<boolean>;
  refresh: () => void;
}) {
  // Null until the person types: the field then shows the saved description as it changes.
  const [draft, setDraft] = useState<string | null>(null);
  const [preview, setPreview] = useState(false);
  const [saving, setSaving] = useState(false);
  const description = draft ?? card.description;

  async function save() {
    setSaving(true);
    if (await onSaveDescription(description)) setDraft(null);
    setSaving(false);
  }

  return (
    <div className="grid min-w-0 content-start gap-[30px]">
      <CardSummaryNote card={card} />
      <CardTicketSummary card={card} />
      <CardDialogForm
        description={description}
        onDescriptionChange={setDraft}
        preview={preview}
        onPreviewChange={setPreview}
        dirty={draft !== null && draft !== card.description}
        saving={saving}
        onSave={() => {
          void save();
        }}
        readOnly={readOnly}
        ticketHref={ticketHref}
      />
      <CardAttachments
        boardId={boardId}
        cardId={card.id}
        readOnly={readOnly}
        currentActorId={actorId}
        onChanged={refresh}
        picker={picker}
      />
      <CardComments
        live={live}
        mentions={comments.mentions}
        retrying={comments.retryMention.isPending}
        onRetryMention={(jobId) => comments.retryMention.mutate(jobId)}
        comments={card.comments ?? []}
        comment={comments.comment}
        onCommentChange={comments.changeComment}
        onCommentBlur={comments.closeSuggestions}
        suggestions={comments.suggestions}
        mentionIndex={comments.mentionIndex}
        onMentionIndexChange={comments.setMentionIndex}
        onChooseAgent={comments.chooseAgent}
        commentField={comments.commentField}
        onSubmitComment={(content) => comments.addComment.mutate(content)}
      />
      <CardHistory entries={history} />
    </div>
  );
}
