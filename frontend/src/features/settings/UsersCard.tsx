import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Copy, KeyRound, Link2, Plus, Power } from "lucide-react";
import { useState } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent } from "@/components/ui/dialog";
import { Field, Input, Select } from "@/components/ui/input";
import { useToast } from "@/components/ui/useToast";
import { ApiError, api } from "@/lib/api";
import { ROLES, type InviteCreated, type Role, type UserAccount } from "@/lib/types";
import { clipboard, formatDateTime } from "@/lib/utils";

export function UsersCard({ currentUserId }: { currentUserId: string }) {
  const queryClient = useQueryClient();
  const toast = useToast();
  const usersQuery = useQuery({ queryKey: ["users"], queryFn: () => api.listUsers() });
  const [creating, setCreating] = useState(false);
  const [name, setName] = useState("");
  const [password, setPassword] = useState("");
  const [role, setRole] = useState<Role>("member");
  const [resetting, setResetting] = useState<UserAccount | null>(null);
  const [newPassword, setNewPassword] = useState("");
  const [invited, setInvited] = useState<InviteCreated | null>(null);

  const invalidate = () => queryClient.invalidateQueries({ queryKey: ["users"] });

  const onError = (title: string) => (error: unknown) => {
    toast.push({
      title,
      description: error instanceof ApiError ? error.message : undefined,
      variant: "error",
    });
  };

  const createMutation = useMutation({
    mutationFn: () => api.createUser({ name: name.trim(), password, role }),
    onSuccess: () => {
      void invalidate();
      setCreating(false);
      setName("");
      setPassword("");
      setRole("member");
      toast.push({ title: "User created", variant: "success" });
    },
    onError: onError("Could not create the user"),
  });

  const updateMutation = useMutation({
    mutationFn: (payload: { userId: string; role?: Role; disabled?: boolean }) =>
      api.updateUser(payload.userId, { role: payload.role, disabled: payload.disabled }),
    onSuccess: (user) => {
      void invalidate();
      toast.push({
        title: user.disabled ? `${user.name} is disabled` : `${user.name} updated`,
        variant: "success",
      });
    },
    onError: onError("Could not update the user"),
  });

  const resetMutation = useMutation({
    mutationFn: () => api.resetUserPassword(resetting?.id ?? "", newPassword),
    onSuccess: () => {
      void invalidate();
      setResetting(null);
      setNewPassword("");
      toast.push({ title: "Password reset", description: "Existing sessions were signed out." });
    },
    onError: onError("Could not reset the password"),
  });

  const inviteMutation = useMutation({
    mutationFn: (userId: string) => api.inviteUser(userId),
    onSuccess: (invite) => {
      setInvited(invite);
    },
    onError: onError("Could not create an invitation link"),
  });

  const users = usersQuery.data ?? [];
  const inviteLink = invited ? `${window.location.origin}${invited.path}` : "";

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

      <ul className="mt-3 divide-y divide-[var(--border)]">
        {usersQuery.isLoading ? (
          <li className="py-2.5 text-xs text-[var(--muted-foreground)]">Loading users…</li>
        ) : null}
        {users.map((user) => (
          <li key={user.id} className="flex flex-wrap items-center gap-2 py-2.5">
            <div className="min-w-0 flex-1">
              <p className="truncate text-sm font-medium">
                {user.name}
                {user.id === currentUserId ? " (you)" : ""}
              </p>
              <p className="text-[11px] text-[var(--muted-foreground)]">
                Created {formatDateTime(user.created_at)} ·{" "}
                {user.agent_access_count === 1
                  ? "1 agent access"
                  : `${user.agent_access_count} agent accesses`}
                {user.agent_access_last_used_at
                  ? ` · last used ${formatDateTime(user.agent_access_last_used_at)}`
                  : ""}
              </p>
            </div>
            <Select
              aria-label={`Role of ${user.name}`}
              className="w-28"
              value={user.role}
              onChange={(event) =>
                updateMutation.mutate({ userId: user.id, role: event.target.value as Role })
              }
            >
              {ROLES.map((value) => (
                <option key={value} value={value}>
                  {value}
                </option>
              ))}
            </Select>
            <Badge tone={user.disabled ? "danger" : "success"}>
              {user.disabled ? "disabled" : "active"}
            </Badge>
            <Button
              size="icon"
              variant="ghost"
              aria-label={`Create an invitation link for ${user.name}`}
              title="Invitation link"
              disabled={user.disabled || inviteMutation.isPending}
              onClick={() => inviteMutation.mutate(user.id)}
            >
              <Link2 size={14} />
            </Button>
            <Button
              size="icon"
              variant="ghost"
              aria-label={`Reset password for ${user.name}`}
              title="Reset password"
              onClick={() => setResetting(user)}
            >
              <KeyRound size={14} />
            </Button>
            <Button
              size="icon"
              variant="ghost"
              aria-label={`${user.disabled ? "Enable" : "Disable"} ${user.name}`}
              title={
                user.disabled
                  ? "Enable: the person can sign in again; revoked agent access stays revoked"
                  : "Disable: signs the person out and revokes their agent access"
              }
              onClick={() =>
                updateMutation.mutate({ userId: user.id, disabled: !user.disabled })
              }
            >
              <Power size={14} />
            </Button>
          </li>
        ))}
        {!usersQuery.isLoading && users.length === 0 ? (
          <li className="py-2.5 text-xs text-[var(--muted-foreground)]">No users yet.</li>
        ) : null}
      </ul>

      <Dialog open={creating} onOpenChange={setCreating}>
        <DialogContent title="New user" description="They can sign in right away.">
          <form
            className="flex flex-col gap-3"
            onSubmit={(event) => {
              event.preventDefault();
              if (name.trim() && password.length >= 8) createMutation.mutate();
            }}
          >
            <Field label="Username" htmlFor="user-name">
              <Input
                id="user-name"
                value={name}
                onChange={(event) => setName(event.target.value)}
                required
                maxLength={100}
              />
            </Field>
            <Field label="Initial password" htmlFor="user-password" hint="At least 8 characters.">
              <Input
                id="user-password"
                type="password"
                autoComplete="new-password"
                minLength={8}
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                required
              />
            </Field>
            <Field label="Role" htmlFor="user-role">
              <Select
                id="user-role"
                value={role}
                onChange={(event) => setRole(event.target.value as Role)}
              >
                {ROLES.map((value) => (
                  <option key={value} value={value}>
                    {value}
                  </option>
                ))}
              </Select>
            </Field>
            <div className="flex justify-end gap-2">
              <Button variant="ghost" onClick={() => setCreating(false)}>
                Cancel
              </Button>
              <Button type="submit" disabled={!name.trim() || password.length < 8}>
                Create user
              </Button>
            </div>
          </form>
        </DialogContent>
      </Dialog>

      <Dialog open={Boolean(invited)} onOpenChange={(open) => !open && setInvited(null)}>
        <DialogContent
          title={`Invitation link for ${invited?.user_name ?? ""}`}
          description="Send it once through a channel you already trust. The link sets the password and signs the person in."
        >
          <div className="flex flex-col gap-3">
            <Field label="Link" htmlFor="invite-link" hint="Shown once; a new link replaces it.">
              <Input id="invite-link" value={inviteLink} readOnly onFocus={(event) => event.currentTarget.select()} />
            </Field>
            <p className="text-[11px] text-[var(--muted-foreground)]">
              Valid until {invited ? formatDateTime(invited.expires_at) : ""}. Anyone with the link can
              claim the account until it is used or a new link is created.
            </p>
            <div className="flex justify-end gap-2">
              <Button
                variant="ghost"
                onClick={() => {
                  void clipboard()?.writeText(inviteLink);
                  toast.push({ title: "Link copied", variant: "success" });
                }}
              >
                <Copy size={14} /> Copy
              </Button>
              <Button onClick={() => setInvited(null)}>Done</Button>
            </div>
          </div>
        </DialogContent>
      </Dialog>

      <Dialog open={Boolean(resetting)} onOpenChange={(open) => !open && setResetting(null)}>
        <DialogContent
          title={`Reset password for ${resetting?.name ?? ""}`}
          description="They are signed out everywhere and must use the new password."
        >
          <form
            className="flex flex-col gap-3"
            onSubmit={(event) => {
              event.preventDefault();
              if (newPassword.length >= 8) resetMutation.mutate();
            }}
          >
            <Field label="New password" htmlFor="reset-password" hint="At least 8 characters.">
              <Input
                id="reset-password"
                type="password"
                autoComplete="new-password"
                minLength={8}
                value={newPassword}
                onChange={(event) => setNewPassword(event.target.value)}
                required
              />
            </Field>
            <div className="flex justify-end gap-2">
              <Button variant="ghost" onClick={() => setResetting(null)}>
                Cancel
              </Button>
              <Button type="submit" disabled={newPassword.length < 8}>
                Reset password
              </Button>
            </div>
          </form>
        </DialogContent>
      </Dialog>
    </div>
  );
}
