import { AlertTriangle, CheckCircle2, GitBranch, KeyRound, RefreshCw, Trash2 } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { ReasonButton } from "@/components/ui/reason-button";
import type { Repository } from "@/lib/types";
import { formatBytes, PROVIDER_LABELS } from "./repositoryLabels";
import type { MirrorAction } from "./useRepositoryActions";

function Detail({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex gap-1">
      <dt className="text-[var(--muted-foreground)]">{label}:</dt>
      <dd className="font-mono">{value}</dd>
    </div>
  );
}

/** What Tralala's copy of a `git_https` repository holds, and the two things to do with it. */
function MirrorDetails({
  repository,
  busy,
  onMirror,
}: {
  repository: Repository;
  busy: boolean;
  onMirror: (action: MirrorAction) => void;
}) {
  const busyReason = busy ? "Removing the mirror…" : null;
  const cleanupFailed = repository.mirror_error === "mirror_cleanup_failed";
  const bytes = repository.mirror_bytes;
  return (
    <div className="flex flex-col gap-2 rounded-lg border border-[var(--border)] bg-[var(--surface-raised)] p-2 text-[11px]">
      <dl className="flex flex-wrap gap-x-4 gap-y-1">
        <Detail label="Default branch" value={repository.default_branch ?? "not known yet"} />
        <Detail label="Fetched" value={repository.fetched_at ?? "not yet"} />
        <Detail label="Size" value={typeof bytes === "number" ? formatBytes(bytes) : "no mirror"} />
      </dl>
      {repository.mirror_error ? (
        <p className="flex items-center gap-1.5 text-[var(--warning)]">
          <AlertTriangle size={12} />
          {cleanupFailed
            ? "The mirror could not be removed: the host still holds a file in it."
            : `Last fetch failed: ${repository.mirror_error}`}
        </p>
      ) : null}
      <div className="flex flex-wrap items-center gap-2">
        <ReasonButton
          size="sm"
          variant="outline"
          aria-label={`Rebuild mirror of ${repository.name}`}
          onClick={() => onMirror("rebuild")}
          disabledReason={busyReason}
        >
          <RefreshCw size={13} /> Rebuild mirror
        </ReasonButton>
        {cleanupFailed ? (
          <ReasonButton
            size="sm"
            variant="outline"
            aria-label={`Remove now: mirror of ${repository.name}`}
            onClick={() => onMirror("remove")}
            disabledReason={busyReason}
          >
            <Trash2 size={13} /> Remove now
          </ReasonButton>
        ) : null}
      </div>
    </div>
  );
}

/** One repository in the list: what it is, who uses it, its last check and its commands. */
export function RepositoryRow({
  repository,
  checkId,
  checkText,
  busy,
  onCheck,
  onEdit,
  onRemove,
  onMirror,
}: {
  repository: Repository;
  /** The id of the row's Test access button, where focus goes when a neighbour is removed. */
  checkId: string;
  checkText: string | undefined;
  /** What is under way for this repository; the other rows stay usable meanwhile. */
  busy: { check: boolean; remove: boolean; mirror: boolean };
  onCheck: () => void;
  onEdit: () => void;
  onRemove: () => void;
  onMirror: (action: MirrorAction) => void;
}) {
  const lastCheck =
    checkText ??
    (repository.last_check_detail
      ? `${repository.last_check_status ?? ""}: ${repository.last_check_detail}`
      : null);
  return (
    <li className="card-surface flex flex-col gap-2 p-3">
      <div className="flex flex-wrap items-center gap-2">
        <GitBranch size={14} className="text-[var(--muted-foreground)]" />
        <span className="text-sm font-medium">{repository.name}</span>
        <Badge tone="neutral">{PROVIDER_LABELS[repository.provider]}</Badge>
        {repository.branch ? <Badge tone="neutral">{repository.branch}</Badge> : null}
        {repository.boards.length > 0 ? (
          repository.boards.map((board) => (
            <Badge key={board.id} tone="brand">
              {board.name}
            </Badge>
          ))
        ) : (
          <Badge tone="neutral">no board</Badge>
        )}
        {repository.has_token ? (
          <Badge tone="success">
            <KeyRound size={11} /> {repository.token_hint ?? "token"}
          </Badge>
        ) : (
          <Badge tone="warning">no token</Badge>
        )}
        {!repository.enabled ? <Badge tone="neutral">disabled</Badge> : null}
      </div>
      <p className="break-all text-[11px] text-[var(--muted-foreground)]">{repository.url}</p>
      {lastCheck ? (
        <p className="flex items-center gap-1.5 text-[11px]">
          <CheckCircle2 size={12} className="text-[var(--muted-foreground)]" />
          {lastCheck}
        </p>
      ) : null}
      {repository.provider === "git_https" ? (
        <MirrorDetails repository={repository} busy={busy.mirror} onMirror={onMirror} />
      ) : null}
      <div className="flex flex-wrap items-center gap-2">
        {/* Each name says which repository, as every row has the same three. */}
        <ReasonButton
          id={checkId}
          size="sm"
          variant="outline"
          aria-label={`Test access to ${repository.name}`}
          onClick={onCheck}
          disabledReason={busy.check ? "Testing access…" : null}
        >
          Test access
        </ReasonButton>
        <Button size="sm" variant="ghost" aria-label={`Edit ${repository.name}`} onClick={onEdit}>
          Edit
        </Button>
        <ReasonButton
          size="sm"
          variant="ghost"
          aria-label={`Remove ${repository.name}`}
          onClick={onRemove}
          disabledReason={busy.remove ? "Removing…" : null}
        >
          <Trash2 size={13} /> Remove
        </ReasonButton>
      </div>
    </li>
  );
}
