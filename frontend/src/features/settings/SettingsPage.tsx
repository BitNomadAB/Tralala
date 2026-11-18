import { GitBranch } from "lucide-react";
import { Link } from "react-router-dom";
import { usePageTitle } from "@/app/usePageTitle";
import { useAuth } from "@/features/auth/useAuth";
import { AgentsCard } from "./AgentsCard";
import { AppearanceCard } from "./AppearanceCard";
import { BoardTemplatesCard } from "./BoardTemplatesCard";
import { BootstrapPasswordBanner } from "./BootstrapPasswordBanner";
import { InteractionAccessCard } from "./InteractionAccessCard";
import { RoleTemplatesCard } from "./RoleTemplatesCard";
import { SecurityCard } from "./SecurityCard";
import { UsersCard } from "./UsersCard";

export function SettingsPage() {
  const { actor } = useAuth();
  usePageTitle({ page: "settings" });
  const isAdmin = actor?.role === "admin";
  return (
    <section className="flex max-w-4xl flex-col gap-8">
      <div>
        <h1 className="text-xl font-semibold">Settings</h1>
        <p className="text-xs text-[var(--muted-foreground)]">
          Local appearance, accounts and agent access for this installation.
        </p>
      </div>

      {isAdmin ? <BootstrapPasswordBanner /> : null}

      <AppearanceCard />

      {isAdmin ? (
        <div className="card-surface p-5">
          <div className="flex flex-wrap items-center gap-2">
            <h2 className="text-sm font-semibold">Repositories</h2>
            <Link
              to="/settings/repositories"
              className="ml-auto inline-flex h-8 items-center gap-1.5 rounded-lg border border-[var(--border)] px-2.5 text-xs hover:bg-[var(--surface-raised)]"
            >
              <GitBranch size={14} /> Manage repositories
            </Link>
          </div>
          <p className="mt-1 text-xs text-[var(--muted-foreground)]">
            Read-only repository access for the Analytics agent, from GitHub or any allowed HTTPS
            Git host. Several repositories can serve one board; the access token is stored sealed
            and never shown again.
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
