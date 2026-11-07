import { QueryClient, QueryClientProvider, useQuery } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http } from "msw";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";
import { ToastProvider } from "@/components/ui/toast";
import { DiscussionThread } from "@/features/discussions/DiscussionThread";
import { api } from "@/lib/api";
import type {
  Discussion,
  DiscussionAnswer,
  DiscussionMessage,
  DiscussionStance,
} from "@/lib/types";
import { apiPath, ok } from "./msw/envelope";
import { server } from "./msw/server";

const BOARD = "b-1";
const THREAD = "t-1";
const NOW = "2026-11-07T10:00:00Z";

function answer(changes: Partial<DiscussionAnswer>): DiscussionAnswer {
  return {
    version: 1,
    format: "structured",
    position: "yes",
    recommendation: "Ship it behind a flag.",
    pros: ["Users asked for it."],
    cons: ["One more flag to remove."],
    conditions: [],
    open_questions: [],
    confidence: "high",
    problem: null,
    ...changes,
  };
}

function message(
  id: string,
  author: string,
  content: string,
  structured: DiscussionAnswer | null,
): DiscussionMessage {
  return {
    id,
    parent_message_id: null,
    author_actor_id: author.toLowerCase(),
    author_type: structured ? "agent" : "user",
    author_name: author,
    author_role: structured ? "Reviewer" : null,
    content,
    status: "posted",
    model: null,
    round_number: structured ? 1 : 0,
    created_at: NOW,
    answer: structured,
  };
}

function stance(participant: string, position: DiscussionStance["position"]): DiscussionStance {
  return {
    participant_id: participant.toLowerCase(),
    participant,
    position,
    recommendation: position === "unclear" ? "" : `${participant} recommends.`,
    confidence: position === "unclear" ? null : "high",
    format: position === "unclear" ? "prose" : "structured",
    message_id: `m-${participant}`,
    round_number: 1,
  };
}

const THREAD_DETAIL: Discussion = {
  id: THREAD,
  card_id: "c-1",
  card_title: "Release notes",
  ticket_key: "T-12",
  loop_id: "l-1",
  loop_key: "R001",
  loop_name: "Release",
  title: "Ship the release notes?",
  goal: "Should we ship the release notes in 1.4?",
  mode: "roundtable",
  status: "discussing",
  run_state: "idle",
  created_by_name: "Ada",
  max_rounds: 3,
  round_count: 1,
  tokens_used: 0,
  elapsed_ms: 0,
  created_at: NOW,
  updated_at: NOW,
  last_activity_at: NOW,
  participant_count: 2,
  message_count: 3,
  participants: [],
  messages: [
    message("m-0", "Ada", "Should we ship the **release notes** in 1.4?", null),
    message("m-Alpha", "Alpha", "The change is small and **reversible**.", answer({})),
    message(
      "m-Gamma",
      "Gamma",
      "I would rather wait for the export owner.",
      answer({
        format: "prose",
        position: "unclear",
        recommendation: "",
        pros: [],
        cons: [],
        confidence: null,
        problem: "the answer holds no JSON object",
      }),
    ),
  ],
  synthesis: {
    version: 1,
    kind: "decision_support",
    written_by: "tralala",
    round_id: "r-1",
    round_number: 1,
    thread_round: 1,
    suggestion: { verdict: "unclear", reason: "Gamma cannot tell yet; read the open questions." },
    counts: { yes: 1, yes_with_conditions: 0, no: 0, unclear: 1, missing: 0 },
    go: [stance("Alpha", "yes")],
    stop: [],
    unclear: [stance("Gamma", "unclear")],
    conditions: [{ text: "A rollback exists.", participants: ["Alpha"] }],
    open_questions: [{ text: "Who owns the export?", participants: ["Gamma"] }],
    missing: [],
  },
  positions: [stance("Alpha", "yes"), stance("Gamma", "unclear")],
  votes: [],
  runs: [],
  active_run: null,
};

