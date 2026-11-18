import { KeyRound, Link2, Power } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Select } from "@/components/ui/input";
import { ReasonButton } from "@/components/ui/reason-button";
import { ROLES, type Role, type UserAccount } from "@/lib/types";
import { formatDateTime } from "@/lib/utils";

/**
 * One account in the Users list. The role select only chooses: nothing is sent until Save role,
 * which shows while the choice differs from the stored role (WCAG 3.3.4). On Windows the arrow
 * keys change a closed select one option at a time, and each step would otherwise be saved.
 */
export function UserRow({
  user,
  isSelf,
  role,
  roleSelectId,
  saving,
  inviting,
  roleHintId,
  disableHintId,
  onRoleChange,
  onSaveRole,
  onInvite,
  onResetPassword,
  onToggleDisabled,
}: {
  user: UserAccount;
  isSelf: boolean;
  /** The role shown: the person's unsaved choice, else the stored one. */
  role: Role;
  /** The id of the role select, where focus goes once the role is saved. */
  roleSelectId: string;
  saving: boolean;
  inviting: boolean;
  roleHintId: string;
  disableHintId: string;
  onRoleChange: (role: Role) => void;
  onSaveRole: () => void;
  onInvite: () => void;
  onResetPassword: () => void;
  onToggleDisabled: () => void;
}) {
  return (
    <li className="flex flex-wrap items-center gap-2 py-2.5">
      <div className="min-w-0 flex-1">
        <p className="truncate text-sm font-medium">
          {user.name}
          {isSelf ? " (you)" : ""}
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
        id={roleSelectId}
        aria-label={`Role of ${user.name}`}
        aria-describedby={roleHintId}
        className="w-28"
        value={role}
        onChange={(event) => {
          const next = ROLES.find((value) => value === event.target.value);
          if (next) onRoleChange(next);
        }}
      >
        {ROLES.map((value) => (
          <option key={value} value={value}>
            {value}
          </option>
        ))}
      </Select>
      {role !== user.role ? (
        <ReasonButton
          size="sm"
          aria-label={`Save role of ${user.name}`}
          disabledReason={saving ? "Saving…" : null}
          onClick={onSaveRole}
        >
          Save role
        </ReasonButton>
      ) : null}
      <Badge tone={user.disabled ? "danger" : "success"}>
        {user.disabled ? "disabled" : "active"}
      </Badge>
      <Button
        size="icon"
        variant="ghost"
        aria-label={`Create an invitation link for ${user.name}`}
        title="Invitation link"
        disabled={user.disabled}
        // While the link is being made the button stays focusable, so focus is not lost.
        aria-disabled={inviting ? true : undefined}
        onClick={() => {
          if (!inviting) onInvite();
        }}
      >
        <Link2 size={14} />
      </Button>
      <Button
        size="icon"
        variant="ghost"
        aria-label={`Reset password for ${user.name}`}
        title="Reset password"
        onClick={onResetPassword}
      >
        <KeyRound size={14} />
      </Button>
      <Button
        size="icon"
        variant="ghost"
        aria-label={`${user.disabled ? "Enable" : "Disable"} ${user.name}`}
        aria-describedby={disableHintId}
        onClick={onToggleDisabled}
      >
        <Power size={14} />
      </Button>
    </li>
  );
}
