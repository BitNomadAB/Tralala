import type { InviteCreated } from "@/lib/types";
import { formatDateTime } from "@/lib/utils";
import { invitationLink } from "./invitation";
import { OneTimeSecretDialog } from "./OneTimeSecretDialog";

/** Shows a new invitation link once; a new link replaces it. */
export function InvitationDialog({
  invited,
  onClose,
}: {
  invited: InviteCreated | null;
  onClose: () => void;
}) {
  return (
    <OneTimeSecretDialog
      value={invited ? invitationLink(window.location.origin, invited) : null}
      title={`Invitation link for ${invited?.user_name ?? ""}`}
      description="Send it once through a channel you already trust. The link sets the password and signs the person in."
      label="Link"
      noun="link"
      hint="Shown once; a new link replaces it."
      onClose={onClose}
    >
      <p className="text-xs text-[var(--muted-foreground)]">
        Valid until {invited ? formatDateTime(invited.expires_at) : ""}. Anyone with the link can
        claim the account until it is used or a new link is created.
      </p>
    </OneTimeSecretDialog>
  );
}
