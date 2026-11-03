import { MessagesSquare, LayoutGrid, LogOut, Settings, Sun, Moon, MonitorSmartphone } from "lucide-react";
import { NavLink, Outlet, useNavigate } from "react-router-dom";
import { Button } from "@/components/ui/button";
import { useAuth } from "@/features/auth/useAuth";
import { cn } from "@/lib/utils";
import type { ThemeMode } from "@/themes/theme";
import { useTheme } from "@/themes/useTheme";

const themeOptions: { value: ThemeMode; label: string; Icon: typeof Sun }[] = [
  { value: "dark", label: "Dark theme", Icon: Moon },
  { value: "light", label: "Light theme", Icon: Sun },
  { value: "system", label: "System theme", Icon: MonitorSmartphone },
];

export function AppLayout() {
  const { actor, logout } = useAuth();
  const { mode, setMode } = useTheme();
  const navigate = useNavigate();

  const nextTheme = themeOptions[(themeOptions.findIndex((item) => item.value === mode) + 1) % 3];
  const ActiveIcon = themeOptions.find((item) => item.value === mode)?.Icon ?? Moon;

  async function signOut() {
    await logout();
    void navigate("/login", { replace: true });
  }

  return (
    <div className="flex min-h-screen flex-col">
      <header className="sticky top-0 z-30 border-b border-[var(--border)] bg-[color-mix(in_srgb,var(--background)_88%,transparent)] backdrop-blur">
        <div className="mx-auto flex h-14 w-full max-w-[1600px] items-center gap-4 px-4">
          <NavLink to="/" className="flex items-center gap-2 text-sm">
            <span className="grid h-7 w-7 place-items-center rounded-md bg-[var(--primary)] text-xs font-medium text-[var(--primary-foreground)]">
              AI
            </span>
            <span className="text-sm font-semibold text-[var(--foreground)]">Tralala</span>
          </NavLink>
          <nav className="flex items-center gap-1 text-sm">
            <NavLink
              to="/"
              end
              className={({ isActive }) =>
                cn(
                  "flex items-center gap-1.5 rounded-md px-2.5 py-1.5 text-[var(--muted-foreground)] hover:text-[var(--foreground)]",
                  isActive && "bg-[var(--surface-raised)] text-[var(--foreground)]",
                )
              }
            >
              <LayoutGrid size={15} /> Boards
            </NavLink>
            <NavLink
              to="/discussions"
              className={({ isActive }) =>
                cn(
                  "flex items-center gap-1.5 rounded-md px-2.5 py-1.5 text-[var(--muted-foreground)] hover:text-[var(--foreground)]",
                  isActive && "bg-[var(--surface-raised)] text-[var(--foreground)]",
                )
              }
            >
              <MessagesSquare size={15} /> Discussions
            </NavLink>
            <NavLink
              to="/settings"
              className={({ isActive }) =>
                cn(
                  "flex items-center gap-1.5 rounded-md px-2.5 py-1.5 text-[var(--muted-foreground)] hover:text-[var(--foreground)]",
                  isActive && "bg-[var(--surface-raised)] text-[var(--foreground)]",
                )
              }
            >
              <Settings size={15} /> Settings
            </NavLink>
          </nav>
          <div className="ml-auto flex items-center gap-2">
            <span className="hidden text-xs text-[var(--muted-foreground)] sm:inline">
              {actor?.name}
            </span>
            <Button
              variant="ghost"
              size="icon"
              aria-label={`Switch to ${nextTheme.label.toLowerCase()}`}
              title={`Current: ${mode}. Switch to ${nextTheme.label.toLowerCase()}.`}
              onClick={() => setMode(nextTheme.value)}
              className="border border-[var(--border)]"
            >
              <ActiveIcon size={15} />
            </Button>
            <Button
              variant="ghost"
              size="icon"
              aria-label="Sign out"
              title="Sign out"
              onClick={() => {
                void signOut();
              }}
            >
              <LogOut size={15} />
            </Button>
          </div>
        </div>
      </header>
      <main className="mx-auto w-full max-w-[1600px] flex-1 px-4 py-6">
        <Outlet />
      </main>
    </div>
  );
}
