import { useQuery } from "@tanstack/react-query";
import { AlertTriangle } from "lucide-react";
import { api } from "@/lib/api";

/**
 * Tells an administrator that the generated first password is still on the server. Only an
 * administrator receives the flag, and the bootstrap account's next password change removes the
 * file, so the banner goes with it.
 */
export function BootstrapPasswordBanner() {
  const metaQuery = useQuery({
    queryKey: ["api-meta"],
    queryFn: () => api.meta(),
    staleTime: 5 * 60_000,
  });
  if (metaQuery.data?.bootstrap_password_file_present !== true) return null;
  return (
    <p className="flex items-center gap-2 rounded-lg border border-[var(--warning)] p-2 text-xs text-[var(--warning)]">
      <AlertTriangle size={14} aria-hidden="true" className="flex-none" />
      <span>
        The generated administrator password is still stored in{" "}
        <code>&lt;data&gt;/.bootstrap-password</code>. Signed in as the account it was generated
        for, change that password under Your password below: the file is then deleted.
      </span>
    </p>
  );
}
