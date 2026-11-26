import { screen, waitFor, within } from "@testing-library/react";
import { http } from "msw";
import { describe, expect, it } from "vitest";
import { CLOSED_NOTICE, REOPENED_NOTICE } from "@/features/discussions/closingRules";
import type { DiscussionMessage } from "@/lib/types";
import { announcer } from "./announcer";
import { BOARD_TITLE, boardThread } from "./msw/boardDiscussions";
import { discussion, DISCUSSION_PATH, QUESTION, TICKET_KEY } from "./msw/discussions";
import { CLOSED_AT } from "./msw/discussionThread";
import { apiPath, failure } from "./msw/envelope";
import { LOOP_ID } from "./msw/loops";
import { server } from "./msw/server";
import {
  BOARD_PAGE_URL,
  MODAL_URL,
  PAGE_URL,
  renderDiscussion,
  TICKET_PAGE_URL,
} from "./renderDiscussion";

/** Everything the polite announcer says from now on, one text after the other. */
function heard(): { text: () => string } {
  const texts: string[] = [];
  const region = announcer();
  const observer = new MutationObserver(() => {
    if (region.textContent) texts.push(region.textContent);
  });
  observer.observe(region, { childList: true, characterData: true, subtree: true });
  return { text: () => texts.join(" | ") };
}

const closed = (extra: Partial<Parameters<typeof discussion>[0]> = {}) =>
  discussion({ status: "closed", closed_at: CLOSED_AT, ...extra });

function comment(id: string, extra: Partial<DiscussionMessage>): DiscussionMessage {
  const base = discussion().messages[4];
  if (!base) throw new Error("The fixture has no reply");
  return { ...base, id, ...extra };
}

