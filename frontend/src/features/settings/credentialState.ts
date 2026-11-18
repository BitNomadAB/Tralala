import type { BadgeTone } from "@/components/ui/badge";
import type { Credential } from "@/lib/types";

/** Whether a key still works: a revoked key never does again, an expired one stopped by itself. */
export type CredentialState = "active" | "expired" | "revoked";

export const CREDENTIAL_TONES: Record<CredentialState, BadgeTone> = {
  active: "success",
  expired: "warning",
  revoked: "danger",
};

/**
 * The state of a key at `now`. The list includes keys past their expiry, which the server refuses,
 * so a key is only "active" while it is neither revoked nor expired.
 */
export function credentialState(credential: Credential, now: number = Date.now()): CredentialState {
  if (credential.revoked_at) return "revoked";
  if (credential.expires_at && new Date(credential.expires_at).getTime() <= now) return "expired";
  return "active";
}
