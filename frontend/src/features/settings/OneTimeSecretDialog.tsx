import { Copy } from "lucide-react";
import { useId, type ReactNode } from "react";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent } from "@/components/ui/dialog";
import { Field, Input } from "@/components/ui/input";
import { focusById } from "./removalFocus";
import { selectField, useOneTimeSecret } from "./useOneTimeSecret";

/**
 * A dialog that shows a secret once: an access token, an invitation link. It opens on the secret
 * with its text selected, not on the header's Close button, so Enter or Escape cannot throw it
 * away at once (WCAG 2.4.3, 3.3.4). Closing it before it was copied asks first, inside the
 * dialog; copying says whether it worked, and where the browser cannot copy, what to do instead.
 */
export function OneTimeSecretDialog({
  value,
  title,
  description,
  label,
  noun,
  hint,
  returnFocusId,
  onClose,
  children,
}: {
  /** The secret; null while there is none, which keeps the dialog closed. */
  value: string | null;
  title: string;
  description: string;
  /** The field's label: "New API token", "Link". */
  label: string;
  /** What the secret is called in the messages: "token", "link". */
  noun: string;
  hint?: string | undefined;
  /** Where focus goes on closing when what opened the dialog is gone (another dialog). */
  returnFocusId?: string | null | undefined;
  onClose: () => void;
  /** What to do with the secret, under the field. */
  children?: ReactNode;
}) {
  const fieldId = useId();
  const questionId = useId();
  const secret = useOneTimeSecret({ value: value ?? "", noun, fieldId, onClose });

  return (
    <Dialog
      open={value !== null}
      onOpenChange={(open) => {
        if (!open) secret.requestClose();
      }}
    >
      <DialogContent
        title={title}
        description={description}
        onOpenAutoFocus={(event) => {
          event.preventDefault();
          selectField(fieldId);
        }}
        onCloseAutoFocus={(event) => {
          if (!returnFocusId) return;
          event.preventDefault();
          focusById(returnFocusId);
        }}
      >
        <div className="flex flex-col gap-3">
          <Field label={label} htmlFor={fieldId} hint={secret.problem ?? hint}>
            <Input
              id={fieldId}
              readOnly
              value={value ?? ""}
              className="font-mono text-xs"
              onFocus={(event) => event.currentTarget.select()}
              onCopy={secret.markCopied}
            />
          </Field>
          <div>
            <Button
              variant="secondary"
              size="sm"
              onClick={() => {
                void secret.copy();
              }}
            >
              <Copy size={14} aria-hidden="true" /> Copy {noun}
            </Button>
          </div>
          {children}
          {secret.asking ? (
            <div
              role="group"
              aria-labelledby={questionId}
              className="rounded-lg border border-[var(--warning)] p-3"
            >
              <p id={questionId} className="text-sm font-medium">
                You have not copied the {noun}. Close anyway?
              </p>
              <p className="mt-0.5 text-xs text-[var(--muted-foreground)]">
                It cannot be shown again.
              </p>
              <div className="mt-3 flex justify-end gap-2">
                <Button variant="ghost" onClick={onClose}>
                  Close anyway
                </Button>
                <Button autoFocus onClick={secret.keepOpen}>
                  Keep open
                </Button>
              </div>
            </div>
          ) : (
            <div className="flex justify-end">
              <Button onClick={secret.requestClose}>Done</Button>
            </div>
          )}
        </div>
      </DialogContent>
    </Dialog>
  );
}
