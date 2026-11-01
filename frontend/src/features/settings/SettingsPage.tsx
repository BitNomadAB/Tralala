import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Copy, GitBranch, KeyRound, RefreshCw, ShieldCheck, Trash2 } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent } from "@/components/ui/dialog";
import { Field, Input } from "@/components/ui/input";
import { useToast } from "@/components/ui/toast";
import { ApiError, api } from "@/lib/api";
import { formatDateTime } from "@/lib/utils";
import type { Credential } from "@/lib/types";
import { useAuth } from "@/features/auth/AuthProvider";
import { Link } from "react-router-dom";
import { THEME_KITS, useTheme, type ThemeKit, type ThemeMode } from "@/themes/ThemeProvider";
import { isWebMcpAvailable } from "@/webmcp/capability";
import { BoardTemplatesCard } from "./BoardTemplatesCard";
import { RoleTemplatesCard } from "./RoleTemplatesCard";
import { AgentsCard } from "./AgentsCard";
import { SecurityCard } from "./SecurityCard";
import { UsersCard } from "./UsersCard";

const themeChoices: { value: ThemeMode; label: string; description: string }[] = [
  { value: "dark", label: "Dark", description: "Night palette of the chosen theme" },
  { value: "light", label: "Light", description: "Day palette of the chosen theme" },
  { value: "system", label: "System", description: "Follow the operating system" },
];

const kitSwatches: Record<ThemeKit, { background: string; primary: string; accent: string }> = {
  carenomad: { background: "#0a1628", primary: "#4b8bf5", accent: "#34d399" },
  matchmap: { background: "#0b1326", primary: "#ff7043", accent: "#94ccff" },
  classic: { background: "#0b0f14", primary: "#4f8cff", accent: "#1d9bf0" },
};

