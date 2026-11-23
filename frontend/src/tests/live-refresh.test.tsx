import {
  focusManager,
  QueryClient,
  QueryClientProvider,
  useMutation,
  useQuery,
} from "@tanstack/react-query";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { http } from "msw";
import { useState } from "react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { RefreshButton } from "@/app/RefreshButton";
import { BOARD_CHANGES_INTERVAL_MS, followedQueries } from "@/app/useBoardChanges";
import { ToastProvider } from "@/components/ui/toast";
import { keys, useBoard } from "@/lib/queries";
import type { ActivityEntry } from "@/lib/types";
import { announcer } from "./announcer";
import { board } from "./msw/boards";
import { apiPath, failure, ok, requestPath } from "./msw/envelope";
import { BOARD_ID, LOOP_ID, NOW } from "./msw/loops";
import { server } from "./msw/server";

const BOARD_PAGE = `/boards/${BOARD_ID}/loops/${LOOP_ID}`;
const BOARD_PATH = `GET /boards/${BOARD_ID}`;
const ACTIVITY_PATH = `GET /boards/${BOARD_ID}/activity`;

const ENTRY: ActivityEntry = {
  id: "entry-1",
  actor_id: "agent-1",
  actor_type: "agent",
  action: "card.moved",
  entity_type: "card",
  entity_id: "card-1",
  request_id: null,
  timestamp: NOW,
  changes: {},
};

/** A promise and the function that settles it, for a step the test decides when to take. */
function signal() {
  let resolve: () => void = () => undefined;
  const promise = new Promise<void>((settle) => {
    resolve = settle;
  });
  return { promise, resolve };
}

/**
 * The board as the server holds it: its name, how many entries its activity log has and whether
 * the board can be read. The newest entry keeps its id, as it does when two writes land in the same
 * second, so only the count tells a change. `requests` is every request, as "METHOD /path".
 */
function boardNetwork() {
  const state = { name: "MatchMap", entries: 3, readable: true, requests: [] as string[] };
  server.use(
    // Answers nothing, so MSW moves on to the next handler: this one only records the request.
    http.all(apiPath("/*"), ({ request }) => {
      state.requests.push(`${request.method} ${requestPath(request)}`);
    }),
    http.get(apiPath(`/boards/${BOARD_ID}`), () =>
      state.readable
        ? ok(board(BOARD_ID, state.name))
        : failure(500, "internal_error", "The board could not be read."),
    ),
    http.get(apiPath(`/boards/${BOARD_ID}/activity`), () =>
      ok([ENTRY], { total: state.entries, limit: 1, offset: 0, has_more: true }),
    ),
  );
  const sent = (route: string) => state.requests.filter((request) => request === route).length;
  return { state, sent };
}

/**
 * A page of the board: its name, which is followed, and its planning documents, which are not
 * (`readDocuments` counts how often they are read). "Open question" opens a dialog and "Close
 * question" closes it; "Save" starts a change that runs until `saved` settles.
 */
function BoardPage({
  readDocuments,
  saved,
}: {
  readDocuments: () => Promise<string>;
  saved: Promise<void>;
}) {
  const boardQuery = useBoard(BOARD_ID);
  useQuery({ queryKey: keys.loopDocuments(BOARD_ID, LOOP_ID), queryFn: readDocuments });
  const save = useMutation({ mutationFn: () => saved });
  const [asking, setAsking] = useState(false);
  return (
    <>
      <h1>{boardQuery.data?.name ?? "Loading board"}</h1>
      <button type="button" onClick={() => setAsking(true)}>
        Open question
      </button>
      <button type="button" onClick={() => save.mutate()}>
        Save
      </button>
      {asking ? (
        <div role="dialog" aria-label="Question">
          <button type="button" onClick={() => setAsking(false)}>
            Close question
          </button>
        </div>
      ) : null}
    </>
  );
}

