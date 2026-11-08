import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http } from "msw";
import type { ReactNode } from "react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { describe, expect, it } from "vitest";
import { ToastProvider } from "@/components/ui/toast";
import { NewBoardDialog } from "@/features/boards/NewBoardDialog";
import { globLines, pathsDrafts, pathsPayload } from "@/features/boards/repositoryPaths";
import { BoardLoopsPage } from "@/features/loops/BoardLoopsPage";
import type { Board, Repository } from "@/lib/types";
import { apiPath, failure, ok } from "./msw/envelope";
import { server } from "./msw/server";

const NOW = "2026-11-03T10:00:00Z";

function repository(id: string, name: string): Repository {
  return {
    id,
    name,
    provider: "github",
    url: `https://github.com/example/${name}`,
    branch: null,
    enabled: true,
    has_token: true,
    token_hint: null,
    boards: [],
    last_checked_at: null,
    last_check_status: null,
    last_check_detail: null,
    created_at: NOW,
    updated_at: NOW,
  };
}

const REPOSITORIES = [repository("repo-app", "app"), repository("repo-web", "web")];

const BOARD: Board = {
  id: "board-1",
  name: "Platform",
  description: "",
  status: "active",
  created_at: NOW,
  updated_at: NOW,
  archived_at: null,
  schema_version: 19,
  schema_revision: null,
  loop_count: 0,
  list_count: 0,
  card_count: 0,
  repository_ids: ["repo-app"],
  agent_ids: [],
  repository_paths: { "repo-app": { focus_paths: ["docs/**", "src/*.py"], exclude_paths: [] } },
};

function renderAt(path: string, routePath: string, element: ReactNode) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  render(
    <QueryClientProvider client={queryClient}>
      <ToastProvider>
        <MemoryRouter initialEntries={[path]}>
          <Routes>
            <Route path={routePath} element={element} />
          </Routes>
        </MemoryRouter>
      </ToastProvider>
    </QueryClientProvider>,
  );
}

describe("the focus and exclude globs of a board's repositories", () => {
  // It types four globs key by key, which takes longer than vitest's 5 s default under coverage.
  it(
    "shows a selected repository's stored globs in Edit board and saves what was typed",
    {
      timeout: 15_000,
    },
    async () => {
      const sent: unknown[] = [];
      server.use(
        http.get(apiPath("/boards/board-1"), () => ok(BOARD)),
        http.get(apiPath("/boards/board-1/loops"), () => ok([])),
        http.get(apiPath("/boards/board-1/loop-summaries"), () =>
          ok({ board_id: "board-1", loops: [], count: 0 }),
        ),
        http.get(apiPath("/agents"), () => ok([])),
        http.get(apiPath("/repositories"), () => ok(REPOSITORIES)),
        http.patch(apiPath("/boards/board-1"), async ({ request }) => {
          sent.push(await request.json());
          return ok(BOARD);
        }),
      );
      renderAt("/boards/board-1", "/boards/:boardId", <BoardLoopsPage />);
      const user = userEvent.setup();
      // Edit board sits in the board's quiet menu.
      await user.click(await screen.findByRole("button", { name: "Board actions" }));
      await user.click(screen.getByRole("menuitem", { name: "Edit board" }));

      expect(await screen.findByLabelText("Focus paths in app")).toHaveValue("docs/**\nsrc/*.py");
      expect(screen.getByLabelText("Exclude paths in app")).toHaveValue("");
      // Only a selected repository takes globs.
      expect(screen.queryByLabelText("Focus paths in web")).not.toBeInTheDocument();
      await user.click(screen.getByRole("checkbox", { name: /^web/ }));
      await user.type(screen.getByLabelText("Exclude paths in app"), "docs/old/**");
      await user.type(
        screen.getByLabelText("Focus paths in web"),
        "  public_docs/*  {Enter}{Enter}README.md",
      );
      await user.click(screen.getByRole("button", { name: "Save board" }));

      await waitFor(() => expect(sent).toHaveLength(1));
      expect(sent[0]).toMatchObject({
        repository_ids: ["repo-app", "repo-web"],
        repository_paths: {
          "repo-app": { focus_paths: ["docs/**", "src/*.py"], exclude_paths: ["docs/old/**"] },
          "repo-web": { focus_paths: ["public_docs/*", "README.md"], exclude_paths: [] },
        },
      });
    },
  );

  it("names the glob the server refused when a new board is created", async () => {
    const sent: unknown[] = [];
    server.use(
      http.get(apiPath("/templates"), () => ok({ items: [] })),
      http.get(apiPath("/agents"), () => ok([])),
      http.get(apiPath("/repositories"), () => ok(REPOSITORIES)),
      http.post(apiPath("/boards"), async ({ request }) => {
        sent.push(await request.json());
        return failure(422, "validation_failed", "Request validation failed", [
          {
            loc: ["body", "repository_paths", "repo-app", "focus_paths", "0"],
            msg: "Value error, a glob is relative to the repository root, not an absolute path",
            type: "value_error",
          },
        ]);
      }),
    );
    renderAt("/", "/", <NewBoardDialog open onOpenChange={() => undefined} />);
    const user = userEvent.setup();
    await user.type(screen.getByLabelText("Name"), "Platform");
    await user.click(await screen.findByRole("checkbox", { name: /^app/ }));
    await user.type(screen.getByLabelText("Focus paths in app"), "/etc/*");
    await user.click(screen.getByRole("button", { name: "Create board" }));

    expect(await screen.findByText("Could not create board")).toBeInTheDocument();
    expect(
      screen.getByText(
        "repository_paths.repo-app.focus_paths.0: Value error, a glob is relative to the repository root, not an absolute path",
      ),
    ).toBeInTheDocument();
    expect(sent[0]).toMatchObject({
      repository_ids: ["repo-app"],
      repository_paths: { "repo-app": { focus_paths: ["/etc/*"], exclude_paths: [] } },
    });
  });

  it("reads one glob per line and sends only what a selected repository has", () => {
    expect(globLines("  docs/**  \r\n\n*.md\n   ")).toEqual(["docs/**", "*.md"]);
    const drafts = {
      app: { focus: "docs/**\n", exclude: "" },
      web: { focus: "", exclude: "  \n" },
      gone: { focus: "src/*", exclude: "" },
    };
    expect(pathsPayload(drafts, ["app", "web", "new"])).toEqual({
      app: { focus_paths: ["docs/**"], exclude_paths: [] },
    });
    expect(pathsDrafts({ app: { focus_paths: ["a/*", "b/*"], exclude_paths: ["c/*"] } })).toEqual({
      app: { focus: "a/*\nb/*", exclude: "c/*" },
    });
  });
});