export function SettingsPage() {
  const { mode, kit, setMode, setKit } = useTheme();
  const { actor } = useAuth();
  const isAdmin = actor?.role === "admin";
  const queryClient = useQueryClient();
  const toast = useToast();
  const credentialsQuery = useQuery({
    queryKey: ["credentials"],
    queryFn: () => api.listCredentials(),
    enabled: isAdmin,
  });
  // The server owns which scopes a token may hold, so the form never keeps its own copy.
  const metaQuery = useQuery({
    queryKey: ["api-meta"],
    queryFn: () => api.meta(),
    enabled: isAdmin,
    staleTime: 5 * 60_000,
  });
  const grantableScopes = metaQuery.data?.token_scopes ?? [];
  const [creating, setCreating] = useState(false);
  const [name, setName] = useState("");
  const [scopes, setScopes] = useState<string[]>(["boards:read", "cards:read"]);
  const [expires, setExpires] = useState("90");
  const [issued, setIssued] = useState<Credential | null>(null);

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
      queryClient.invalidateQueries({ queryKey: ["credentials"] });
    },
    onError: (error) =>
      toast.push({
        title: "Could not create credential",
        description: error instanceof ApiError ? error.message : undefined,
        variant: "error",
      }),
  });

  const revokeMutation = useMutation({
    mutationFn: (credential: Credential) => api.revokeCredential(credential.id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["credentials"] });
      toast.push({ title: "Credential revoked", variant: "success" });
    },
  });

  const rotateMutation = useMutation({
    mutationFn: (credential: Credential) => api.rotateCredential(credential.id),
    onSuccess: (credential) => {
      setIssued(credential);
      queryClient.invalidateQueries({ queryKey: ["credentials"] });
      toast.push({ title: "Credential rotated", description: "The old token no longer works." });
    },
    onError: (error) =>
      toast.push({
        title: "Could not rotate the credential",
        description: error instanceof ApiError ? error.message : undefined,
        variant: "error",
      }),
  });

  return (
    <section className="flex max-w-4xl flex-col gap-8">
      <div>
        <h1 className="text-xl font-semibold">Settings</h1>
        <p className="text-xs text-[var(--muted-foreground)]">
          Local appearance, accounts and agent access for this installation.
        </p>
      </div>

      <div className="card-surface p-5">
        <h2 className="text-sm font-semibold">Appearance</h2>
        <p className="mt-1 text-xs text-[var(--muted-foreground)]">
          Pick a theme kit, then dark, light or follow the system. Saved to your account, so it
          follows you to any browser.
        </p>
        <div role="radiogroup" aria-label="Theme kit" className="mt-3 grid gap-2 sm:grid-cols-3">
          {THEME_KITS.map((option) => {
            const swatch = kitSwatches[option.value];
            return (
              <button
                key={option.value}
                type="button"
                role="radio"
                aria-checked={kit === option.value}
                onClick={() => setKit(option.value)}
                className={`flex items-center gap-3 rounded-lg border p-3 text-left ${
                  kit === option.value
                    ? "border-[var(--primary)] bg-[color-mix(in_srgb,var(--primary)_10%,transparent)]"
                    : "border-[var(--border)]"
                }`}
              >
                <span
                  aria-hidden="true"
                  className="flex h-9 w-9 flex-none items-center justify-center gap-0.5 rounded-md border border-[var(--border)]"
                  style={{ background: swatch.background }}
                >
                  <span
                    className="h-2 w-2 rounded-full"
                    style={{ background: swatch.primary }}
                  />
                  <span
                    className="h-2 w-2 rounded-full"
                    style={{ background: swatch.accent }}
                  />
                </span>
                <span className="min-w-0">
                  <span className="block text-sm font-medium">{option.label}</span>
                  <span className="mt-0.5 block text-[11px] text-[var(--muted-foreground)]">
                    {option.description}
                  </span>
                </span>
              </button>
            );
          })}
        </div>
        <div role="radiogroup" aria-label="Theme mode" className="mt-3 grid gap-2 sm:grid-cols-3">
          {themeChoices.map((choice) => (
            <button
              key={choice.value}
              type="button"
              role="radio"
              aria-checked={mode === choice.value}
              onClick={() => setMode(choice.value)}
              className={`rounded-lg border p-3 text-left ${
                mode === choice.value
                  ? "border-[var(--primary)] bg-[color-mix(in_srgb,var(--primary)_10%,transparent)]"
                  : "border-[var(--border)]"
              }`}
            >
              <span className="text-sm font-medium">{choice.label}</span>
              <span className="mt-0.5 block text-[11px] text-[var(--muted-foreground)]">
                {choice.description}
              </span>
            </button>
          ))}
        </div>
      </div>

      {isAdmin ? (
        <div className="card-surface p-5">
          <div className="flex flex-wrap items-center gap-2">
            <h2 className="text-sm font-semibold">GitHub repositories</h2>
            <Link
              to="/settings/repositories"
              className="ml-auto inline-flex h-8 items-center gap-1.5 rounded-lg border border-[var(--border)] px-2.5 text-xs hover:bg-[var(--surface-raised)]"
            >
              <GitBranch size={14} /> Manage repositories
            </Link>
          </div>
          <p className="mt-1 text-xs text-[var(--muted-foreground)]">
            Read-only repository access for the Analytics agent. Several repositories can serve one
            board; the access token is stored sealed and never shown again.
          </p>
        </div>
      ) : null}

      <BoardTemplatesCard />

      <RoleTemplatesCard />

      <AgentsCard />

      {actor?.role === "admin" ? <UsersCard currentUserId={actor.id} /> : null}

      <SecurityCard />

      {isAdmin ? (
        <>
          <div className="card-surface p-5">
            <div className="flex flex-wrap items-center gap-2">
              <h2 className="text-sm font-semibold">API credentials</h2>
              <Badge tone="brand">
                WebMCP {isWebMcpAvailable() ? "available in this browser" : "not available"}
              </Badge>
              <Button size="sm" className="ml-auto" onClick={() => setCreating(true)}>
                <KeyRound size={14} /> New token
              </Button>
            </div>
            <p className="mt-1 text-xs text-[var(--muted-foreground)]">
              Agents use these bearer tokens against <code>/api/v1</code>. Raw tokens are shown once and
              stored hashed.
            </p>
            <ul className="mt-3 divide-y divide-[var(--border)]">
              {(credentialsQuery.data ?? []).map((credential) => (
                <li key={credential.id} className="flex flex-wrap items-center gap-2 py-2.5">
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-sm font-medium">{credential.name}</p>
                    <p className="text-[11px] text-[var(--muted-foreground)]">
                      {credential.scopes.join(", ")} · created {formatDateTime(credential.created_at)}
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
              ))}
              {(credentialsQuery.data ?? []).length === 0 ? (
                <li className="py-2.5 text-xs text-[var(--muted-foreground)]">
                  No credentials yet.
                </li>
              ) : null}
            </ul>
            <div className="mt-4 flex flex-wrap items-center gap-3 text-[11px] text-[var(--muted-foreground)]">
              <a className="underline" href="/docs" target="_blank" rel="noreferrer">
                OpenAPI docs
              </a>
              <span>
                Grantable scopes: <code>{grantableScopes.join(", ") || "loading…"}</code>
              </span>
            </div>
          </div>

          <Dialog open={creating} onOpenChange={setCreating}>
            <DialogContent title="New agent token" description="Scopes limit what the agent can do.">
              <form
                className="flex flex-col gap-3"
                onSubmit={(event) => {
                  event.preventDefault();
                  if (name.trim() && scopes.length > 0) createMutation.mutate();
                }}
              >
                <Field label="Agent name" htmlFor="credential-name">
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
                  {grantableScopes.map((scope) => (
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
                <Field
                  label="Expires in days"
                  htmlFor="credential-expiry"
                  hint="Defaults to 90 days. Use 0 for a token that never expires."
                >
                  <Input
                    id="credential-expiry"
                    type="number"
                    min={0}
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
                    <ShieldCheck size={14} /> Create token
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
              <div className="mt-3 flex justify-end">
                <Button onClick={() => setIssued(null)}>Done</Button>
              </div>
            </DialogContent>
          </Dialog>
        </>
      ) : null}
    </section>
  );
}