describe("Refresh and the board's changes", () => {
  let readDocuments: ReturnType<typeof vi.fn<() => Promise<string>>>;
  let saved: ReturnType<typeof signal>;

  beforeEach(() => {
    // Fake time that also moves on its own, so the page can load; the tests then jump five seconds.
    vi.useFakeTimers({ shouldAdvanceTime: true });
    readDocuments = vi.fn(() => Promise.resolve("Info"));
    saved = signal();
  });

  afterEach(() => {
    focusManager.setFocused(undefined);
    vi.useRealTimers();
  });

  /** The header's button beside the page, at `path`; resolves once the page shows the board. */
  async function renderPage(path: string) {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={client}>
        <ToastProvider>
          <MemoryRouter initialEntries={[path]}>
            <RefreshButton />
            <BoardPage readDocuments={readDocuments} saved={saved.promise} />
          </MemoryRouter>
        </ToastProvider>
      </QueryClientProvider>,
    );
    expect(await screen.findByRole("heading", { name: "MatchMap" })).toBeInTheDocument();
  }

  async function later(ms: number) {
    await act(async () => {
      await vi.advanceTimersByTimeAsync(ms);
    });
  }

  const refresh = () => screen.getByRole("button", { name: "Refresh" });

  describe("the Refresh button", () => {
    it("reads again everything the page shows, held while it runs, and says so", async () => {
      const { state, sent } = boardNetwork();
      await renderPage("/settings");
      state.name = "MatchMap 2";

      fireEvent.click(refresh());
      expect(refresh()).toHaveAttribute("aria-disabled", "true");

      await later(1_000);
      expect(screen.getByRole("heading", { name: "MatchMap 2" })).toBeInTheDocument();
      // The button reads what the board's changes leave alone as well.
      expect(readDocuments).toHaveBeenCalledTimes(2);
      expect(refresh()).not.toHaveAttribute("aria-disabled");
      expect(announcer()).toHaveTextContent("Page refreshed.");
      // Settings has no board, so nothing asked for a board's changes.
      expect(sent(ACTIVITY_PATH)).toBe(0);
    });

    it("does not say the page was refreshed when a request failed", async () => {
      const { state, sent } = boardNetwork();
      await renderPage("/settings");
      state.readable = false;

      fireEvent.click(refresh());
      await later(1_000);

      expect(sent(BOARD_PATH)).toBe(2);
      expect(refresh()).not.toHaveAttribute("aria-disabled");
      expect(announcer()).toBeEmptyDOMElement();
    });
  });

  describe("a page of a board", () => {
    /** The page with the board's first marker read, which is where it starts from. */
    async function renderBoardPage() {
      const network = boardNetwork();
      await renderPage(BOARD_PAGE);
      await waitFor(() => {
        expect(network.sent(ACTIVITY_PATH)).toBe(1);
      });
      return network;
    }

    /** Someone else changes the board: its name, and one more entry in its activity log. */
    function changeElsewhere(state: ReturnType<typeof boardNetwork>["state"]) {
      state.name = "MatchMap 2";
      state.entries += 1;
    }

    it("shows a change made elsewhere within five seconds, and leaves the documents alone", async () => {
      const { state } = await renderBoardPage();
      changeElsewhere(state);

      await later(BOARD_CHANGES_INTERVAL_MS);

      expect(await screen.findByRole("heading", { name: "MatchMap 2" })).toBeInTheDocument();
      expect(readDocuments).toHaveBeenCalledTimes(1);
      // Nobody pressed Refresh, so nothing is read out.
      expect(announcer()).toBeEmptyDOMElement();
    });

    it("asks only for the marker while the board stays as it is", async () => {
      const { sent } = await renderBoardPage();

      await later(BOARD_CHANGES_INTERVAL_MS * 2);

      expect(sent(ACTIVITY_PATH)).toBe(3);
      expect(sent(BOARD_PATH)).toBe(1);
    });

    it("waits while a dialog is open and takes the change up once it is closed", async () => {
      const { state, sent } = await renderBoardPage();
      fireEvent.click(screen.getByRole("button", { name: "Open question" }));
      changeElsewhere(state);

      await later(BOARD_CHANGES_INTERVAL_MS);
      expect(sent(ACTIVITY_PATH)).toBe(2);
      expect(sent(BOARD_PATH)).toBe(1);

      fireEvent.click(screen.getByRole("button", { name: "Close question" }));
      await later(BOARD_CHANGES_INTERVAL_MS);
      expect(await screen.findByRole("heading", { name: "MatchMap 2" })).toBeInTheDocument();
    });

    it("waits while a change of the person's own is on its way", async () => {
      const { state, sent } = await renderBoardPage();
      fireEvent.click(screen.getByRole("button", { name: "Save" }));
      changeElsewhere(state);

      await later(BOARD_CHANGES_INTERVAL_MS);
      expect(sent(ACTIVITY_PATH)).toBe(2);
      expect(sent(BOARD_PATH)).toBe(1);

      saved.resolve();
      await later(BOARD_CHANGES_INTERVAL_MS);
      expect(await screen.findByRole("heading", { name: "MatchMap 2" })).toBeInTheDocument();
    });

    it("asks nothing while the tab is hidden, and at once when it is shown again", async () => {
      const { state, sent } = await renderBoardPage();
      act(() => {
        focusManager.setFocused(false);
      });
      changeElsewhere(state);

      await later(BOARD_CHANGES_INTERVAL_MS * 2);
      expect(sent(ACTIVITY_PATH)).toBe(1);

      act(() => {
        focusManager.setFocused(true);
      });
      expect(await screen.findByRole("heading", { name: "MatchMap 2" })).toBeInTheDocument();
    });
  });
});

