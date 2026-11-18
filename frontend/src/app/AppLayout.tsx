import {
  MessagesSquare,
  LayoutGrid,
  LogOut,
  Settings,
  Sun,
  Moon,
  MonitorSmartphone,
} from "lucide-react";
import { NavLink, Outlet, useNavigate } from "react-router-dom";
import { Button } from "@/components/ui/button";
import { TralalaLogo } from "@/components/ui/tralala-logo";
import { useAuth } from "@/features/auth/useAuth";
import { cn } from "@/lib/utils";
import type { ThemeMode } from "@/themes/theme";
import { useTheme } from "@/themes/useTheme";

/** Each mode's label and icon, and the mode the toggle switches to next. */
const themeOptions: Record<ThemeMode, { label: string; Icon: typeof Sun; next: ThemeMode }> = {
  dark: { label: "Dark theme", Icon: Moon, next: "light" },
  light: { label: "Light theme", Icon: Sun, next: "system" },
  system: { label: "System theme", Icon: MonitorSmartphone, next: "dark" },
};

export function AppLayout() {
  const { actor, logout } = useAuth();
  const { mode, setMode } = useTheme();
  const navigate = useNavigate();

  const nextMode = themeOptions[mode].next;
  const nextTheme = themeOptions[nextMode];
  const ActiveIcon = themeOptions[mode].Icon;

  async function signOut() {
    await logout();
    void navigate("/login", { replace: true });
  }

  // The skip link moves focus itself: a jump to "#main" alone would put the fragment in the URL
  // and, in some browsers, scroll without moving where the next Tab starts.
  function skipToMain(event: React.MouseEvent<HTMLAnchorElement>) {
    event.preventDefault();
    document.getElementById("main")?.focus();
  }

  return (
    <div className="flex min-h-screen flex-col">
      {/* First in the page, so the first Tab offers to jump past the header (WCAG 2.4.1). */}
      <a
        href="#main"
        onClick={skipToMain}
        className="sr-only rounded-md border border-[var(--border)] bg-[var(--surface)] px-3 py-2 text-sm font-medium text-[var(--foreground)] shadow-lg focus:not-sr-only focus:fixed focus:left-4 focus:top-2 focus:z-50"
      >
        Skip to main content
      </a>
      <header className="sticky top-0 z-30 border-b border-[var(--border)] bg-[color-mix(in_srgb,var(--background)_88%,transparent)] backdrop-blur">
        <div className="mx-auto flex h-14 w-full max-w-[1600px] items-center gap-4 px-4">
          <NavLink to="/" className="flex items-center gap-2 text-sm">
            <TralalaLogo className="h-7" />
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
              onClick={() => setMode(nextMode)}
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
      <main id="main" tabIndex={-1} className="mx-auto w-full max-w-[1600px] flex-1 px-4 py-6">
        <Outlet />
      </main>
    </div>
  );
}
