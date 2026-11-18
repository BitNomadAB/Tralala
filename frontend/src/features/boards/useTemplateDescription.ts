import { useState } from "react";

/** What choosing a template did to the description the field holds. */
export type TemplateChoice = "replaced" | "kept";

/**
 * Whether choosing a template with `templateText` may replace `current`: only when the person has
 * not written it (`written`), when it is empty, or when it already says the same. Words the person
 * wrote are never replaced by a choice in a list (WCAG 3.3.4), and a template without a
 * description (the blank board) has nothing to offer instead.
 */
export function templateReplaces(current: string, written: boolean, templateText: string): boolean {
  return !written || current.trim() === "" || current === templateText;
}

/**
 * The new board's description and what choosing a template does to it. A template brings its own
 * description, which fills the field while the person has not written in it. Once they have, their
 * words stay and `offer` holds the template's text, for "Use the template's description".
 */
export function useTemplateDescription() {
  const [description, setDescription] = useState("");
  const [written, setWritten] = useState(false);
  const [offer, setOffer] = useState<string | null>(null);

  return {
    description,
    offer,
    /** The person typed in the field. */
    write: (next: string) => {
      setDescription(next);
      setWritten(true);
    },
    /** A template (or the blank board, with "") was chosen. */
    choose: (templateText: string): TemplateChoice => {
      if (templateReplaces(description, written, templateText)) {
        setDescription(templateText);
        setWritten(false);
        setOffer(null);
        return "replaced";
      }
      setOffer(templateText === "" ? null : templateText);
      return "kept";
    },
    /** "Use the template's description": the offered text replaces the person's. */
    takeOffer: () => {
      if (offer === null) return;
      setDescription(offer);
      setWritten(false);
      setOffer(null);
    },
    /** The template choice was reset (the dialog was dismissed): nothing is offered any more. */
    dropOffer: () => {
      setOffer(null);
    },
    /** The board was created: the next one starts empty. */
    clear: () => {
      setDescription("");
      setWritten(false);
      setOffer(null);
    },
  };
}
