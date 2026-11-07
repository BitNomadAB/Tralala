import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http } from "msw";
import { describe, expect, it } from "vitest";
import { ToastProvider } from "@/components/ui/toast";
import { AuthContext } from "@/features/auth/useAuth";
import { RepositoriesPage } from "@/features/settings/RepositoriesPage";
import { formatBytes } from "@/features/settings/repositoryLabels";
import type { Actor, Repository } from "@/lib/types";
import { apiPath, failure, ok, requestPath } from "./msw/envelope";
import { server } from "./msw/server";
import { MEMBER } from "./msw/session";

const ADMIN: Actor = { ...MEMBER, id: "admin-1", name: "Ada Admin", role: "admin" };

const GITHUB: Repository = {
  id: "repo-hub",
  name: "hub app",
  provider: "github",
  url: "https://github.com/acme/app",
  branch: null,
  enabled: true,
  has_token: false,
  token_hint: null,
  boards: [],
  last_checked_at: null,
  last_check_status: null,
  last_check_detail: null,
  created_at: "2026-11-01T09:00:00Z",
  updated_at: "2026-11-01T09:00:00Z",
};

const MIRRORED: Repository = {
  ...GITHUB,
  id: "repo-git",
  name: "mirrored app",
  provider: "git_https",
  url: "https://git.example.com/team/app.git",
  default_branch: "main",
  last_sha: "c".repeat(40),
  fetched_at: "2026-11-03T09:00:00Z",
  mirror_bytes: 1_572_864,
};

const READABLE = {
  status: "ok",
  detail: "acme/app is readable, its code included",
  default_branch: "main",
  private: false,
  size_kb: 12,
  checked_at: "2026-11-03T10:00:00Z",
};

/** The page for an administrator over `repositories`; `sent` is every write it made, in order. */
async function renderPage(repositories: Repository[]) {
  const sent: { path: string; body: unknown }[] = [];
  const record = async ({ request }: { request: Request }) => {
    const body: unknown = request.method === "POST" ? await request.json().catch(() => null) : null;
    sent.push({ path: `${request.method} ${requestPath(request)}`, body });
  };
  server.use(
    http.get(apiPath("/repositories"), () => ok(repositories)),
    http.post(apiPath("/repositories"), async (info) => {
      await record(info);
      return ok({ ...GITHUB, id: "repo-new" });
    }),
    http.post(apiPath("/repositories/:id/mirror/:action"), async (info) => {
      await record(info);
      return ok({ ...MIRRORED, last_sha: null, fetched_at: null, mirror_bytes: null });
    }),
    http.post(apiPath("/repositories/:id/check"), async (info) => {
      await record(info);
      return ok(READABLE);
    }),
  );
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  const auth = {
    actor: ADMIN,
    loading: false,
    login: () => Promise.resolve(ADMIN),
    logout: () => Promise.resolve(),
    refresh: () => Promise.resolve(ADMIN),
    signOutLocally: () => undefined,
  };
  render(
    <QueryClientProvider client={queryClient}>
      <AuthContext.Provider value={auth}>
        <ToastProvider>
          <RepositoriesPage />
        </ToastProvider>
      </AuthContext.Provider>
    </QueryClientProvider>,
  );
  expect(await screen.findByRole("heading", { name: "Repositories" })).toBeInTheDocument();
  return { sent, user: userEvent.setup() };
}

/** The list item of the repository called `name`. */
async function row(name: string) {
  const item = (await screen.findByText(name)).closest("li");
  if (!item) throw new Error(`no list item for ${name}`);
  return within(item);
}

