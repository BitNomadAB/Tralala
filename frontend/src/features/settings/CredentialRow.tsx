import { RefreshCw, Trash2 } from "lucide-react";
import { useId } from "react";
import { Badge } from "@/components/ui/badge";
import { HeldButton } from "@/components/ui/held-button";
import { DECIDE_LABEL, holdsDecide } from "@/lib/agentAccess";
import type { Credential } from "@/lib/types";
import { formatDateTime } from "@/lib/utils";
import { CREDENTIAL_TONES, credentialState } from "./credentialState";

/**
 * One agent access key: its scopes, when it was used and when it expires, with rotate and revoke.
 * A button that cannot act (the key is revoked, or the request is under way) stays focusable and
 * says why through `aria-disabled` and its description, so focus is not lost when it turns off.
 */
export function CredentialRow({
  credential,
  showOwner,
  rotating,
  revoking,
  hintId,
  onRotate,
  onRevoke,
}: {
  credential: Credential;
  showOwner: boolean;
  rotating: boolean;
  revoking: boolean;
  /** The id of the visible sentence that says what Rotate and Revoke do. */
  hintId: string;
  onRotate: () => void;
  onRevoke: () => void;
}) {
  const stateId = useId();
  const state = credentialState(credential);
  const revoked = state === "revoked";
  // A revoked key's buttons are described by its "revoked" badge, any other's by what they do.
  const describedBy = revoked ? stateId : hintId;
  return (
    <li className="flex flex-wrap items-center gap-2 py-2.5">
      <div className="min-w-0 flex-1">
        <p className="break-words text-sm font-medium">
          {credential.name}
          {showOwner && credential.owner_name ? (
            <span className="ml-2 text-xs font-normal text-[var(--muted-foreground)]">
              owner {credential.owner_name}
            </span>
          ) : null}
          {showOwner && !credential.owner_name ? (
            <span className="ml-2 text-xs font-normal text-[var(--muted-foreground)]">
              installation-wide
            </span>
          ) : null}
        </p>
        <p className="text-xs text-[var(--muted-foreground)]">
          {credential.scopes.join(", ")} · created {formatDateTime(credential.created_at)}
          {credential.last_used_at
            ? ` · last used ${formatDateTime(credential.last_used_at)}`
            : " · never used"}
          {credential.expires_at
            ? ` · ${state === "expired" ? "expired" : "expires"} ${formatDateTime(credential.expires_at)}`
            : ""}
        </p>
      </div>
      {holdsDecide(credential) ? <Badge tone="warning">{DECIDE_LABEL}</Badge> : null}
      <Badge id={stateId} tone={CREDENTIAL_TONES[state]}>
        {state}
      </Badge>
      <HeldButton
        size="icon"
        variant="ghost"
        aria-label={`Rotate ${credential.name}`}
        aria-describedby={describedBy}
        held={revoked || rotating}
        onClick={onRotate}
      >
        <RefreshCw size={14} />
      </HeldButton>
      <HeldButton
        size="icon"
        variant="ghost"
        aria-label={`Revoke ${credential.name}`}
        aria-describedby={describedBy}
        held={revoked || revoking}
        onClick={onRevoke}
      >
        <Trash2 size={14} />
      </HeldButton>
    </li>
  );
}
