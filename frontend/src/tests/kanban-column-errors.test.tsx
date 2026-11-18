import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http } from "msw";
import { describe, expect, it, vi } from "vitest";
import { ToastProvider } from "@/components/ui/toast";
import { LoopKanban } from "@/features/loops/LoopKanban";
import { apiPath, failure } from "./msw/envelope";
import { BOARD_ID, LOOP_ID, LOOP_PATH } from "./msw/loops";
import { server } from "./msw/server";
import { COLUMNS } from "./msw/ticketView";

/** The Loop's columns, empty, with a server that refuses every change to a column. */
function renderKanban() {
  server.use(
    http.patch(apiPath(`${LOOP_PATH}/lists/list-1`), () =>
      failure(409, "list_name_taken", "A column with that name exists"),
    ),
    http.post(apiPath(`${LOOP_PATH}/lists/list-1/archive`), () =>
      failure(409, "loop_read_only", "The Loop is completed"),
    ),
  );
  const onListsChanged = vi.fn<() => void>();
  const client = new QueryClient({ defaultOptions: { mutations: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <ToastProvider>
        <LoopKanban
          boardId={BOARD_ID}
          loopId={LOOP_ID}
          lists={COLUMNS}
          cardsByList={{}}
          matchingIds={null}
          readOnly={false}
          onOpenCard={() => undefined}
          onListsChanged={onListsChanged}
          onCardsChanged={() => undefined}
        >
          {null}
        </LoopKanban>
      </ToastProvider>
    </QueryClientProvider>,
  );
  return { onListsChanged, user: userEvent.setup() };
}

describe("a column change the server refuses", () => {
  it("says why a new name did not stay, and shows the stored one again", async () => {
    const { onListsChanged, user } = renderKanban();
    await user.click(screen.getByRole("button", { name: "Column actions for Backlog" }));
    await user.click(screen.getByRole("menuitem", { name: "Rename column" }));
    const name = screen.getByRole("textbox", { name: "Rename column Backlog" });
    await user.clear(name);
    await user.type(name, "Ideas{Enter}");

    expect(await screen.findByText("Could not rename column")).toBeInTheDocument();
    expect(screen.getByText("A column with that name exists")).toBeInTheDocument();
    expect(onListsChanged).toHaveBeenCalledTimes(1);
    expect(screen.getByRole("heading", { level: 2, name: /^Backlog/ })).toBeInTheDocument();
  });

  it("says why a column was not archived", async () => {
    const { onListsChanged, user } = renderKanban();
    await user.click(screen.getByRole("button", { name: "Column actions for Backlog" }));
    await user.click(screen.getByRole("menuitem", { name: "Archive column" }));

    expect(await screen.findByText("Could not archive column")).toBeInTheDocument();
    expect(screen.getByText("The Loop is completed")).toBeInTheDocument();
    expect(onListsChanged).toHaveBeenCalledTimes(1);
  });
});
