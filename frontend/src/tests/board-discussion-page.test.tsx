import { screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { BOARD_QUESTION, BOARD_TITLE, boardThread } from "./msw/boardDiscussions";
import { discussion, QUESTION, TICKET_KEY } from "./msw/discussions";
import {
  BOARD_PAGE_URL,
  BOARD_URL,
  PAGE_URL,
  renderDiscussion,
  TICKET_PAGE_URL,
} from "./renderDiscussion";

function location(): string | null {
  return document.querySelector('output[aria-label="Location"]')?.textContent ?? null;
}

describe("a discussion on the board", () => {
  it("has its own address, with the title as the heading and the question under it", async () => {
    await renderDiscussion(boardThread(), BOARD_PAGE_URL);
    const heading = screen.getByRole("heading", { level: 1, name: BOARD_TITLE });
    expect(heading.nextElementSibling).toHaveTextContent(BOARD_QUESTION);
    expect(screen.queryByText(TICKET_KEY)).toBeNull();
    const crumbs = screen.getByRole("navigation", { name: "Breadcrumb" });
    await waitFor(() => expect(crumbs).toHaveTextContent(`Platform/Discussions/${BOARD_TITLE}`));
    expect(within(crumbs).getByRole("link", { name: "Platform" })).toHaveAttribute(
      "href",
      BOARD_URL,
    );
    expect(within(crumbs).getByRole("link", { name: "Discussions" })).toHaveAttribute(
      "href",
      "/discussions",
    );
    expect(within(crumbs).getByText(BOARD_TITLE)).toHaveAttribute("aria-current", "page");
    await waitFor(() => expect(document.title).toBe(`${BOARD_TITLE} · Platform · Tralala`));
  });

  it("shows the board in the rail where a Ticket's discussion shows the Ticket", async () => {
    await renderDiscussion(boardThread(), BOARD_PAGE_URL);
    const facts = screen.getByRole("group", { name: "Facts" });
    expect(within(facts).queryByText("Ticket")).toBeNull();
    expect(within(facts).getByText("Board")).toBeInTheDocument();
    expect(await within(facts).findByRole("link", { name: "Platform" })).toHaveAttribute(
      "href",
      BOARD_URL,
    );
  });

  it("goes back to the board", async () => {
    const { user } = await renderDiscussion(boardThread(), BOARD_PAGE_URL);
    expect(screen.queryByRole("button", { name: "Back to the Ticket" })).toBeNull();
    await user.click(screen.getByRole("button", { name: "Back to the board" }));
    expect(await screen.findByRole("heading", { name: "Board page" })).toBeInTheDocument();
    expect(location()).toBe(BOARD_URL);
  });

  it("is marked read once when it opens, not again as the view changes", async () => {
    const { api, user } = await renderDiscussion(boardThread(), BOARD_PAGE_URL);
    await waitFor(() => expect(api.state.reads).toBe(1));
    await user.click(screen.getByRole("tab", { name: "Raw text" }));
    await user.click(screen.getByRole("tab", { name: "For you" }));
    expect(api.state.reads).toBe(1);
  });

  it("still shows a Ticket's discussion opened at the board's address with its Ticket", async () => {
    await renderDiscussion(discussion(), BOARD_PAGE_URL);
    const crumbs = screen.getByRole("navigation", { name: "Breadcrumb" });
    await waitFor(() =>
      expect(crumbs).toHaveTextContent(`Platform/SES-1 Session expiry/${TICKET_KEY}/${QUESTION}`),
    );
    expect(within(crumbs).getByRole("link", { name: TICKET_KEY })).toHaveAttribute(
      "href",
      TICKET_PAGE_URL,
    );
    expect(screen.getByRole("button", { name: "Back to the Ticket" })).toBeInTheDocument();
  });
});

describe("a discussion on a Ticket", () => {
  it("is marked read once when its page opens, and keeps the question as its heading", async () => {
    const { api } = await renderDiscussion(discussion(), PAGE_URL);
    expect(screen.getByRole("heading", { level: 1, name: QUESTION })).toBeInTheDocument();
    await waitFor(() => expect(api.state.reads).toBe(1));
  });
});
