import { QueryClient, QueryClientProvider, useQuery, useQueryClient } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http } from "msw";
import { useState } from "react";
import { describe, expect, it } from "vitest";
import { CardComments } from "@/features/cards/CardComments";
import { useCardComments } from "@/features/cards/useCardComments";
import { ApiError, api } from "@/lib/api";
import { keys } from "@/lib/queries";
import type { CardDetail, Comment } from "@/lib/types";
import { CARD_ID, CARD_PATH, ticketCard } from "./msw/cards";
import { apiPath, failure, ok } from "./msw/envelope";
import { BOARD_ID, LOOP_ID, NOW } from "./msw/loops";
import { server } from "./msw/server";

const LATER = "2026-11-05T08:00:00Z";
const LABEL = "written after the Loop was completed";

function comment(id: string, content: string, afterLoopCompleted: boolean): Comment {
  const at = afterLoopCompleted ? LATER : NOW;
  return {
    id,
    card_id: CARD_ID,
    actor_id: "actor-ada",
    actor_name: "Ada",
    actor_type: "user",
    content,
    created_at: at,
    updated_at: at,
    after_loop_completed: afterLoopCompleted,
  };
}

/** The comment section as the dialog holds it: the card from its query, the composer's hook. */
function Comments() {
  const queryClient = useQueryClient();
  const [error, setError] = useState("");
  const card = useQuery({
    queryKey: keys.card(BOARD_ID, LOOP_ID, CARD_ID),
    queryFn: () => api.getCard(BOARD_ID, LOOP_ID, CARD_ID),
  });
  const comments = useCardComments({
    boardId: BOARD_ID,
    loopId: LOOP_ID,
    cardId: CARD_ID,
    refresh: () => {
      void queryClient.invalidateQueries({ queryKey: keys.card(BOARD_ID, LOOP_ID, CARD_ID) });
    },
    onError: (reason) => setError(reason instanceof ApiError ? reason.code : "failed"),
  });
  if (!card.data) return <p>Loading card…</p>;
  return (
    <>
      {error ? <p role="alert">{error}</p> : null}
      <CardComments
        live={false}
        mentions={comments.mentions}
        retrying={false}
        onRetryMention={() => undefined}
        comments={card.data.comments ?? []}
        comment={comments.comment}
        onCommentChange={comments.changeComment}
        onCommentBlur={comments.closeSuggestions}
        suggestions={comments.suggestions}
        mentionIndex={comments.mentionIndex}
        onMentionIndexChange={comments.setMentionIndex}
        onChooseAgent={comments.chooseAgent}
        commentField={comments.commentField}
        onSubmitComment={(content) => comments.addComment.mutate(content)}
      />
    </>
  );
}

/**
 * A completed Ticket of a completed Loop with one comment from before the completion. A new
 * comment is answered as the server does on such a Loop, marked as written after it, unless
 * `refusal` says the board is archived.
 */
function completedLoopHandlers(card: CardDetail, refusal?: "board_archived") {
  const state = { card, bodies: [] as unknown[] };
  server.use(
    http.get(apiPath(CARD_PATH), () => ok(state.card)),
    http.get(apiPath("/agents/directory"), () => ok([])),
    http.get(apiPath(`${CARD_PATH}/mentions`), () => ok([])),
    http.post(apiPath(`${CARD_PATH}/comments`), async ({ request }) => {
      const body: unknown = await request.json();
      state.bodies.push(body);
      if (refusal) return failure(409, refusal, "Board is archived");
      const content =
        typeof body === "object" && body !== null && "content" in body ? String(body.content) : "";
      const created = comment(`c-${state.bodies.length + 1}`, content, true);
      state.card = { ...state.card, comments: [...(state.card.comments ?? []), created] };
      return ok(created);
    }),
  );
  return state;
}

async function renderComments(later: Comment[] = [], refusal?: "board_archived") {
  const card = ticketCard({
    completed_at: NOW,
    state: null,
    comments: [comment("c-1", "Shipped as planned.", false), ...later],
  });
  const state = completedLoopHandlers(card, refusal);
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={queryClient}>
      <Comments />
    </QueryClientProvider>,
  );
  await screen.findByText("Shipped as planned.");
  return { state, user: userEvent.setup() };
}

function commentItem(text: string): HTMLElement {
  const item = screen.getByText(text).closest("li");
  if (!item) throw new Error(`no comment item holds "${text}"`);
  return item;
}

describe("comments on a Ticket of a completed Loop", () => {
  it("labels only a comment written after the Loop was completed", async () => {
    await renderComments([comment("c-2", "See L-7 for the rework.", true)]);
    expect(within(commentItem("Shipped as planned.")).queryByText(LABEL)).toBeNull();
    expect(within(commentItem("See L-7 for the rework.")).getByText(LABEL)).toBeInTheDocument();
  });

  it("keeps the comment box open and shows the new comment with its label", async () => {
    const { state, user } = await renderComments();
    const box = screen.getByLabelText("New comment");
    expect(box).toBeEnabled();
    await user.type(box, "Superseded by L-7, which replaced this work.");
    await user.click(screen.getByRole("button", { name: "Send comment" }));
    const later = await screen.findByText("Superseded by L-7, which replaced this work.");
    const item = later.closest("li");
    expect(item).not.toBeNull();
    if (item) expect(within(item).getByText(LABEL)).toBeInTheDocument();
    expect(within(commentItem("Shipped as planned.")).queryByText(LABEL)).toBeNull();
    expect(state.bodies).toEqual([{ content: "Superseded by L-7, which replaced this work." }]);
    await waitFor(() => expect(box).toHaveValue(""));
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("shows the refusal and keeps the text when the board is archived", async () => {
    const { state, user } = await renderComments([], "board_archived");
    const box = screen.getByLabelText("New comment");
    await user.type(box, "Too late");
    await user.click(screen.getByRole("button", { name: "Send comment" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("board_archived");
    expect(box).toHaveValue("Too late");
    expect(state.bodies).toEqual([{ content: "Too late" }]);
    expect(screen.queryByText(LABEL)).toBeNull();
  });
});
