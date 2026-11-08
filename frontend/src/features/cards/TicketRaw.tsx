import { useState } from "react";
import { Button } from "@/components/ui/button";
import { MarkdownField } from "@/components/ui/markdown-field";
import { RawBlock as Block, RawText as Raw } from "@/components/ui/raw-text";
import type { MarkdownOptions } from "@/lib/markdown";
import type { Card, LoopReadiness } from "@/lib/types";
import { planEntryText } from "./ticketText";

const LINK =
  "rounded border-0 bg-transparent p-0 text-[13px] text-[var(--muted-foreground)] hover:text-[var(--primary)] focus-visible:outline-2 focus-visible:outline-[var(--ring)]";

/**
 * "Raw text": everything the agent wrote, as it is and unstyled on purpose: the summary for AI,
 * the description's Markdown source (which a person edits here), the acceptance criteria, the
 * evidence and the plan entry. A block with nothing in it is absent.
 */
export function TicketRaw({
  card,
  readiness,
  readOnly,
  onSaveDescription,
  ticketHref,
}: {
  card: Card;
  readiness: LoopReadiness | undefined;
  readOnly: boolean;
  /** Saves the description with the card's version; resolves true once saved. */
  onSaveDescription: (description: string) => Promise<boolean>;
  ticketHref?: MarkdownOptions["ticketHref"];
}) {
  // Null while the description is read; the text being edited otherwise.
  const [draft, setDraft] = useState<string | null>(null);
  const [preview, setPreview] = useState(false);
  const [saving, setSaving] = useState(false);
  const item =
    card.plan_item_id === null
      ? undefined
      : readiness?.items.find((entry) => entry.id === card.plan_item_id);

  async function save(text: string) {
    setSaving(true);
    if (await onSaveDescription(text)) {
      setDraft(null);
      setPreview(false);
    }
    setSaving(false);
  }

  return (
    <div className="grid max-w-[78ch] gap-[18px]">
      <p className="m-0 text-[13px] text-[var(--foreground-faint)]">
        Written by the agent that planned the Loop. Read over /mcp by your coding session. Shown as
        it is, for when you want to dig.
      </p>
      {card.summary ? (
        <Block label="Summary for AI">
          <Raw text={card.summary} />
          {card.summary_source === "agent" ? (
            <p className="m-0 mt-1 text-xs text-[var(--foreground-faint)]">Written by an agent.</p>
          ) : null}
          {card.summary_stale ? (
            <p className="m-0 mt-1 text-xs text-[var(--warning)]">
              The Ticket changed after this summary was written; it may be out of date.
            </p>
          ) : null}
        </Block>
      ) : null}
      {card.description || !readOnly ? (
        <Block
          label="Description"
          action={
            readOnly || draft !== null ? undefined : (
              <button type="button" className={LINK} onClick={() => setDraft(card.description)}>
                Edit description
              </button>
            )
          }
        >
          {draft === null ? (
            card.description ? (
              <Raw text={card.description} />
            ) : (
              <p className="m-0 text-xs text-[var(--foreground-faint)]">No description.</p>
            )
          ) : (
            <div className="grid gap-2">
              <MarkdownField
                id="card-description"
                title="Description"
                label="Card description (Markdown)"
                value={draft}
                onChange={setDraft}
                preview={preview}
                onPreviewChange={setPreview}
                placeholder="Markdown supported"
                ticketHref={ticketHref}
              />
              <div className="flex gap-2">
                <Button
                  size="sm"
                  disabled={saving || draft === card.description}
                  onClick={() => void save(draft)}
                >
                  {saving ? "Saving…" : "Save description"}
                </Button>
                <Button variant="quiet" size="sm" disabled={saving} onClick={() => setDraft(null)}>
                  Cancel
                </Button>
              </div>
            </div>
          )}
        </Block>
      ) : null}
      {card.acceptance_criteria.length > 0 ? (
        <Block label="Accepted when">
          <Raw text={card.acceptance_criteria.join("\n")} />
        </Block>
      ) : null}
      {card.expected_evidence.length > 0 ? (
        <Block label="Evidence">
          <Raw text={card.expected_evidence.join("\n")} />
        </Block>
      ) : null}
      {item ? (
        <Block label="Plan entry">
          <Raw text={planEntryText(item, readiness)} />
        </Block>
      ) : null}
    </div>
  );
}
