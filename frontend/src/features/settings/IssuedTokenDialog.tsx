import type { Credential } from "@/lib/types";
import { OneTimeSecretDialog } from "./OneTimeSecretDialog";

/** Shows a newly issued token once; the server keeps only its hash. */
export function IssuedTokenDialog({
  issued,
  returnFocusId,
  onClose,
}: {
  issued: Credential | null;
  /** Where focus goes on closing, when what opened it is gone (the New access key dialog). */
  returnFocusId?: string | null | undefined;
  onClose: () => void;
}) {
  return (
    <OneTimeSecretDialog
      value={issued ? (issued.token ?? "") : null}
      title="Copy this token now"
      description="The server stores only a hash. It cannot be shown again."
      label="New API token"
      noun="token"
      returnFocusId={returnFocusId}
      onClose={onClose}
    >
      <p className="text-xs text-[var(--muted-foreground)]">
        Paste it into your MCP client as <code>Authorization: Bearer &lt;token&gt;</code>. The card
        above now shows the config with this token filled in.
      </p>
    </OneTimeSecretDialog>
  );
}
