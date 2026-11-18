import { useState } from "react";
import { useToast } from "@/components/ui/useToast";
import { COPY_BY_HAND, copyText } from "./copyText";

/** Focuses the field that shows the secret with its text selected, so Ctrl+C copies all of it. */
export function selectField(fieldId: string): void {
  const field = document.getElementById(fieldId);
  if (!(field instanceof HTMLInputElement)) return;
  field.focus();
  field.select();
}

/**
 * The state of a dialog that shows a secret once (an access token, an invitation link): whether
 * it was copied, whether closing it is being asked about, and what went wrong with a copy. A new
 * `value` starts over. Closing before the secret was copied asks first (WCAG 3.3.4): the server
 * keeps only a hash, so a secret closed away by accident is gone for good.
 */
export function useOneTimeSecret({
  value,
  noun,
  fieldId,
  onClose,
}: {
  value: string;
  /** What the secret is called in the messages: "token", "link". */
  noun: string;
  fieldId: string;
  onClose: () => void;
}) {
  const toast = useToast();
  const [shownFor, setShownFor] = useState(value);
  const [copied, setCopied] = useState(false);
  const [asking, setAsking] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  // A new secret is a new start: adjusted while rendering, as React advises for a changed prop.
  if (shownFor !== value) {
    setShownFor(value);
    setCopied(false);
    setAsking(false);
    setProblem(null);
  }

  function markCopied() {
    setCopied(true);
    setAsking(false);
    setProblem(null);
  }

  return {
    copied,
    asking,
    problem,
    /** Copies through the clipboard; where that fails, selects the text and says what to do. */
    copy: async () => {
      if (await copyText(value)) {
        markCopied();
        toast.push({
          title: `${noun[0]?.toUpperCase() ?? ""}${noun.slice(1)} copied`,
          variant: "success",
        });
        return;
      }
      setProblem(`The browser did not copy the ${noun}. ${COPY_BY_HAND}`);
      selectField(fieldId);
    },
    /** The person copied the selected text themselves (Ctrl+C, the context menu). */
    markCopied,
    /**
     * Escape, a click outside, Close or Done: closes once the secret was copied, otherwise asks.
     * Asked already, the same gesture means "keep it open".
     */
    requestClose: () => {
      if (copied) onClose();
      else if (asking) {
        setAsking(false);
        selectField(fieldId);
      } else setAsking(true);
    },
    keepOpen: () => {
      setAsking(false);
      selectField(fieldId);
    },
  };
}
