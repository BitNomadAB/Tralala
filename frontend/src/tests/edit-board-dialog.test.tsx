import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http } from "msw";
import { describe, expect, it, vi } from "vitest";
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

async function renderDialog(saving: boolean, onSave: () => void = () => undefined) {
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
        onSave={onSave}
      />
    </QueryClientProvider>,
  );
  expect(await screen.findByText(/No repositories are registered yet/)).toBeInTheDocument();
}

describe("the Edit board dialog", () => {
  it("says it is saving with an ellipsis, not a question mark, and cannot be sent twice", async () => {
    const onSave = vi.fn<() => void>();
    await renderDialog(true, onSave);

    // Held, not disabled: the button that was pressed keeps the focus while the board is saved.
    const button = screen.getByRole("button", { name: "Saving…" });
    expect(button).toHaveAttribute("aria-disabled", "true");
    await userEvent.setup().click(button);
    expect(onSave).not.toHaveBeenCalled();
    expect(screen.queryByRole("button", { name: "Saving?" })).not.toBeInTheDocument();
  });

  it("offers to save the board when it is not saving", async () => {
    await renderDialog(false);

    expect(screen.getByRole("button", { name: "Save board" })).toBeEnabled();
  });
});
