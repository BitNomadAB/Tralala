import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { http } from "msw";
import { describe, expect, it } from "vitest";
import { EditBoardDialog, type BoardEditDraft } from "@/features/loops/EditBoardDialog";
import { apiPath, ok } from "./msw/envelope";
import { server } from "./msw/server";

const DRAFT: BoardEditDraft = {
  name: "Platform",
  description: "",
  repositoryIds: [],
  repositoryPaths: {},
  agentIds: [],
};

async function renderDialog(saving: boolean) {
  // The pickers ask for the repositories and agents to choose from; none is the simplest answer.
  server.use(
    http.get(apiPath("/repositories"), () => ok([])),
    http.get(apiPath("/agents"), () => ok([])),
  );
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={queryClient}>
      <EditBoardDialog
        open
        onOpenChange={() => undefined}
        draft={DRAFT}
        onDraftChange={() => undefined}
        saving={saving}
        onSave={() => undefined}
      />
    </QueryClientProvider>,
  );
  expect(await screen.findByText(/No repositories are registered yet/)).toBeInTheDocument();
}

describe("the Edit board dialog", () => {
  it("says it is saving with an ellipsis, not a question mark, and cannot be sent twice", async () => {
    await renderDialog(true);

    const button = screen.getByRole("button", { name: "Saving…" });
    expect(button).toBeDisabled();
    expect(screen.queryByRole("button", { name: "Saving?" })).not.toBeInTheDocument();
  });

  it("offers to save the board when it is not saving", async () => {
    await renderDialog(false);

    expect(screen.getByRole("button", { name: "Save board" })).toBeEnabled();
  });
});
