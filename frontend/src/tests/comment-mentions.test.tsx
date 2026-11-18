import { QueryClient, QueryClientProvider, useQueryClient } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http } from "msw";
import { describe, expect, it, vi } from "vitest";
import { Dialog, DialogFrame, DialogTitle } from "@/components/ui/dialog";
import { ToastProvider } from "@/components/ui/toast";
import { CardComments } from "@/features/cards/CardComments";
import { mentionAnnouncement } from "@/features/cards/ticketText";
import { useCardComments } from "@/features/cards/useCardComments";
import { keys } from "@/lib/queries";
import type { AgentDirectoryEntry } from "@/lib/types";
import { announcer } from "./announcer";
import { CARD_ID, CARD_PATH, ticketCard } from "./msw/cards";
import { apiPath, ok } from "./msw/envelope";
import { BOARD_ID, LOOP_ID } from "./msw/loops";
import { server } from "./msw/server";

function agent(name: string, role: string | null): AgentDirectoryEntry {
  return {
    id: `agent-${name}`,
    name,
    role_template_id: role ? `role-${name}` : null,
    role_template_name: role,
    role_template_scope: "board",
  };
}

const AGENTS = [
  agent("Alpha", "Product Owner"),
  agent("Bravo", "Backend Developer"),
  agent("Charlie", null),
];

/** The composer as the Ticket's dialog holds it, inside a dialog frame that Escape would close. */
function Composer() {
  const queryClient = useQueryClient();
  const comments = useCardComments({
    boardId: BOARD_ID,
    loopId: LOOP_ID,
    cardId: CARD_ID,
    refresh: () => {
      void queryClient.invalidateQueries({ queryKey: keys.card(BOARD_ID, LOOP_ID, CARD_ID) });
    },
    onError: () => undefined,
  });
  return (
    <CardComments
      live={false}
      mentions={comments.mentions}
      retrying={false}
      onRetryMention={() => undefined}
      comments={[]}
      comment={comments.comment}
      onCommentChange={comments.changeComment}
      onCloseSuggestions={comments.closeSuggestions}
      suggestions={comments.suggestions}
      mentionIndex={comments.mentionIndex}
      onMentionIndexChange={comments.setMentionIndex}
      onChooseAgent={comments.chooseAgent}
      commentField={comments.commentField}
      onSubmitComment={(content) => comments.addComment.mutate(content)}
    />
  );
}

async function renderComposer() {
  server.use(
    http.get(apiPath(CARD_PATH), () => ok(ticketCard())),
    http.get(apiPath("/agents/directory"), () => ok(AGENTS)),
    http.get(apiPath(`${CARD_PATH}/mentions`), () => ok([])),
  );
  const onOpenChange = vi.fn();
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={queryClient}>
      <ToastProvider>
        <Dialog open onOpenChange={onOpenChange}>
          <DialogFrame>
            <DialogTitle>Rotate the signing key</DialogTitle>
            <Composer />
          </DialogFrame>
        </Dialog>
      </ToastProvider>
    </QueryClientProvider>,
  );
  const field = screen.getByRole("textbox", { name: "New comment" });
  // The directory is read once; the suggestions need it.
  await waitFor(() => expect(queryClient.getQueryData(keys.agentDirectory)).toEqual(AGENTS));
  return { field, onOpenChange, user: userEvent.setup() };
}

describe("mentioning an agent in a comment", () => {
  it("lists the agents as options the field points at, and moves the highlight with the arrows", async () => {
    const { field, user } = await renderComposer();
    expect(field).not.toHaveAttribute("aria-controls");
    expect(field).not.toHaveAttribute("aria-activedescendant");
    await user.type(field, "Ask @");
    const list = screen.getByRole("listbox", { name: "Mention an agent" });
    const options = within(list).getAllByRole("option");
    expect(options.map((option) => option.textContent)).toEqual([
      "AlphaProduct Owner",
      "BravoBackend Developer",
      "Charlieno role",
    ]);
    expect(field).toHaveAttribute("aria-autocomplete", "list");
    expect(field).toHaveAttribute("aria-controls", list.id);
    expect(field).toHaveAttribute("aria-activedescendant", options[0]?.id);
    expect(options[0]).toHaveAttribute("aria-selected", "true");
    // More than colour marks the highlight: the Enter sign shows on it alone, and it is bold.
    expect(options[0]?.querySelector("svg.lucide-corner-down-left")).not.toHaveClass("invisible");
    expect(options[1]?.querySelector("svg.lucide-corner-down-left")).toHaveClass("invisible");
    expect(options[0]).toHaveClass("font-semibold");
    await waitFor(() => expect(announcer()).toHaveTextContent("3 agents. Alpha highlighted."));

    await user.keyboard("{ArrowDown}");
    expect(field).toHaveFocus();
    expect(field).toHaveAttribute("aria-activedescendant", options[1]?.id);
    expect(options[1]).toHaveAttribute("aria-selected", "true");
    await waitFor(() => expect(announcer()).toHaveTextContent("3 agents. Bravo highlighted."));
    await user.keyboard("{ArrowUp}{ArrowUp}");
    expect(field).toHaveAttribute("aria-activedescendant", options[2]?.id);

    await user.keyboard("{Enter}");
    expect(screen.queryByRole("listbox")).toBeNull();
    expect(field).toHaveValue("Ask @[Charlie] ");
    expect(field).not.toHaveAttribute("aria-activedescendant");
  });

  it("closes only the list on Escape, keeping the dialog and the unsent comment", async () => {
    const { field, onOpenChange, user } = await renderComposer();
    await user.type(field, "Please look @Br");
    expect(screen.getByRole("listbox", { name: "Mention an agent" })).toBeInTheDocument();
    expect(field).toHaveAttribute("data-keeps-escape");
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("listbox")).toBeNull();
    expect(onOpenChange).not.toHaveBeenCalled();
    expect(field).toHaveValue("Please look @Br");
    expect(field).toHaveFocus();
    expect(field).not.toHaveAttribute("data-keeps-escape");
    // With the list closed, Escape is the dialog's again.
    await user.keyboard("{Escape}");
    expect(onOpenChange).toHaveBeenCalledWith(false);
  });

  it("chooses an agent with a press, without taking the focus from the field", async () => {
    const { field, user } = await renderComposer();
    await user.type(field, "@a");
    await user.click(screen.getByRole("option", { name: /Charlie/ }));
    await waitFor(() => expect(field).toHaveValue("@[Charlie] "));
    expect(field).toHaveFocus();
  });

  it("words the announcement for one agent and for none highlighted", () => {
    expect(mentionAnnouncement(["Alpha"], 0)).toBe("1 agent. Alpha highlighted.");
    expect(mentionAnnouncement(["Alpha", "Bravo"], 5)).toBe("2 agents.");
  });
});
