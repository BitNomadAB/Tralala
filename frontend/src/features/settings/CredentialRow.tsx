import { RefreshCw, Trash2 } from "lucide-react";
import { useId, type MouseEvent } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
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
  const guard = (blocked: boolean, action: () => void) => (event: MouseEvent) => {
    if (blocked) event.preventDefault();
    else action();
  };
  return (
    <li className="flex flex-wrap items-center gap-2 py-2.5">
      <div className="min-w-0 flex-1">
        <p className="truncate text-sm font-medium">
          {credential.name}
          {showOwner && credential.owner_name ? (
            <span className="ml-2 text-[11px] font-normal text-[var(--muted-foreground)]">
              owner {credential.owner_name}
            </span>
          ) : null}
          {showOwner && !credential.owner_name ? (
            <span className="ml-2 text-[11px] font-normal text-[var(--muted-foreground)]">
              installation-wide
            </span>
          ) : null}
        </p>
        <p className="text-[11px] text-[var(--muted-foreground)]">
          {credential.scopes.join(", ")} · created {formatDateTime(credential.created_at)}
          {credential.last_used_at
            ? ` · last used ${formatDateTime(credential.last_used_at)}`
            : " · never used"}
          {credential.expires_at
            ? ` · ${state === "expired" ? "expired" : "expires"} ${formatDateTime(credential.expires_at)}`
            : ""}
        </p>
      </div>
      <Badge id={stateId} tone={CREDENTIAL_TONES[state]}>
        {state}
      </Badge>
      <Button
        size="icon"
        variant="ghost"
        aria-label={`Rotate ${credential.name}`}
        aria-describedby={describedBy}
        aria-disabled={revoked || rotating ? true : undefined}
        onClick={guard(revoked || rotating, onRotate)}
      >
        <RefreshCw size={14} />
      </Button>
      <Button
        size="icon"
        variant="ghost"
        aria-label={`Revoke ${credential.name}`}
        aria-describedby={describedBy}
        aria-disabled={revoked || revoking ? true : undefined}
        onClick={guard(revoked || revoking, onRevoke)}
      >
        <Trash2 size={14} />
      </Button>
    </li>
  );
}
