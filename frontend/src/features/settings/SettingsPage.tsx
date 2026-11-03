import { GitBranch } from "lucide-react";
import { Link } from "react-router-dom";
import { useAuth } from "@/features/auth/useAuth";
import { THEME_KITS, type ThemeKit, type ThemeMode } from "@/themes/theme";
import { useTheme } from "@/themes/useTheme";
import { AgentsCard } from "./AgentsCard";
import { BoardTemplatesCard } from "./BoardTemplatesCard";
import { InteractionAccessCard } from "./InteractionAccessCard";
import { RoleTemplatesCard } from "./RoleTemplatesCard";
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
                  <span className="h-2 w-2 rounded-full" style={{ background: swatch.primary }} />
                  <span className="h-2 w-2 rounded-full" style={{ background: swatch.accent }} />
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

      <InteractionAccessCard isAdmin={isAdmin} currentUserId={actor?.id ?? ""} />
    </section>
  );
}
