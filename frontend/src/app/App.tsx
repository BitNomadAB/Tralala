import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter, Navigate, Route, Routes, useLocation } from "react-router-dom";
import { ToastProvider } from "@/components/ui/toast";
import { AuthProvider } from "@/features/auth/AuthProvider";
import { addressOf, returnPath } from "@/features/auth/returnPath";
import { useAuth } from "@/features/auth/useAuth";
import { ThemeProvider } from "@/themes/ThemeProvider";
import { AmbientBackground } from "./AmbientBackground";
import { AppLayout } from "./AppLayout";
import { lazyPage } from "./chunkLoading";
import { RouteErrorBoundary } from "./RouteErrorBoundary";
import { useRouteFocus } from "./useRouteFocus";

// One chunk per page, loaded when its route first renders; the layouts stay in the main chunk.
const LoginPage = lazyPage(() => import("@/features/auth/LoginPage"), "LoginPage");
const EnrolPage = lazyPage(() => import("@/features/auth/EnrolPage"), "EnrolPage");
const DashboardPage = lazyPage(() => import("@/features/boards/DashboardPage"), "DashboardPage");
const BoardLoopsPage = lazyPage(() => import("@/features/loops/BoardLoopsPage"), "BoardLoopsPage");
const LoopPage = lazyPage(() => import("@/features/loops/LoopPage"), "LoopPage");
const TicketPage = lazyPage(() => import("@/features/cards/TicketPage"), "TicketPage");
const DiscussionPage = lazyPage(
  () => import("@/features/discussions/DiscussionPage"),
  "DiscussionPage",
);
const HistoryPage = lazyPage(() => import("@/features/history/HistoryPage"), "HistoryPage");
const DiscussionsPage = lazyPage(
  () => import("@/features/discussions/DiscussionsPage"),
  "DiscussionsPage",
);
const SettingsPage = lazyPage(() => import("@/features/settings/SettingsPage"), "SettingsPage");
const RepositoriesPage = lazyPage(
  () => import("@/features/settings/RepositoriesPage"),
  "RepositoriesPage",
);
const TemplateEditorPage = lazyPage(
  () => import("@/features/settings/TemplateEditorPage"),
  "TemplateEditorPage",
);
const RoleTemplateEditorPage = lazyPage(
  () => import("@/features/settings/RoleTemplateEditorPage"),
  "RoleTemplateEditorPage",
);
const AgentEditorPage = lazyPage(
  () => import("@/features/settings/AgentEditorPage"),
  "AgentEditorPage",
);

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      refetchOnWindowFocus: false,
      retry: 1,
      staleTime: 5_000,
    },
  },
});

function RequireAuth({ children }: { children: React.ReactNode }) {
  const { actor, loading } = useAuth();
  const location = useLocation();

  if (loading) {
    return (
      <div className="flex min-h-screen items-center justify-center text-sm text-[var(--muted-foreground)]">
        Loading workspace…
      </div>
    );
  }
  if (!actor) {
    // The whole address, query and fragment too, so a link to a decision opens it after the sign-in.
    return <Navigate to="/login" replace state={{ from: addressOf(location) }} />;
  }
  return <>{children}</>;
}

/** Moves focus to each new page's heading; inside the router, beside the routes. */
function RouteFocus() {
  useRouteFocus();
  return null;
}

/**
 * The login page, or for a signed-in person the address the sign-in goes to: the one the login
 * page navigates to as well, so whichever of the two runs first, the person lands on it.
 */
function LoginRoute() {
  const { actor, loading, addressForgotten } = useAuth();
  const location = useLocation();
  if (loading) return null;
  if (actor) return <Navigate to={returnPath(location.state)} replace />;
  // After a sign-out the person asked for, the address RequireAuth kept leaves the login page's
  // state, so the next sign-in opens the dashboard, also after a reload of the login page.
  if (addressForgotten && location.state !== null) return <Navigate to="/login" replace />;
  return <LoginPage />;
}

export function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <AuthProvider>
        <ThemeProvider>
          <AmbientBackground />
          <ToastProvider>
            <BrowserRouter>
              <RouteFocus />
              <Routes>
                {/* Each level of routes renders inside an error boundary, so a page that throws
                    shows a fallback inside the layout and a new route cannot be left outside. The
                    boundary also holds the Suspense a lazy page shows while its chunk loads. */}
                <Route element={<RouteErrorBoundary />}>
                  <Route path="/login" element={<LoginRoute />} />
                  <Route path="/enrol" element={<EnrolPage />} />
                  <Route
                    element={
                      <RequireAuth>
                        <AppLayout />
                      </RequireAuth>
                    }
                  >
                    <Route element={<RouteErrorBoundary />}>
                      <Route path="/" element={<DashboardPage />} />
                      <Route path="/boards/:boardId" element={<BoardLoopsPage />} />
                      <Route path="/boards/:boardId/loops/:loopId" element={<LoopPage />} />
                      <Route
                        path="/boards/:boardId/loops/:loopId/tickets/:cardId"
                        element={<TicketPage />}
                      />
                      <Route
                        path="/boards/:boardId/loops/:loopId/tickets/:cardId/discussions/:discussionId"
                        element={<DiscussionPage />}
                      />
                      <Route
                        path="/boards/:boardId/discussions/:discussionId"
                        element={<DiscussionPage />}
                      />
                      <Route path="/boards/:boardId/history" element={<HistoryPage />} />
                      <Route path="/discussions" element={<DiscussionsPage />} />
                      <Route path="/settings" element={<SettingsPage />} />
                      <Route path="/settings/repositories" element={<RepositoriesPage />} />
                      <Route
                        path="/settings/templates/:templateId"
                        element={<TemplateEditorPage />}
                      />
                      <Route path="/settings/roles/:roleId" element={<RoleTemplateEditorPage />} />
                      <Route path="/settings/agents/:agentId" element={<AgentEditorPage />} />
                    </Route>
                  </Route>
                  <Route path="*" element={<Navigate to="/" replace />} />
                </Route>
              </Routes>
            </BrowserRouter>
          </ToastProvider>
        </ThemeProvider>
      </AuthProvider>
    </QueryClientProvider>
  );
}