describe("the Repositories page", () => {
  it("lets a new repository choose its provider and sends the one chosen", async () => {
    const { sent, user } = await renderPage([]);
    await user.click(screen.getByRole("button", { name: /New repository/ }));
    const dialog = within(screen.getByRole("dialog", { name: "New repository" }));

    const provider = dialog.getByLabelText("Provider");
    expect(provider).toHaveValue("github");
    expect(dialog.getByText("How do I create the key?")).toBeInTheDocument();
    await user.selectOptions(provider, "git_https");
    // The GitHub token recipe gives way to what the mirror needs.
    expect(dialog.queryByText("How do I create the key?")).not.toBeInTheDocument();
    expect(dialog.getByLabelText("Repository URL")).toHaveAttribute(
      "placeholder",
      "https://git.example.com/team/app.git",
    );
    expect(dialog.getByText(/user x-access-token/)).toBeInTheDocument();

    await user.type(
      dialog.getByLabelText("Repository URL"),
      "https://git.example.com/team/app.git",
    );
    await user.click(dialog.getByRole("button", { name: "Save repository" }));
    expect(await screen.findByText("Repository saved")).toBeInTheDocument();
    // A new repository is checked at once, the way a run reads it.
    expect(await screen.findByText("Access verified")).toBeInTheDocument();
    expect(sent).toEqual([
      {
        path: "POST /repositories",
        body: {
          provider: "git_https",
          url: "https://git.example.com/team/app.git",
          branch: null,
          enabled: true,
        },
      },
      { path: "POST /repositories/repo-new/check", body: null },
    ]);
  });

  it("says at once when the key of a new repository cannot read its code", async () => {
    const { user } = await renderPage([]);
    const cannotSee =
      "The key cannot see acme/app: give it read access to the repository's contents";
    server.use(
      http.post(apiPath("/repositories/:id/check"), () =>
        ok({ ...READABLE, status: "not_found", detail: cannotSee }),
      ),
    );
    await user.click(screen.getByRole("button", { name: /New repository/ }));
    const dialog = within(screen.getByRole("dialog", { name: "New repository" }));
    await user.type(dialog.getByLabelText("Repository URL"), "https://github.com/acme/app");
    await user.click(dialog.getByRole("button", { name: "Save repository" }));
    expect(await screen.findByText("Access failed")).toBeInTheDocument();
    expect(screen.getAllByText(new RegExp(cannotSee.slice(0, 30))).length).toBeGreaterThan(0);
  });

  it("keeps the provider of a repository being edited", async () => {
    const { user } = await renderPage([MIRRORED]);
    await user.click((await row("mirrored app")).getByRole("button", { name: "Edit" }));
    const dialog = within(screen.getByRole("dialog", { name: "Edit repository" }));
    expect(dialog.getByLabelText("Provider")).toHaveValue("git_https");
    expect(dialog.getByLabelText("Provider")).toBeDisabled();
  });

  it("shows a mirror's default branch, last fetch and size, and only on a mirrored row", async () => {
    await renderPage([GITHUB, MIRRORED]);
    const mirrored = await row("mirrored app");
    expect(mirrored.getByText("Git over HTTPS")).toBeInTheDocument();
    expect(mirrored.getByText("main")).toBeInTheDocument();
    expect(mirrored.getByText("2026-11-03T09:00:00Z")).toBeInTheDocument();
    expect(mirrored.getByText("1.5 MB")).toBeInTheDocument();
    expect(mirrored.getByRole("button", { name: "Rebuild mirror" })).toBeInTheDocument();
    expect(mirrored.queryByRole("button", { name: "Remove now" })).not.toBeInTheDocument();

    const hub = await row("hub app");
    expect(hub.getByText("GitHub")).toBeInTheDocument();
    expect(hub.queryByRole("button", { name: "Rebuild mirror" })).not.toBeInTheDocument();
  });

  it("rebuilds a mirror, and offers Remove now when a removal failed", async () => {
    const failed = { ...MIRRORED, mirror_error: "mirror_cleanup_failed" };
    const { sent, user } = await renderPage([failed]);
    const mirrored = await row("mirrored app");
    expect(mirrored.getByText(/host still holds a file in it/)).toBeInTheDocument();

    await user.click(mirrored.getByRole("button", { name: "Rebuild mirror" }));
    expect(await screen.findByText(/next analysis or RoadMap run fetches it again/)).toBeVisible();
    await user.click(mirrored.getByRole("button", { name: "Remove now" }));
    expect(sent.map((entry) => entry.path)).toEqual([
      "POST /repositories/repo-git/mirror/rebuild",
      "POST /repositories/repo-git/mirror/remove",
    ]);
  });

  it("says why a mirror could not be removed", async () => {
    const failed = { ...MIRRORED, mirror_error: "mirror_cleanup_failed" };
    const { user } = await renderPage([failed]);
    server.use(
      http.post(apiPath("/repositories/:id/mirror/remove"), () =>
        failure(409, "mirror_cleanup_failed", "The mirror's directory could not be removed"),
      ),
    );
    await user.click((await row("mirrored app")).getByRole("button", { name: "Remove now" }));
    expect(await screen.findByText("Could not remove the mirror")).toBeInTheDocument();
    expect(screen.getByText("The mirror's directory could not be removed")).toBeInTheDocument();
  });
});

describe("formatBytes", () => {
  it("names a mirror's size in the largest unit under 1024", () => {
    expect(formatBytes(512)).toBe("512 B");
    expect(formatBytes(48 * 1024)).toBe("48 KB");
    expect(formatBytes(1_572_864)).toBe("1.5 MB");
    expect(formatBytes(3 * 1024 ** 3)).toBe("3.0 GB");
  });
});
