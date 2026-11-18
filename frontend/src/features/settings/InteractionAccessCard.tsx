import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { KeyRound } from "lucide-react";
import { useMemo, useState } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { useToast } from "@/components/ui/useToast";
import { scopeChoicesFor } from "@/lib/agentAccess";
import { api } from "@/lib/api";
import { describeError } from "@/lib/describeError";
import type { Credential } from "@/lib/types";
import { AgentAccessGuide } from "./AgentAccessGuide";
import { CredentialRow } from "./CredentialRow";
import { IssuedTokenDialog } from "./IssuedTokenDialog";
import { NewAccessDialog } from "./NewAccessDialog";

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
  const [issued, setIssued] = useState<Credential | null>(null);

  const credentials = credentialsQuery.data ?? [];
  const mine = isAdmin
    ? credentials.filter((entry) => entry.owner_actor_id === currentUserId)
    : credentials;
  const others = isAdmin
    ? credentials.filter((entry) => entry.owner_actor_id !== currentUserId)
    : [];

  function invalidate() {
    void queryClient.invalidateQueries({ queryKey: ["credentials"] });
    void queryClient.invalidateQueries({ queryKey: ["users"] });
  }

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
    onError: (error) => {
      toast.push({
        title: "Could not rotate the access",
        description: describeError(error, undefined),
        variant: "error",
      });
    },
  });

  async function copySnippet(snippet: string) {
    await navigator.clipboard.writeText(snippet);
    toast.push({ title: "MCP configuration copied", variant: "success" });
  }

  async function copyToken() {
    if (!issued?.token) return;
    await navigator.clipboard.writeText(issued.token);
    toast.push({ title: "Token copied", variant: "success" });
  }

  function renderRow(credential: Credential, showOwner: boolean) {
    return (
      <CredentialRow
        key={credential.id}
        credential={credential}
        showOwner={showOwner}
        rotating={rotateMutation.isPending}
        onRotate={() => rotateMutation.mutate(credential)}
        onRevoke={() => revokeMutation.mutate(credential)}
      />
    );
  }

  return (
    <>
      <div className="card-surface p-5">
        <div className="flex flex-wrap items-center gap-2">
          <h2 className="text-sm font-semibold">Interaction agent access</h2>
          <Badge tone="brand">you</Badge>
          <Button size="sm" className="ml-auto" onClick={() => setCreating(true)}>
            <KeyRound size={14} /> New access key
          </Button>
        </div>
        <p className="mt-1 text-xs text-[var(--muted-foreground)]">
          A key for an agent on your own machine. It can read boards, open Loops, write the Info you
          agree on, ask the local agents and track Tickets — never approve a plan, manage accounts
          or change a board&apos;s structure. The key is shown once; &quot;last used&quot; is how
          you recognise which machine is connected.
        </p>

        <div className="mt-2">
          <AgentAccessGuide
            token={issued?.token}
            onCopy={(snippet) => {
              void copySnippet(snippet);
            }}
          />
        </div>
        <ul className="mt-3 divide-y divide-[var(--border)]">
          {credentialsQuery.isLoading ? (
            <li className="py-2.5 text-xs text-[var(--muted-foreground)]">Loading…</li>
          ) : null}
          {mine.map((credential) => renderRow(credential, false))}
          {!credentialsQuery.isLoading && mine.length === 0 ? (
            <li className="py-2.5 text-xs text-[var(--muted-foreground)]">No agent access yet.</li>
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

      <NewAccessDialog
        open={creating}
        onOpenChange={setCreating}
        isAdmin={isAdmin}
        scopeChoices={scopeChoices}
        defaultExpiry={defaultExpiry}
        expiryHint={expiryHint}
        onIssued={(credential) => {
          setIssued(credential);
          setCreating(false);
          invalidate();
        }}
      />

      <IssuedTokenDialog
        issued={issued}
        onClose={() => setIssued(null)}
        onCopy={() => {
          void copyToken();
        }}
      />
    </>
  );
}
