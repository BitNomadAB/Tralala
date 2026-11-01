import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter, Navigate, Route, Routes, useLocation } from "react-router-dom";
import { ToastProvider } from "@/components/ui/toast";
import { ThemeProvider } from "@/themes/ThemeProvider";
import { AmbientBackground } from "./AmbientBackground";
import { AuthProvider, useAuth } from "@/features/auth/AuthProvider";
import { LoginPage } from "@/features/auth/LoginPage";
import { AppLayout } from "./AppLayout";
import { DashboardPage } from "@/features/boards/DashboardPage";
import { BoardPage } from "@/features/board/BoardPage";
import { DiscussionsPage } from "@/features/discussions/DiscussionsPage";
import { SettingsPage } from "@/features/settings/SettingsPage";
import { TemplateEditorPage } from "@/features/settings/TemplateEditorPage";
import { RoleTemplateEditorPage } from "@/features/settings/RoleTemplateEditorPage";
import { AgentEditorPage } from "@/features/settings/AgentEditorPage";

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
                <Route path="/login" element={<LoginRoute />} />
                <Route
                  element={
                    <RequireAuth>
                      <AppLayout />
                    </RequireAuth>
                  }
                >
                  <Route path="/" element={<DashboardPage />} />
                  <Route path="/boards/:boardId" element={<BoardPage />} />
                  <Route path="/discussions" element={<DiscussionsPage />} />
                  <Route path="/settings" element={<SettingsPage />} />
                  <Route path="/settings/templates/:templateId" element={<TemplateEditorPage />} />
                  <Route
                    path="/settings/roles/:roleId"
                    element={<RoleTemplateEditorPage />}
                  />
                  <Route path="/settings/agents/:agentId" element={<AgentEditorPage />} />
                </Route>
                <Route path="*" element={<Navigate to="/" replace />} />
              </Routes>
            </BrowserRouter>
          </ToastProvider>
        </ThemeProvider>
      </AuthProvider>
    </QueryClientProvider>
  );
}

