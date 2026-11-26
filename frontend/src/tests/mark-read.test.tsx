import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { describe, expect, it } from "vitest";
import { useMarkRead } from "@/features/discussions/useMarkRead";
import { keys } from "@/lib/queries";
import { discussion, discussionHandlers, DISCUSSION_ID } from "./msw/discussions";
import { BOARD_ID } from "./msw/loops";
import { server } from "./msw/server";

function setup() {
  const api = discussionHandlers(discussion());
  server.use(...api.handlers);
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  queryClient.setQueryData(keys.discussionInbox, { items: [], total: 0 });
  queryClient.setQueryData(keys.boardDiscussions(BOARD_ID, "open"), []);
  queryClient.setQueryData(keys.discussion(BOARD_ID, DISCUSSION_ID), discussion());
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  );
  return { api, queryClient, wrapper };
}

describe("marking a discussion read", () => {
  it("waits until the thread has loaded, marks it once, and reads the lists again", async () => {
    const { api, queryClient, wrapper } = setup();
    const { rerender } = renderHook(
      ({ ready }: { ready: boolean }) => useMarkRead(BOARD_ID, DISCUSSION_ID, ready),
      { wrapper, initialProps: { ready: false } },
    );
    expect(api.state.reads).toBe(0);
    rerender({ ready: true });
    await waitFor(() =>
      expect(queryClient.getQueryState(keys.discussionInbox)?.isInvalidated).toBe(true),
    );
    expect(queryClient.getQueryState(keys.boardDiscussions(BOARD_ID, "open"))?.isInvalidated).toBe(
      true,
    );
    // The thread itself is not read again: what is new is the lists' business.
    expect(queryClient.getQueryState(keys.discussion(BOARD_ID, DISCUSSION_ID))?.isInvalidated).toBe(
      false,
    );
    rerender({ ready: true });
    rerender({ ready: false });
    rerender({ ready: true });
    expect(api.state.reads).toBe(1);
  });
});
