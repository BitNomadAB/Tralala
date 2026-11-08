import { screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { CARD_PATH, ticketCard } from "./msw/cards";
import { MEMBER } from "./msw/session";
import { PHASE_NAME } from "./msw/ticketView";
import { CSRF, renderTicket, TICKET_URL, writes } from "./renderTicket";

const TITLE = "Rotate the signing key";
const KEY = "SES-1-PH01-001";

function dialog() {
  return screen.getByRole("dialog", { name: TITLE });
}

/** The quiet "more" menu of the actions row, once it is open. */
function menu() {
  return screen.getByRole("list", { name: "More actions" });
}

describe("the Ticket over the Kanban", () => {
  it("shows the head, the actions and the rail", async () => {
    await renderTicket(ticketCard({ summary: "Old keys stop working after a day." }));
    const modal = dialog();
    const heading = within(modal).getByRole("heading", { level: 2, name: TITLE });
    expect(heading).toHaveClass("text-balance");
    // The lead under the title is the summary; For you does not repeat it.
    expect(heading.nextElementSibling).toHaveTextContent("Old keys stop working after a day.");
    const forYou = within(modal).getByRole("tabpanel", { name: "For you" });
    expect(within(forYou).queryByText("Old keys stop working after a day.")).toBeNull();
    const copyKey = within(modal).getByRole("button", { name: `Copy key ${KEY}` });
    expect(copyKey.parentElement).toHaveClass("font-mono");
    expect(copyKey.parentElement).toHaveTextContent(KEY);
    expect(await within(modal).findByText(PHASE_NAME, { selector: "b" })).toBeInTheDocument();
    expect(modal).toHaveTextContent(`Phase 1 · ${PHASE_NAME}`);
    for (const name of ["Open as page", "Close dialog", "Start work", "Mark as waiting"]) {
      expect(within(modal).getByRole("button", { name })).toBeInTheDocument();
    }
    for (const name of ["Comment", "More actions"]) {
      expect(within(modal).getByRole("button", { name })).toBeInTheDocument();
    }
    // Add file in the actions row, and again on the Files section.
    expect(within(modal).getAllByRole("button", { name: "Add file" })).toHaveLength(2);
    const rail = within(modal).getByRole("complementary", { name: "Status and details" });
    expect(within(rail).getByRole("button", { name: "Column: Backlog" })).toBeInTheDocument();
    expect(rail).toHaveTextContent("Ready· nothing holds it up");
    expect(within(rail).getByRole("button", { name: "Owner: None" })).toBeInTheDocument();
    expect(rail).toHaveTextContent("Created");
    expect(rail).toHaveTextContent("from the RoadMap");
    expect(within(rail).getByText("More")).toBeInTheDocument();
    // One primary decision: Mark complete waits until the work has started.
    expect(within(modal).queryByRole("button", { name: "Mark complete" })).toBeNull();
  });

  it("starts work: assigns the person, moves to the next column, then offers Mark complete", async () => {
    const { view, user } = await renderTicket();
    await user.click(screen.getByRole("button", { name: "Start work" }));
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Column: In Progress" })).toBeInTheDocument(),
    );
    expect(writes(view)).toEqual([
      { route: `PATCH ${CARD_PATH}`, body: { version: 3, assignee_actor_id: MEMBER.id } },
      {
        route: `POST ${CARD_PATH}/move`,
        body: { version: 4, list_id: "list-2", position: 10_000 },
      },
    ]);
    expect(view.state.csrf).toEqual([CSRF, CSRF]);
    expect(screen.getByRole("button", { name: `Owner: ${MEMBER.name}` })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Start work" })).toBeNull();
    expect(screen.getByRole("button", { name: "Mark complete" })).toBeEnabled();
  });

  it("only moves a Ticket that already has an owner", async () => {
    const { view, user } = await renderTicket(
      ticketCard({ assignee_actor_id: "user-2", assignee_name: "Grace Hopper" }),
    );
    await user.click(screen.getByRole("button", { name: "Start work" }));
    await waitFor(() => expect(writes(view)).toHaveLength(1));
    expect(writes(view)[0]?.route).toBe(`POST ${CARD_PATH}/move`);
  });

  it("offers Mark complete past the first column, and nothing once completed", async () => {
    const { view, user } = await renderTicket(ticketCard({ list_id: "list-2" }));
    expect(screen.queryByRole("button", { name: "Start work" })).toBeNull();
    await user.click(screen.getByRole("button", { name: "Mark complete" }));
    await waitFor(() => expect(screen.queryByRole("button", { name: "Mark complete" })).toBeNull());
    expect(writes(view)).toEqual([
      { route: `PATCH ${CARD_PATH}`, body: { version: 3, completed: true } },
    ]);
    expect(screen.queryByRole("button", { name: "Start work" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Mark as waiting" })).toBeNull();
    // A completed Ticket can be reopened from the quiet menu.
    await user.click(screen.getByRole("button", { name: "More actions" }));
    expect(screen.getByRole("button", { name: "Mark incomplete" })).toBeInTheDocument();
  });

  it("says what holds Mark complete back while the Ticket waits", async () => {
    await renderTicket(
      ticketCard({ list_id: "list-2", waiting_for: "decision", waiting_reason: "Which store?" }),
    );
    const complete = screen.getByRole("button", { name: "Mark complete" });
    expect(complete).toBeDisabled();
    expect(complete).toHaveAttribute("title", "Clear the wait first");
  });

  it("edits the title inline: Enter saves with the version, Escape keeps it", async () => {
    const { view, user, onClose } = await renderTicket();
    await user.click(screen.getByRole("button", { name: TITLE }));
    await user.keyboard("{Escape}");
    expect(screen.getByRole("heading", { name: TITLE })).toBeInTheDocument();
    // Escape in the field is the field's: the dialog stays open.
    expect(onClose).not.toHaveBeenCalled();
    await user.click(screen.getByRole("button", { name: TITLE }));
    const field = screen.getByRole("textbox", { name: "Title" });
    await user.clear(field);
    await user.type(field, "Rotate the key every day{Enter}");
    expect(
      await screen.findByRole("heading", { name: "Rotate the key every day" }),
    ).toBeInTheDocument();
    expect(writes(view)).toEqual([
      { route: `PATCH ${CARD_PATH}`, body: { version: 3, title: "Rotate the key every day" } },
    ]);
  });

  it("tells the person to reload when someone changed the Ticket first", async () => {
    const { view, user } = await renderTicket();
    view.state.card = { ...view.state.card, version: 9 };
    await user.click(screen.getByRole("button", { name: TITLE }));
    await user.type(screen.getByRole("textbox", { name: "Title" }), " now{Enter}");
    expect(
      await screen.findByText("Someone changed this Ticket. Reload to see it."),
    ).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: TITLE })).toBeInTheDocument();
  });

  it("copies the key and says so", async () => {
    const { user } = await renderTicket();
    await user.click(screen.getByRole("button", { name: `Copy key ${KEY}` }));
    expect(await screen.findByText("Copied")).toBeInTheDocument();
    expect(await navigator.clipboard.readText()).toBe(KEY);
  });

  it("copies the Ticket's page link from the quiet menu", async () => {
    const { user } = await renderTicket();
    await user.click(screen.getByRole("button", { name: "More actions" }));
    await user.click(within(menu()).getByRole("button", { name: "Copy link" }));
    expect(await screen.findByText("Link copied")).toBeInTheDocument();
    expect(await navigator.clipboard.readText()).toBe(`${window.location.origin}${TICKET_URL}`);
  });

  it("archives from the quiet menu and closes", async () => {
    const { view, user, onClose } = await renderTicket();
    await user.click(screen.getByRole("button", { name: "More actions" }));
    await user.click(within(menu()).getByRole("button", { name: "Archive" }));
    await waitFor(() => expect(onClose).toHaveBeenCalledOnce());
    expect(writes(view)).toEqual([{ route: `POST ${CARD_PATH}/archive`, body: null }]);
  });

  it("focuses the composer on Comment, opens the picker on Add file and the wait on Mark as waiting", async () => {
    const { user } = await renderTicket();
    await user.click(screen.getByRole("button", { name: "Comment" }));
    expect(screen.getByRole("textbox", { name: /comment/i })).toHaveFocus();
    const picker = screen.getByLabelText("Choose files to attach");
    let opened = 0;
    picker.addEventListener("click", () => {
      opened += 1;
    });
    // The head's Add file and the Files section's open the same picker.
    for (const addFile of screen.getAllByRole("button", { name: "Add file" })) {
      await user.click(addFile);
    }
    expect(opened).toBe(2);
    await user.click(screen.getByRole("button", { name: "Mark as waiting" }));
    expect(screen.getByLabelText("It waits for")).toHaveFocus();
  });

  it("closes the open column menu on Escape and keeps the dialog", async () => {
    const { user, onClose } = await renderTicket();
    await user.click(screen.getByRole("button", { name: "Column: Backlog" }));
    expect(screen.getByRole("listbox", { name: "Column" })).toBeInTheDocument();
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("listbox")).toBeNull();
    expect(dialog()).toBeInTheDocument();
    expect(onClose).not.toHaveBeenCalled();
    await user.keyboard("{Escape}");
    expect(onClose).toHaveBeenCalledOnce();
  });

  it("opens as a page with the breadcrumb and a way back to the board", async () => {
    const { user } = await renderTicket();
    await user.click(screen.getByRole("button", { name: "Open as page" }));
    expect(await screen.findByRole("heading", { level: 1, name: TITLE })).toBeInTheDocument();
    expect(screen.getByRole("status", { name: "Location" })).toHaveTextContent(TICKET_URL);
    expect(screen.queryByRole("dialog")).toBeNull();
    const crumbs = screen.getByRole("navigation", { name: "Breadcrumb" });
    await waitFor(() =>
      expect(crumbs).toHaveTextContent(
        `Platform/SES-1 Session expiry/Phase 1 · ${PHASE_NAME}/${KEY}`,
      ),
    );
    expect(within(crumbs).getByText(KEY)).toHaveAttribute("aria-current", "page");
    expect(screen.getByRole("link", { name: "Back to the board" })).toHaveAttribute(
      "href",
      "/boards/board-1/loops/loop-1",
    );
    expect(screen.queryByRole("button", { name: "Open as page" })).toBeNull();
    expect(screen.getByRole("button", { name: "Start work" })).toBeInTheDocument();
  });

  it("renders the page from its own URL", async () => {
    await renderTicket(ticketCard(), TICKET_URL);
    expect(screen.getByRole("heading", { level: 1, name: TITLE })).toBeInTheDocument();
    expect(screen.getByRole("navigation", { name: "Breadcrumb" })).toHaveTextContent(KEY);
  });
});
