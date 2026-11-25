import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { KeyRound } from "lucide-react";
import { useId, useMemo, useState } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { useToast } from "@/components/ui/useToast";
import { scopeChoicesFor } from "@/lib/agentAccess";
import { api } from "@/lib/api";
import { describeError } from "@/lib/describeError";
import type { Credential } from "@/lib/types";
import { AgentAccessGuide } from "./AgentAccessGuide";
import { ConfirmDialog, type Confirmation } from "./ConfirmDialog";
import { COPY_BY_HAND, copyText } from "./copyText";
import { CredentialRow } from "./CredentialRow";
import { IssuedTokenDialog } from "./IssuedTokenDialog";
import { NewAccessDialog } from "./NewAccessDialog";

/** What the two buttons of a key do, said under each list and read as the buttons' description. */
const ROTATE_AND_REVOKE =
  "Rotate issues a new token with the same scopes and revokes the old one at once. Revoke stops a key for good.";

const NEW_ACCESS_ID = "new-access-key";

/** A key the person chose to rotate or revoke, waiting for them to confirm (WCAG 3.3.4). */
interface KeyAction {
  type: "rotate" | "revoke";
  credential: Credential;
}

/** What the confirmation asks and says: neither action can be undone. */
function confirmation({ type, credential }: KeyAction): Confirmation {
  return type === "revoke"
    ? {
        title: `Revoke ${credential.name}?`,
        consequence: "Agents using this key lose access at once. This cannot be undone.",
        confirmLabel: "Revoke key",
      }
    : {
        title: `Rotate ${credential.name}?`,
        consequence:
          "The old token stops working at once, so agents using it lose access until they get the new one. You get the new token once.",
        confirmLabel: "Rotate key",
      };
}

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
  const [asking, setAsking] = useState<KeyAction | null>(null);
  // A token issued from the New access key dialog gives focus back to that button on closing,
  // as the dialog that opened it is gone; a rotated one gives it back to the Rotate button.
  const [returnFocusId, setReturnFocusId] = useState<string | null>(null);
  const mineHintId = useId();
  const othersHintId = useId();

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
    onError: (error) => {
      toast.push({
        title: "Could not revoke the access",
        description: describeError(error, undefined),
        variant: "error",
      });
    },
  });

  const rotateMutation = useMutation({
    mutationFn: (credential: Credential) => api.rotateCredential(credential.id),
    onSuccess: (credential) => {
      setReturnFocusId(null);
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

  async function copyCommand(command: string) {
    if (await copyText(command)) {
      toast.push({ title: "Command copied", variant: "success" });
      return;
    }
    toast.push({
      title: "The browser did not copy the command",
      description: COPY_BY_HAND,
      variant: "error",
    });
  }

  function renderRow(credential: Credential, showOwner: boolean) {
    return (
      <CredentialRow
        key={credential.id}
        credential={credential}
        showOwner={showOwner}
        rotating={rotateMutation.isPending}
        revoking={revokeMutation.isPending && revokeMutation.variables.id === credential.id}
        hintId={showOwner ? othersHintId : mineHintId}
        onRotate={() => setAsking({ type: "rotate", credential })}
        onRevoke={() => setAsking({ type: "revoke", credential })}
      />
    );
  }

  return (
    <>
      <div className="card-surface p-5">
        <div className="flex flex-wrap items-center gap-2">
          <h2 className="text-sm font-semibold">Interaction agent access</h2>
          <Badge tone="brand">you</Badge>
          <Button
            id={NEW_ACCESS_ID}
            size="sm"
            className="ml-auto"
            onClick={() => setCreating(true)}
          >
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
            onCopy={(command) => {
              void copyCommand(command);
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
        <p id={mineHintId} className="mt-2 text-xs text-[var(--muted-foreground)]">
          {ROTATE_AND_REVOKE}
        </p>
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
          <p id={othersHintId} className="mt-2 text-xs text-[var(--muted-foreground)]">
            {ROTATE_AND_REVOKE}
          </p>
          <p className="mt-3 text-xs text-[var(--muted-foreground)]">
            Yours may hold any grantable scope: <code>{scopeChoices.join(", ")}</code>
          </p>
        </div>
      ) : null}

      <ConfirmDialog
        question={asking ? confirmation(asking) : null}
        onCancel={() => setAsking(null)}
        onConfirm={() => {
          if (!asking) return;
          setAsking(null);
          if (asking.type === "revoke") revokeMutation.mutate(asking.credential);
          else rotateMutation.mutate(asking.credential);
        }}
      />

      <NewAccessDialog
        open={creating}
        onOpenChange={setCreating}
        isAdmin={isAdmin}
        scopeChoices={scopeChoices}
        defaultExpiry={defaultExpiry}
        expiryHint={expiryHint}
        onIssued={(credential) => {
          setReturnFocusId(NEW_ACCESS_ID);
          setIssued(credential);
          setCreating(false);
          invalidate();
        }}
      />

      <IssuedTokenDialog
        issued={issued}
        returnFocusId={returnFocusId}
        onClose={() => setIssued(null)}
      />
    </>
  );
}
