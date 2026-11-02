import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Copy, KeyRound, RefreshCw, ShieldCheck, Trash2 } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent } from "@/components/ui/dialog";
import { Field, Input } from "@/components/ui/input";
import { useToast } from "@/components/ui/toast";
import { ApiError, api } from "@/lib/api";
import { formatDateTime } from "@/lib/utils";
import type { Credential } from "@/lib/types";
import { AgentAccessGuide } from "./AgentAccessGuide";
import { scopeChoicesFor } from "@/lib/agentAccess";

interface InteractionAccessCardProps {
  isAdmin: boolean;
  currentUserId: string;
}

/**
 * A person's own agent access, plus the installation-wide view for an administrator.
 *
 * A token is the identity an agent connects with, so this card is deliberately explicit about what a
 * key can do: the scopes it holds, when it last connected, and when it stops working.
 */
export function InteractionAccessCard({ isAdmin, currentUserId }: InteractionAccessCardProps) {
  const queryClient = useQueryClient();
  const toast = useToast();
  const metaQuery = useQuery({
    queryKey: ["api-meta"],
    queryFn: () => api.meta(),
    staleTime: 5 * 60_000,
  });
  const credentialsQuery = useQuery({
    queryKey: ["credentials", isAdmin ? "all" : "mine"],
    queryFn: () => (isAdmin ? api.listCredentials() : api.listMyCredentials()),
  });

  const scopeChoices = useMemo(
    () => scopeChoicesFor(isAdmin, metaQuery.data),
    [isAdmin, metaQuery.data],
  );
  const limits = metaQuery.data?.member_token_limits;
  const defaultExpiry = String(isAdmin ? 90 : (limits?.default_days ?? 30));
  const expiryHint = isAdmin
    ? "Defaults to 90 days. Use 0 for a token that never expires."
    : `Your access expires after ${limits?.default_days ?? 30} days by default and never lasts longer than ${limits?.max_days ?? 365}.`;

  const [creating, setCreating] = useState(false);
  const [name, setName] = useState("");
  const [scopes, setScopes] = useState<string[]>([]);
  const [expires, setExpires] = useState(defaultExpiry);
  const [issued, setIssued] = useState<Credential | null>(null);

  const credentials = credentialsQuery.data ?? [];
  const mine = isAdmin
    ? credentials.filter((entry) => entry.owner_actor_id === currentUserId)
    : credentials;
  const others = isAdmin
    ? credentials.filter((entry) => entry.owner_actor_id !== currentUserId)
    : [];

  function invalidate() {
    queryClient.invalidateQueries({ queryKey: ["credentials"] });
    queryClient.invalidateQueries({ queryKey: ["users"] });
  }

  const createMutation = useMutation({
    mutationFn: () =>
      api.createCredential({
        name: name.trim(),
        scopes,
        expires_in_days: expires.trim() === "" ? undefined : Number(expires),
      }),
    onSuccess: (credential) => {
      setIssued(credential);
      setCreating(false);
      setName("");
      invalidate();
    },
    onError: (error) =>
      toast.push({
        title: "Could not create the agent access",
        description: error instanceof ApiError ? error.message : undefined,
        variant: "error",
      }),
  });

  const revokeMutation = useMutation({
    mutationFn: (credential: Credential) => api.revokeCredential(credential.id),
    onSuccess: () => {
      invalidate();
      toast.push({ title: "Agent access revoked", variant: "success" });
    },
  });

  const rotateMutation = useMutation({
    mutationFn: (credential: Credential) => api.rotateCredential(credential.id),
    onSuccess: (credential) => {
      setIssued(credential);
      invalidate();
      toast.push({
        title: "Agent access rotated",
        description: "The previous token stopped working.",
      });
    },
    onError: (error) =>
      toast.push({
        title: "Could not rotate the access",
        description: error instanceof ApiError ? error.message : undefined,
        variant: "error",
      }),
  });

  function openCreate() {
    // Start from the smallest useful set instead of the first N scopes in the catalogue, and keep it
    // when the scope list is still loading: both are valid for every role.
    const candidates = ["boards:read", "cards:read"];
    const known = scopeChoices.length > 0 ? scopeChoices : candidates;
    setScopes(candidates.filter((scope) => known.includes(scope)));
    setExpires(defaultExpiry);
    setCreating(true);
  }

  function renderRow(credential: Credential, showOwner: boolean) {
    return (
      <li key={credential.id} className="flex flex-wrap items-center gap-2 py-2.5">
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
          disabled={Boolean(credential.revoked_at) || rotateMutation.isPending}
          onClick={() => rotateMutation.mutate(credential)}
        >
          <RefreshCw size={14} />
        </Button>
        <Button
          size="icon"
          variant="ghost"
          aria-label={`Revoke ${credential.name}`}
          title="Revoke"
          disabled={Boolean(credential.revoked_at)}
          onClick={() => revokeMutation.mutate(credential)}
        >
          <Trash2 size={14} />
        </Button>
      </li>
    );
  }

  return (
    <>
      <div className="card-surface p-5">
        <div className="flex flex-wrap items-center gap-2">
          <h2 className="text-sm font-semibold">Interaction agent access</h2>
          <Badge tone="brand">you</Badge>
          <Button size="sm" className="ml-auto" onClick={openCreate}>
            <KeyRound size={14} /> New access key
          </Button>
        </div>
        <p className="mt-1 text-xs text-[var(--muted-foreground)]">
          A key for an agent on your own machine. It can read boards, open Loops, write the Info you
          agree on, ask the local agents and track Tickets — never approve a plan, manage accounts or
          change a board&apos;s structure. The key is shown once; &quot;last used&quot; is how you
          recognise which machine is connected.
        </p>

        <div className="mt-2">
          <AgentAccessGuide
            token={issued?.token}
            onCopy={async (snippet) => {
              await navigator.clipboard.writeText(snippet);
              toast.push({ title: "MCP configuration copied", variant: "success" });
            }}
          />
        </div>
        <ul className="mt-3 divide-y divide-[var(--border)]">
          {credentialsQuery.isLoading ? (
            <li className="py-2.5 text-xs text-[var(--muted-foreground)]">Loading…</li>
          ) : null}
          {mine.map((credential) => renderRow(credential, false))}
          {!credentialsQuery.isLoading && mine.length === 0 ? (
            <li className="py-2.5 text-xs text-[var(--muted-foreground)]">
              No agent access yet.
            </li>
          ) : null}
        </ul>
      </div>

      {isAdmin ? (
        <div className="card-surface p-5">
          <h2 className="text-sm font-semibold">All agent access</h2>
          <p className="mt-1 text-xs text-[var(--muted-foreground)]">
            Every key in the installation. Disabling a person under Users also revokes their access
            here.
          </p>
          <ul className="mt-3 divide-y divide-[var(--border)]">
            {others.map((credential) => renderRow(credential, true))}
            {!credentialsQuery.isLoading && others.length === 0 ? (
              <li className="py-2.5 text-xs text-[var(--muted-foreground)]">
                No other agent access yet.
              </li>
            ) : null}
          </ul>
          <p className="mt-3 text-[11px] text-[var(--muted-foreground)]">
            Yours may hold any grantable scope: <code>{scopeChoices.join(", ")}</code>
          </p>
        </div>
      ) : null}

      <Dialog open={creating} onOpenChange={setCreating}>
        <DialogContent
          title="New interaction agent access"
          description="Scopes decide what the agent may do. Grant what it needs, nothing more."
        >
          <form
            className="flex flex-col gap-3"
            onSubmit={(event) => {
              event.preventDefault();
              if (name.trim() && scopes.length > 0) createMutation.mutate();
            }}
          >
            <Field
              label="Agent name"
              htmlFor="credential-name"
              hint="Name it after the machine that will hold the key."
            >
              <Input
                id="credential-name"
                value={name}
                onChange={(event) => setName(event.target.value)}
                required
                maxLength={200}
              />
            </Field>
            <fieldset className="flex flex-col gap-1.5">
              <legend className="text-xs font-medium uppercase tracking-wide text-[var(--muted-foreground)]">
                Scopes
              </legend>
              {scopeChoices.map((scope) => (
                <label key={scope} className="flex items-center gap-2 text-sm">
                  <input
                    type="checkbox"
                    checked={scopes.includes(scope)}
                    onChange={(event) =>
                      setScopes((current) =>
                        event.target.checked
                          ? [...current, scope]
                          : current.filter((value) => value !== scope),
                      )
                    }
                  />
                  {scope}
                </label>
              ))}
            </fieldset>
            <Field label="Expires in days" htmlFor="credential-expiry" hint={expiryHint}>
              <Input
                id="credential-expiry"
                type="number"
                min={isAdmin ? 0 : 1}
                max={3650}
                value={expires}
                onChange={(event) => setExpires(event.target.value)}
              />
            </Field>
            <div className="flex justify-end gap-2">
              <Button variant="ghost" onClick={() => setCreating(false)}>
                Cancel
              </Button>
              <Button type="submit" disabled={!name.trim() || scopes.length === 0}>
                <ShieldCheck size={14} /> Create access
              </Button>
            </div>
          </form>
        </DialogContent>
      </Dialog>

      <Dialog open={Boolean(issued)} onOpenChange={(open) => !open && setIssued(null)}>
        <DialogContent
          title="Copy this token now"
          description="The server stores only a hash. It cannot be shown again."
        >
          <div className="flex items-center gap-2">
            <Input readOnly value={issued?.token ?? ""} aria-label="New API token" />
            <Button
              size="icon"
              variant="secondary"
              aria-label="Copy token"
              onClick={async () => {
                if (!issued?.token) return;
                await navigator.clipboard.writeText(issued.token);
                toast.push({ title: "Token copied", variant: "success" });
              }}
            >
              <Copy size={14} />
            </Button>
          </div>
          <p className="mt-3 text-[11px] text-[var(--muted-foreground)]">
            Paste it into your MCP client as{" "}
            <code>Authorization: Bearer &lt;token&gt;</code>. The card above now shows the config
            with this token filled in.
          </p>
          <div className="mt-3 flex justify-end">
            <Button onClick={() => setIssued(null)}>Done</Button>
          </div>
        </DialogContent>
      </Dialog>
    </>
  );
}
