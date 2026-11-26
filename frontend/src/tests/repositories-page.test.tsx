import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { delay, http } from "msw";
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
    addressForgotten: false,
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
    await user.click(
      (await row("mirrored app")).getByRole("button", { name: "Edit mirrored app" }),
    );
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
    expect(
      mirrored.getByRole("button", { name: "Rebuild mirror of mirrored app" }),
    ).toBeInTheDocument();
    expect(mirrored.queryByRole("button", { name: /^Remove now/ })).not.toBeInTheDocument();

    const hub = await row("hub app");
    expect(hub.getByText("GitHub")).toBeInTheDocument();
    expect(hub.queryByRole("button", { name: /^Rebuild mirror/ })).not.toBeInTheDocument();
  });

  it("rebuilds a mirror, and offers Remove now when a removal failed", async () => {
    const failed = { ...MIRRORED, mirror_error: "mirror_cleanup_failed" };
    const { sent, user } = await renderPage([failed]);
    const mirrored = await row("mirrored app");
    expect(mirrored.getByText(/host still holds a file in it/)).toBeInTheDocument();

    await user.click(mirrored.getByRole("button", { name: "Rebuild mirror of mirrored app" }));
    expect(await screen.findByText(/next analysis or RoadMap run fetches it again/)).toBeVisible();
    await user.click(mirrored.getByRole("button", { name: "Remove now: mirror of mirrored app" }));
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
    await user.click(
      (await row("mirrored app")).getByRole("button", {
        name: "Remove now: mirror of mirrored app",
      }),
    );
    expect(await screen.findByText("Could not remove the mirror")).toBeInTheDocument();
    expect(screen.getByText("The mirror's directory could not be removed")).toBeInTheDocument();
  });
});

describe("the Repositories page's commands", () => {
  it("names the repository in every command and blocks only the row under way", async () => {
    const { user } = await renderPage([GITHUB, MIRRORED]);
    server.use(
      http.post(apiPath("/repositories/:id/check"), async () => {
        await delay("infinite");
      }),
    );
    const hub = await row("hub app");
    expect(hub.getByRole("button", { name: "Edit hub app" })).toBeInTheDocument();
    expect(hub.getByRole("button", { name: "Remove hub app" })).toBeInTheDocument();

    const test = hub.getByRole("button", { name: "Test access to hub app" });
    await user.click(test);
    // The button stays where the person is, and says what it waits for.
    expect(await hub.findByText("Testing access…")).toBeInTheDocument();
    expect(test).toHaveAttribute("aria-disabled", "true");
    expect(test).toHaveAccessibleDescription("Testing access…");
    expect(test).toHaveFocus();
    const other = (await row("mirrored app")).getByRole("button", {
      name: "Test access to mirrored app",
    });
    expect(other).not.toHaveAttribute("aria-disabled");
  });

  it("moves focus to the next repository once one is removed, and to the heading after the last", async () => {
    const listed = [GITHUB, MIRRORED];
    const { user } = await renderPage(listed);
    server.use(
      http.get(apiPath("/repositories"), () => ok(listed)),
      http.delete(apiPath("/repositories/:id"), ({ params }) => {
        listed.splice(
          listed.findIndex((entry) => entry.id === params.id),
          1,
        );
        return ok({ deleted: true });
      }),
    );

    await user.click((await row("hub app")).getByRole("button", { name: "Remove hub app" }));
    await user.click(screen.getByRole("button", { name: "Remove repository" }));
    const next = (await row("mirrored app")).getByRole("button", {
      name: "Test access to mirrored app",
    });
    await waitFor(() => expect(next).toHaveFocus());

    await user.click(screen.getByRole("button", { name: "Remove mirrored app" }));
    await user.click(screen.getByRole("button", { name: "Remove repository" }));
    const heading = screen.getByRole("heading", { name: "Repositories", level: 1 });
    await waitFor(() => expect(heading).toHaveFocus());
    expect(await screen.findByText(/No repositories yet/)).toBeInTheDocument();
  });
});

describe("removing a repository", () => {
  it("asks first, says what goes with it, and Cancel removes nothing", async () => {
    const used = { ...MIRRORED, boards: [{ id: "board-1", name: "Platform" }] };
    const { user, sent } = await renderPage([GITHUB, used]);
    const remove = (await row("mirrored app")).getByRole("button", {
      name: "Remove mirrored app",
    });
    await user.click(remove);

    const dialog = screen.getByRole("dialog", { name: "Remove mirrored app?" });
    expect(dialog).toHaveAccessibleDescription(
      "This removes the repository and its stored key from Tralala, and deletes Tralala's mirror of it. The board Platform can no longer read it. This cannot be undone.",
    );
    await user.click(within(dialog).getByRole("button", { name: "Cancel" }));

    await waitFor(() => expect(remove).toHaveFocus());
    expect(sent).toEqual([]);
  });

  it("removes it once it is confirmed, and gives focus back to its button when that fails", async () => {
    const { user } = await renderPage([GITHUB]);
    const deletes: string[] = [];
    server.use(
      http.delete(apiPath("/repositories/:id"), ({ request }) => {
        deletes.push(requestPath(request));
        return failure(409, "conflict", "The repository is in use by a running analysis");
      }),
    );
    const remove = (await row("hub app")).getByRole("button", { name: "Remove hub app" });
    await user.click(remove);
    expect(screen.getByRole("dialog", { name: "Remove hub app?" })).toHaveAccessibleDescription(
      "This removes the repository and its stored key from Tralala. This cannot be undone.",
    );
    await user.click(screen.getByRole("button", { name: "Remove repository" }));

    expect(await screen.findByText("Could not remove")).toBeInTheDocument();
    expect(deletes).toEqual(["/repositories/repo-hub"]);
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    await waitFor(() => expect(remove).toHaveFocus());
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
