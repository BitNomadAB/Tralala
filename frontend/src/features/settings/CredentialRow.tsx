import { RefreshCw, Trash2 } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import type { Credential } from "@/lib/types";
import { formatDateTime } from "@/lib/utils";

/** One agent access key: its scopes, when it was used and when it expires, with rotate and revoke. */
export function CredentialRow({
  credential,
  showOwner,
  rotating,
  onRotate,
  onRevoke,
}: {
  credential: Credential;
  showOwner: boolean;
  rotating: boolean;
  onRotate: () => void;
  onRevoke: () => void;
}) {
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
          {credential.expires_at ? ` · expires ${formatDateTime(credential.expires_at)}` : ""}
        </p>
      </div>
      <Badge tone={credential.revoked_at ? "danger" : "success"}>
        {credential.revoked_at ? "revoked" : "active"}
      </Badge>
      <Button
        size="icon"
        variant="ghost"
        aria-label={`Rotate ${credential.name}`}
        title="Rotate: issue a new token and revoke this one"
        disabled={Boolean(credential.revoked_at) || rotating}
        onClick={onRotate}
      >
        <RefreshCw size={14} />
      </Button>
      <Button
        size="icon"
        variant="ghost"
        aria-label={`Revoke ${credential.name}`}
        title="Revoke"
        disabled={Boolean(credential.revoked_at)}
        onClick={onRevoke}
      >
        <Trash2 size={14} />
      </Button>
    </li>
  );
}
