import { useRef, useState } from "react";
import { HeldButton } from "@/components/ui/held-button";
import { MarkdownField } from "@/components/ui/markdown-field";
import { RawBlock as Block, RawText as Raw } from "@/components/ui/raw-text";
import { useAnnounce } from "@/components/ui/useAnnounce";
import type { MarkdownOptions } from "@/lib/markdown";
import type { Card, LoopReadiness } from "@/lib/types";
import { planEntryText } from "./ticketText";
import { useFocusAfter } from "./useFocusAfter";

/** The description's field, which takes the focus when Edit description opens it. */
const FIELD_ID = "card-description";

const LINK =
  "rounded border-0 bg-transparent p-0 text-[13px] text-[var(--muted-foreground)] hover:text-[var(--primary)] focus-visible:outline-2 focus-visible:outline-[var(--ring)]";

/**
 * "Raw text": everything the agent wrote, as it is and unstyled on purpose: the summary for AI,
 * the description's Markdown source (which a person edits here), the acceptance criteria, the
 * evidence and the plan entry. A block with nothing in it is absent. Edit description puts the
 * focus in the field; Save (announced) and Cancel give it back to Edit description.
 */
export function TicketRaw({
  level,
  card,
  readiness,
  readOnly,
  onSaveDescription,
  ticketHref,
}: {
  /** The level of the section around it; each block's label is one level under it. */
  level: 2 | 3;
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
  const blockLevel = level === 2 ? 3 : 4;
  const announce = useAnnounce();
  const focusAfter = useFocusAfter();
  const editButton = useRef<HTMLButtonElement>(null);
  const backToEdit = () => {
    focusAfter(() => editButton.current);
  };
  const item =
    card.plan_item_id === null
      ? undefined
      : readiness?.items.find((entry) => entry.id === card.plan_item_id);

  async function save(text: string) {
    setSaving(true);
    const saved = await onSaveDescription(text);
    setSaving(false);
    if (!saved) return;
    setDraft(null);
    setPreview(false);
    announce("Description saved");
    backToEdit();
  }

  return (
    <div className="grid max-w-[78ch] gap-[18px]">
      <p className="m-0 text-[13px] text-[var(--foreground-faint)]">
        Written by the agent that planned the Loop. Read over /mcp by your coding session. Shown as
        it is, for when you want to dig.
      </p>
      {card.summary ? (
        <Block level={blockLevel} label="Summary for AI">
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
          level={blockLevel}
          label="Description"
          action={
            readOnly || draft !== null ? undefined : (
              <button
                ref={editButton}
                type="button"
                className={LINK}
                onClick={() => {
                  setDraft(card.description);
                  focusAfter(() => document.getElementById(FIELD_ID));
                }}
              >
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
                id={FIELD_ID}
                title="Description"
                label="Card description (Markdown)"
                value={draft}
                onChange={setDraft}
                preview={preview}
                onPreviewChange={setPreview}
                placeholder="Markdown supported"
                ticketHref={ticketHref}
                // The level TicketBody shows the description's headings with.
                headingLevel={blockLevel}
              />
              <div className="flex gap-2">
                <HeldButton
                  size="sm"
                  held={saving}
                  disabled={draft === card.description}
                  onClick={() => void save(draft)}
                >
                  {saving ? "Saving…" : "Save description"}
                </HeldButton>
                <HeldButton
                  variant="quiet"
                  size="sm"
                  held={saving}
                  onClick={() => {
                    setDraft(null);
                    backToEdit();
                  }}
                >
                  Cancel
                </HeldButton>
              </div>
            </div>
          )}
        </Block>
      ) : null}
      {card.acceptance_criteria.length > 0 ? (
        <Block level={blockLevel} label="Accepted when">
          <Raw text={card.acceptance_criteria.join("\n")} />
        </Block>
      ) : null}
      {card.expected_evidence.length > 0 ? (
        <Block level={blockLevel} label="Evidence">
          <Raw text={card.expected_evidence.join("\n")} />
        </Block>
      ) : null}
      {item ? (
        <Block level={blockLevel} label="Plan entry">
          <Raw text={planEntryText(item, readiness)} />
        </Block>
      ) : null}
    </div>
  );
}
