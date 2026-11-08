import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter, Navigate, Route, Routes, useLocation } from "react-router-dom";
import { ToastProvider } from "@/components/ui/toast";
import { AuthProvider } from "@/features/auth/AuthProvider";
import { useAuth } from "@/features/auth/useAuth";
import { ThemeProvider } from "@/themes/ThemeProvider";
import { AmbientBackground } from "./AmbientBackground";
import { AppLayout } from "./AppLayout";
import { lazyPage } from "./chunkLoading";
import { RouteErrorBoundary } from "./RouteErrorBoundary";

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
    return <Navigate to="/login" replace state={{ from: location.pathname }} />;
  }
  return <>{children}</>;
}

function LoginRoute() {
  const { actor, loading } = useAuth();
  if (loading) return null;
  if (actor) return <Navigate to="/" replace />;
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
