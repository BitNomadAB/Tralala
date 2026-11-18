import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus } from "lucide-react";
import { useId, useState } from "react";
import { Button } from "@/components/ui/button";
import { useToast } from "@/components/ui/useToast";
import { api } from "@/lib/api";
import { describeError } from "@/lib/describeError";
import type { InviteCreated, Role, UserAccount } from "@/lib/types";
import { ConfirmDialog, type Confirmation } from "./ConfirmDialog";
import { InvitationDialog } from "./InvitationDialog";
import { NewUserDialog } from "./NewUserDialog";
import { entryControlId, focusById } from "./removalFocus";
import { ResetPasswordDialog } from "./ResetPasswordDialog";
import { UserRow } from "./UserRow";

const roleSelectId = (userId: string) => entryControlId("user-role", userId);

const ROLE_WORDS: Record<Role, string> = { admin: "an administrator", member: "a member" };

/** What disabling `user` does, asked first: it signs them out and revokes what they issued. */
function disableQuestion(user: UserAccount, isSelf: boolean): Confirmation {
  const kept = "Enabling the account later does not bring that access back.";
  return isSelf
    ? {
        title: "Disable your own account?",
        consequence: `This signs you out at once and revokes the agent access you issued. ${kept}`,
        confirmLabel: "Disable account",
      }
    : {
        title: `Disable ${user.name}?`,
        consequence: `This signs ${user.name} out at once and revokes the agent access they issued. ${kept}`,
        confirmLabel: "Disable account",
      };
}

export function UsersCard({ currentUserId }: { currentUserId: string }) {
  const queryClient = useQueryClient();
  const toast = useToast();
  const usersQuery = useQuery({ queryKey: ["users"], queryFn: () => api.listUsers() });
  const [creating, setCreating] = useState(false);
  const [resetting, setResetting] = useState<UserAccount | null>(null);
  const [invited, setInvited] = useState<InviteCreated | null>(null);
  const [disabling, setDisabling] = useState<UserAccount | null>(null);
  // A role chosen in a row's select and not saved yet, per user id.
  const [roles, setRoles] = useState<Record<string, Role>>({});
  const disableHintId = useId();
  const roleHintId = useId();

  const invalidate = () => queryClient.invalidateQueries({ queryKey: ["users"] });

  const onError = (title: string) => (error: unknown) => {
    toast.push({
      title,
      description: describeError(error, undefined),
      variant: "error",
    });
  };

  const roleMutation = useMutation({
    mutationFn: (payload: { userId: string; role: Role }) =>
      api.updateUser(payload.userId, { role: payload.role }),
    onSuccess: (user) => {
      // The stored role shows at once, so the select does not flick back while the list reloads.
      queryClient.setQueryData<UserAccount[]>(["users"], (current) =>
        current?.map((entry) => (entry.id === user.id ? user : entry)),
      );
      void invalidate();
      setRoles((current) =>
        Object.fromEntries(Object.entries(current).filter(([userId]) => userId !== user.id)),
      );
      // The Save role button goes once the role is stored, so focus goes back to the select.
      focusById(roleSelectId(user.id));
      toast.push({ title: `${user.name} is now ${ROLE_WORDS[user.role]}`, variant: "success" });
    },
    onError: onError("Could not change the role"),
  });

  const accessMutation = useMutation({
    mutationFn: (payload: { userId: string; disabled: boolean }) =>
      api.updateUser(payload.userId, { disabled: payload.disabled }),
    onSuccess: (user) => {
      void invalidate();
      toast.push({
        title: user.disabled ? `${user.name} is disabled` : `${user.name} is enabled`,
        variant: "success",
      });
    },
    onError: onError("Could not update the user"),
  });

  const inviteMutation = useMutation({
    mutationFn: (userId: string) => api.inviteUser(userId),
    onSuccess: (invite) => {
      setInvited(invite);
    },
    onError: onError("Could not create an invitation link"),
  });

  const users = usersQuery.data ?? [];
  const inviting = (userId: string) =>
    inviteMutation.isPending && inviteMutation.variables === userId;

  return (
    <div className="card-surface p-5">
      <div className="flex flex-wrap items-center gap-2">
        <h2 className="text-sm font-semibold">Users</h2>
        <Button size="sm" className="ml-auto" onClick={() => setCreating(true)}>
          <Plus size={14} /> New user
        </Button>
      </div>
      <p className="mt-1 text-xs text-[var(--muted-foreground)]">
        Everyone who signs in can work with boards, agents and discussions, and manage their own
        agent access. Only administrators manage accounts; disabling somebody also revokes the agent
        access they issued.
      </p>
      <p id={roleHintId} className="mt-1 text-xs text-[var(--muted-foreground)]">
        A new role takes effect when you press Save role beside it.
      </p>
      <p id={disableHintId} className="mt-1 text-xs text-[var(--muted-foreground)]">
        Disable signs the person out and revokes their agent access. Enable lets them sign in again;
        access that was revoked stays revoked.
      </p>

      <ul className="mt-3 divide-y divide-[var(--border)]">
        {usersQuery.isLoading ? (
          <li className="py-2.5 text-xs text-[var(--muted-foreground)]">Loading users…</li>
        ) : null}
        {users.map((user) => (
          <UserRow
            key={user.id}
            user={user}
            isSelf={user.id === currentUserId}
            role={roles[user.id] ?? user.role}
            roleSelectId={roleSelectId(user.id)}
            saving={roleMutation.isPending && roleMutation.variables.userId === user.id}
            inviting={inviting(user.id)}
            roleHintId={roleHintId}
            disableHintId={disableHintId}
            onRoleChange={(role) => setRoles((current) => ({ ...current, [user.id]: role }))}
            onSaveRole={() => {
              const role = roles[user.id];
              if (role) roleMutation.mutate({ userId: user.id, role });
            }}
            onInvite={() => inviteMutation.mutate(user.id)}
            onResetPassword={() => setResetting(user)}
            onToggleDisabled={() => {
              // Enabling is undone by disabling again, so it needs no question; disabling
              // revokes agent access for good, so it asks first (WCAG 3.3.4).
              if (user.disabled) accessMutation.mutate({ userId: user.id, disabled: false });
              else setDisabling(user);
            }}
          />
        ))}
        {!usersQuery.isLoading && users.length === 0 ? (
          <li className="py-2.5 text-xs text-[var(--muted-foreground)]">No users yet.</li>
        ) : null}
      </ul>

      <ConfirmDialog
        question={disabling ? disableQuestion(disabling, disabling.id === currentUserId) : null}
        onCancel={() => setDisabling(null)}
        onConfirm={() => {
          if (!disabling) return;
          setDisabling(null);
          accessMutation.mutate({ userId: disabling.id, disabled: true });
        }}
      />

      <NewUserDialog open={creating} onOpenChange={setCreating} />

      <InvitationDialog invited={invited} onClose={() => setInvited(null)} />

      <ResetPasswordDialog user={resetting} onClose={() => setResetting(null)} />
    </div>
  );
}