describe("closing a discussion", () => {
  it("offers Close discussion to the one who opened it, and asks first", async () => {
    const { api, user } = await renderDiscussion(discussion(), PAGE_URL);
    await user.click(screen.getByRole("button", { name: "Close discussion" }));
    const dialog = await screen.findByRole("dialog", { name: "Close this discussion?" });
    expect(within(dialog).getByRole("button", { name: "Cancel" })).toHaveFocus();
    await user.click(within(dialog).getByRole("button", { name: "Cancel" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(api.state.bodies.filter((entry) => entry.route === "close")).toHaveLength(0);
    expect(screen.getByRole("button", { name: "Close discussion" })).toHaveFocus();
  });

  it("closes on the answer: Closed, no decision or run, Reopen where focus was, and says so", async () => {
    const { api, user } = await renderDiscussion(discussion(), PAGE_URL);
    const said = heard();
    await user.click(screen.getByRole("button", { name: "Close discussion" }));
    const dialog = await screen.findByRole("dialog", { name: "Close this discussion?" });
    await user.click(within(dialog).getByRole("button", { name: "Close discussion" }));
    const reopen = await screen.findByRole("button", { name: "Reopen" });
    await waitFor(() => expect(reopen).toHaveFocus());
    expect(api.state.bodies.map((entry) => entry.route)).toEqual(["close"]);
    expect(api.state.bodies[0]?.csrf).toBe("csrf-discussion");
    expect(screen.getByRole("group", { name: "Status" })).toHaveTextContent("Closed");
    for (const name of ["Approve", "Request rework", "Veto", "Let them talk it out"]) {
      expect(screen.queryByRole("button", { name })).toBeNull();
    }
    expect(screen.queryByRole("button", { name: "Close discussion" })).toBeNull();
    await waitFor(() => expect(said.text()).toContain(CLOSED_NOTICE));
  });

  it("does not offer Close discussion to anyone else", async () => {
    await renderDiscussion(discussion({ opened_by_me: false }), PAGE_URL);
    expect(screen.queryByRole("button", { name: "Close discussion" })).toBeNull();
    expect(screen.getByRole("button", { name: "Let them talk it out" })).toBeInTheDocument();
  });

  it("holds Close discussion while the agents answer, and says why", async () => {
    await renderDiscussion(discussion({ run_state: "running" }), PAGE_URL);
    expect(
      screen.getByRole("button", {
        name: "Close discussion",
        description: "Stop the run before you close it",
      }),
    ).toHaveAttribute("aria-disabled", "true");
  });

  it("lets anyone signed in open a closed discussion again, and says so", async () => {
    const { api, user } = await renderDiscussion(closed({ opened_by_me: false }), PAGE_URL);
    const said = heard();
    expect(screen.getByRole("group", { name: "Status" })).toHaveTextContent("Closed");
    expect(screen.getByRole("group", { name: "Facts" })).toHaveTextContent("Closed");
    await user.click(screen.getByRole("button", { name: "Reopen" }));
    expect(await screen.findByRole("button", { name: "Approve" })).toBeInTheDocument();
    expect(api.state.bodies.map((entry) => entry.route)).toEqual(["reopen"]);
    // Reopen goes with the state for someone who may not close it; the heading takes focus.
    expect(screen.queryByRole("button", { name: "Reopen" })).toBeNull();
    await waitFor(() =>
      expect(screen.getByRole("heading", { level: 1, name: QUESTION })).toHaveFocus(),
    );
    await waitFor(() => expect(said.text()).toContain(REOPENED_NOTICE));
  });

  it("closes from the Ticket's dialog over the Kanban, keeping focus in that dialog", async () => {
    const { user } = await renderDiscussion(discussion(), MODAL_URL);
    const view = screen.getByRole("dialog", { name: QUESTION });
    await user.click(within(view).getByRole("button", { name: "Close discussion" }));
    const ask = await screen.findByRole("dialog", { name: "Close this discussion?" });
    await user.click(within(ask).getByRole("button", { name: "Close discussion" }));
    const reopen = await within(view).findByRole("button", { name: "Reopen" });
    await waitFor(() => expect(reopen).toHaveFocus());
  });

  it("closes a discussion on the board the same way", async () => {
    const { api, user } = await renderDiscussion(boardThread(), BOARD_PAGE_URL);
    await user.click(screen.getByRole("button", { name: "Close discussion" }));
    const dialog = await screen.findByRole("dialog", { name: "Close this discussion?" });
    await user.click(within(dialog).getByRole("button", { name: "Close discussion" }));
    expect(await screen.findByRole("button", { name: "Reopen" })).toBeInTheDocument();
    expect(api.state.bodies.map((entry) => entry.route)).toEqual(["close"]);
    expect(screen.getByRole("heading", { level: 1, name: BOARD_TITLE })).toBeInTheDocument();
  });
});

describe("a closed discussion", () => {
  it("keeps the reply as a comment after the close, which starts no round", async () => {
    const { api, user } = await renderDiscussion(closed(), PAGE_URL);
    const reply = screen.getByRole("textbox", { name: "Reply" });
    expect(reply).toHaveAccessibleDescription(
      "Your comment is added after the discussion was closed. The agents do not answer.",
    );
    api.state.next.messages = closed();
    await user.type(reply, "Noted for the next Loop.");
    await user.click(screen.getByRole("button", { name: "Add comment" }));
    await waitFor(() => expect(api.state.bodies.map((entry) => entry.route)).toEqual(["messages"]));
    expect(api.state.bodies[0]?.body).toEqual({ content: "Noted for the next Loop." });
    expect(screen.queryByRole("button", { name: "Ask again" })).toBeNull();
  });

  it("marks a comment written after closing, in For you and in Raw text", async () => {
    const late = comment("m-late", { content: "Seen too late.", after_closed: true });
    const { user } = await renderDiscussion(
      closed({ messages: [...discussion().messages, late] }),
      PAGE_URL,
    );
    const comments = screen.getByRole("list", { name: "Comments" });
    const items = within(comments).getAllByRole("listitem");
    expect(items).toHaveLength(2);
    expect(items[0]).not.toHaveTextContent("After closing");
    expect(items[1]).toHaveTextContent("After closing");
    expect(items[1]).toHaveTextContent("Seen too late.");
    await user.click(screen.getByRole("tab", { name: "Raw text" }));
    const transcript = screen.getByRole("list", { name: "Transcript" });
    expect(within(transcript).getAllByRole("listitem").at(-1)).toHaveTextContent(
      /After closing\s*Seen too late\./,
    );
  });

  it("links a message to the Ticket it points at", async () => {
    const ref = {
      card_id: "card-1",
      ticket_key: TICKET_KEY,
      title: "Rotate the signing key",
      loop_id: LOOP_ID,
    };
    const pointing = comment("m-ref", { content: "See this one.", ref_ticket: ref });
    await renderDiscussion(
      discussion({ messages: [...discussion().messages, pointing] }),
      PAGE_URL,
    );
    const link = screen.getByRole("link", { name: `${TICKET_KEY} Rotate the signing key` });
    expect(link).toHaveAttribute("href", TICKET_PAGE_URL);
    expect(link.closest("p")).toHaveTextContent(`About ${TICKET_KEY} Rotate the signing key`);
  });
});

describe("About Ticket in the reply", () => {
  it("sends the Ticket's key with the reply", async () => {
    const { api, user } = await renderDiscussion(discussion(), PAGE_URL);
    await user.type(screen.getByRole("textbox", { name: "Reply" }), "Compare with it.");
    await user.type(screen.getByRole("textbox", { name: "About Ticket" }), ` ${TICKET_KEY} `);
    await user.click(screen.getByRole("button", { name: "Ask again" }));
    await waitFor(() =>
      expect(api.state.bodies.find((entry) => entry.route === "messages")?.body).toEqual({
        content: "Compare with it.",
        ticket: TICKET_KEY,
      }),
    );
    await waitFor(() =>
      expect(screen.getByRole("textbox", { name: "About Ticket" })).toHaveValue(""),
    );
  });

  it("shows the server's refusal of an unknown Ticket under the field, which takes focus", async () => {
    const { user } = await renderDiscussion(discussion(), PAGE_URL);
    server.use(
      http.post(apiPath(`${DISCUSSION_PATH}/messages`), () =>
        failure(
          422,
          "validation_failed",
          "The message points at a Ticket that is not on this board",
          {
            field: "ticket",
            ticket: "NOPE-1",
          },
        ),
      ),
    );
    await user.type(screen.getByRole("textbox", { name: "Reply" }), "Compare with it.");
    const field = screen.getByRole("textbox", { name: "About Ticket" });
    await user.type(field, "NOPE-1");
    await user.click(screen.getByRole("button", { name: "Ask again" }));
    await waitFor(() =>
      expect(field).toHaveAccessibleDescription(
        "Error: The message points at a Ticket that is not on this board. Optional: the key of a Ticket on this board.",
      ),
    );
    expect(field).toHaveFocus();
    expect(screen.getByRole("textbox", { name: "Reply" })).toHaveValue("Compare with it.");
    await user.type(field, "2");
    expect(field).toHaveAccessibleDescription("Optional: the key of a Ticket on this board.");
  });
});
