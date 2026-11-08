import { screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ticketCard } from "./msw/cards";
import { QUESTION, TICKET_KEY } from "./msw/discussions";
import { MODAL_URL, PAGE_URL, renderDiscussion, TICKET_PAGE_URL } from "./renderDiscussion";

const TICKET_TITLE = ticketCard().title;

/** Where the router is; read by selector, since an open dialog hides the probe from the a11y tree. */
function location() {
  const read = (name: string) =>
    document.querySelector(`output[aria-label="${name}"]`)?.textContent ?? null;
  return { path: read("Location"), query: read("Query") };
}

describe("a discussion inside its Ticket", () => {
  it("opens in the Ticket's dialog on the Loop page and goes back to the Ticket", async () => {
    const { user } = await renderDiscussion(undefined, MODAL_URL);
    const dialog = screen.getByRole("dialog", { name: QUESTION });
    expect(within(dialog).queryByRole("heading", { name: TICKET_TITLE })).toBeNull();
    await user.click(within(dialog).getByRole("button", { name: "Back to the Ticket" }));
    expect(await screen.findByRole("dialog", { name: TICKET_TITLE })).toBeInTheDocument();
    expect(location().query).toBe("?card=card-1");
  });

  it("drops the Ticket and the discussion from the URL on Close", async () => {
    const { user } = await renderDiscussion(undefined, MODAL_URL);
    await user.click(screen.getByRole("button", { name: "Close dialog" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(location().query).toBe("");
  });

  it("opens as a page of its Ticket with the breadcrumb, and goes back to the Ticket's page", async () => {
    const { user } = await renderDiscussion(undefined, MODAL_URL);
    await user.click(screen.getByRole("button", { name: "Open as page" }));
    expect(await screen.findByRole("heading", { level: 1, name: QUESTION })).toBeInTheDocument();
    expect(location().path).toBe(PAGE_URL);
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(screen.queryByRole("button", { name: "Open as page" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Close dialog" })).toBeNull();
    await user.click(screen.getByRole("button", { name: "Back to the Ticket" }));
    expect(
      await screen.findByRole("heading", { level: 1, name: TICKET_TITLE }),
    ).toBeInTheDocument();
    expect(location().path).toBe(TICKET_PAGE_URL);
  });

  it("renders the page from its own URL with the breadcrumb Board, Loop, Ticket and question", async () => {
    await renderDiscussion(undefined, PAGE_URL);
    const crumbs = screen.getByRole("navigation", { name: "Breadcrumb" });
    await waitFor(() =>
      expect(crumbs).toHaveTextContent(`Platform/SES-1 Session expiry/${TICKET_KEY}/${QUESTION}`),
    );
    expect(within(crumbs).getByRole("link", { name: TICKET_KEY })).toHaveAttribute(
      "href",
      TICKET_PAGE_URL,
    );
    expect(within(crumbs).getByText(QUESTION)).toHaveAttribute("aria-current", "page");
  });
});
