import type { InviteCreated } from "@/lib/types";

/**
 * The link an invited person opens. It names the account as well as carrying the token, so the
 * enrolment page can show the username to the person and to their password manager, which then
 * saves the new password under the right name (WCAG 1.3.5).
 */
export function invitationLink(origin: string, invite: InviteCreated): string {
  const separator = invite.path.includes("?") ? "&" : "?";
  return `${origin}${invite.path}${separator}user=${encodeURIComponent(invite.user_name)}`;
}