/** The thread as the page shows it: fetched through the real client, answered by MSW. */
function Harness() {
  const query = useQuery({
    queryKey: ["discussion", BOARD, THREAD],
    queryFn: () => api.getDiscussion(BOARD, THREAD),
  });
  if (!query.data) return <p>Loading</p>;
  return (
    <DiscussionThread
      boardId={BOARD}
      discussion={query.data}
      live={false}
      onReview={() => undefined}
      onChanged={() => undefined}
      reply=""
      onReplyChange={() => undefined}
      sending={false}
      onSend={() => undefined}
    />
  );
}

function openThread(detail: Discussion) {
  server.use(http.get(apiPath(`/boards/${BOARD}/discussions/${THREAD}`), () => ok(detail)));
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={queryClient}>
      <ToastProvider>
        <MemoryRouter>
          <Harness />
        </MemoryRouter>
      </ToastProvider>
    </QueryClientProvider>,
  );
}

describe("a discussion thread", () => {
  it("shows the decision support on top, labelled a suggestion, and the decision under it", async () => {
    openThread(THREAD_DETAIL);
    const support = await screen.findByRole("region", { name: "Decision support" });
    expect(support).toHaveTextContent("A suggestion, not a decision.");
    expect(support).toHaveTextContent("Suggestion: Unclear Gamma cannot tell yet");
    expect(support).toHaveTextContent("For going ahead");
    expect(support).toHaveTextContent("Alpha (Yes, high confidence): Alpha recommends.");
    expect(support).toHaveTextContent("Gamma (Unclear): answered in prose only");
    expect(support).toHaveTextContent("A rollback exists. (Alpha)");
    expect(support).toHaveTextContent("Who owns the export? (Gamma)");
    expect(screen.getByText("Your decision:")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Approve" })).toBeEnabled();
  });

  it("lists each participant's position from the structured answers", async () => {
    openThread(THREAD_DETAIL);
    const list = await screen.findByRole("list", { name: "Positions" });
    const items = within(list).getAllByRole("listitem");
    expect(items.map((item) => item.textContent)).toEqual(["Alpha: Yes", "Gamma: Unclear"]);
  });

  it("renders an answer as a card with its prose collapsed until asked", async () => {
    openThread(THREAD_DETAIL);
    const card = await screen.findByRole("article", { name: "Answer from Alpha" });
    expect(card).toHaveTextContent("Ship it behind a flag.");
    expect(card).toHaveTextContent("ForUsers asked for it.");
    expect(card).toHaveTextContent("AgainstOne more flag to remove.");
    const details = card.querySelector("details");
    expect(details).not.toBeNull();
    expect(details?.open).toBe(false);
    await userEvent.setup().click(within(card).getByText("Full answer"));
    expect(details?.open).toBe(true);
    expect(within(card).getByText("reversible").tagName).toBe("STRONG");
  });

  it("keeps an answer that never followed the standard as open prose", async () => {
    openThread(THREAD_DETAIL);
    const card = await screen.findByRole("article", { name: "Answer from Gamma" });
    expect(card).toHaveTextContent("Answered in prose only");
    expect(card.querySelector("details")?.open).toBe(true);
    expect(card).toHaveTextContent("I would rather wait for the export owner.");
  });

  it("shows a person's message as Markdown and no support before the first round", async () => {
    openThread({
      ...THREAD_DETAIL,
      messages: [message("m-0", "Ada", "Should we ship the **release notes**?", null)],
      synthesis: null,
      positions: [],
    });
    const list = await screen.findByRole("list", { name: "Messages" });
    expect(within(list).getByText("release notes").tagName).toBe("STRONG");
    expect(screen.queryByRole("region", { name: "Decision support" })).toBeNull();
    expect(screen.queryByRole("list", { name: "Positions" })).toBeNull();
  });
});