describe("followedQueries", () => {
  const client = new QueryClient();
  const followed = (queryKey: readonly unknown[]) => {
    client.setQueryData(queryKey, null);
    const query = client.getQueryCache().find({ queryKey });
    if (!query) throw new Error("the query is not in the cache");
    return followedQueries(BOARD_ID)(query);
  };

  it("matches the board's listings", () => {
    expect(followed(keys.board(BOARD_ID))).toBe(true);
    expect(followed(keys.loops(BOARD_ID))).toBe(true);
    expect(followed(keys.loopSummaries(BOARD_ID))).toBe(true);
    expect(followed(keys.loop(BOARD_ID, LOOP_ID))).toBe(true);
    expect(followed(keys.lists(BOARD_ID, LOOP_ID))).toBe(true);
    expect(followed(keys.listCards(BOARD_ID, LOOP_ID, "list-1", 50))).toBe(true);
    expect(followed(keys.readiness(BOARD_ID, LOOP_ID))).toBe(true);
    expect(followed(keys.notes(BOARD_ID, LOOP_ID))).toBe(true);
    expect(followed(keys.activity(BOARD_ID))).toBe(true);
    expect(followed(keys.ticketDiscussions(BOARD_ID, "card-1"))).toBe(true);
  });

  it("leaves what a draft or a decision is checked against, and the marker itself", () => {
    expect(followed(keys.card(BOARD_ID, LOOP_ID, "card-1"))).toBe(false);
    expect(followed(keys.cardNotes(BOARD_ID, LOOP_ID, "card-1"))).toBe(false);
    expect(followed(keys.loopDocuments(BOARD_ID, LOOP_ID))).toBe(false);
    expect(followed(keys.loopPlan(BOARD_ID, LOOP_ID))).toBe(false);
    expect(followed(keys.qa(BOARD_ID, LOOP_ID))).toBe(false);
    expect(followed(keys.discussion(BOARD_ID, "discussion-1"))).toBe(false);
    expect(followed(keys.boardChanges(BOARD_ID))).toBe(false);
  });

  it("leaves another board's queries", () => {
    expect(followed(keys.board("board-2"))).toBe(false);
    expect(followed(keys.listCards("board-2", LOOP_ID, "list-1", 50))).toBe(false);
  });
});
