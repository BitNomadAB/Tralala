import { renderHook, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { notesHint } from "@/features/cards/ticketText";
import { CARD_EVENT_TYPES, useCardEvents } from "@/features/cards/useCardEvents";
import { noteErrorText } from "@/features/cards/useTicketNotes";
import { ApiError } from "@/lib/api";
import { ticketCard } from "./msw/cards";
import { BOARD_ID, LOOP_ID } from "./msw/loops";
import { cardNote, NOTES_PATH } from "./msw/notes";
import { CSRF, renderTicket } from "./renderTicket";

const MINE = cardNote();
const THEIRS = cardNote({
  id: "note-2",
  author: "Grace Hopper",
  author_actor_id: "user-2",
  text: "The two questions I asked are in it.",
});

function notesList() {
  return screen.getByRole("list", { name: "Your notes" });
}

function row(text: string): HTMLElement {
  const item = screen.getByText(text).closest("li");
  if (!item) throw new Error(`no note holds "${text}"`);
  return item;
}

describe("Your notes", () => {
  it("lists each note with its author and date, and Edit only on the reader's own", async () => {
    await renderTicket(ticketCard(), undefined, { notes: [MINE, THEIRS] });
    await waitFor(() => expect(within(notesList()).getAllByRole("listitem")).toHaveLength(2));
    expect(screen.getByText("2 notes")).toBeInTheDocument();
    const mine = row(MINE.text);
    expect(mine).toHaveTextContent(
      /^AMTry it on this Loop's analysis first\.Ada Member · .+ · Edit$/,
    );
    expect(within(mine).getByRole("button", { name: "Edit" })).toBeInTheDocument();
    const theirs = row(THEIRS.text);
    expect(theirs).toHaveTextContent("Grace Hopper · ");
    expect(within(theirs).queryByRole("button", { name: "Edit" })).toBeNull();
    // A note is there: the section is open from the start, though the Ticket has a face or not.
    expect(
      screen.getByText("Your notes", { selector: "summary" }).closest("details"),
    ).toHaveAttribute("open");
  });

  it("adds a note through the notes route, with the CSRF header", async () => {
    const { view, user } = await renderTicket();
    const box = screen.getByRole("textbox", { name: "Add a note" });
    expect(box).toHaveAttribute(
      "placeholder",
      "Add a note about this Ticket. Written by you, never by an agent.",
    );
    expect(box).toHaveAccessibleDescription(
      "Your notes stay with the Ticket and your coding agent can read them.",
    );
    const save = screen.getByRole("button", { name: "Save note" });
    expect(save).toBeDisabled();
    await user.type(box, "  Ask the owner first.  ");
    await user.click(save);
    await waitFor(() =>
      expect(within(notesList()).getByText("Ask the owner first.")).toBeVisible(),
    );
    expect(box).toHaveValue("");
    expect(view.notes.writes).toEqual([
      { route: `POST ${NOTES_PATH}`, body: { text: "Ask the owner first." } },
    ]);
    expect(view.state.csrf).toEqual([CSRF]);
    expect(screen.getByText("1 note")).toBeInTheDocument();
  });

  it("edits the author's note with its version, then deletes it", async () => {
    const { view, user } = await renderTicket(ticketCard(), undefined, { notes: [MINE] });
    await screen.findByText(MINE.text);
    await user.click(within(row(MINE.text)).getByRole("button", { name: "Edit" }));
    const field = screen.getByRole("textbox", { name: "Edit the note" });
    await user.clear(field);
    await user.type(field, "Try it on the next Loop instead.");
    await user.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(screen.getByText("Try it on the next Loop instead.")).toBeVisible());
    await user.click(
      within(row("Try it on the next Loop instead.")).getByRole("button", { name: "Edit" }),
    );
    await user.click(screen.getByRole("button", { name: "Delete" }));
    await waitFor(() => expect(screen.queryByRole("list", { name: "Your notes" })).toBeNull());
    expect(view.notes.writes).toEqual([
      {
        route: `PATCH ${NOTES_PATH}/note-1`,
        body: { text: "Try it on the next Loop instead.", version: 1 },
      },
      { route: `DELETE ${NOTES_PATH}/note-1`, body: null },
    ]);
    expect(screen.getByText("0 notes")).toBeInTheDocument();
  });

  it("says so when the note changed since it was read", async () => {
    const { view, user } = await renderTicket(ticketCard(), undefined, { notes: [MINE] });
    await screen.findByText(MINE.text);
    await user.click(within(row(MINE.text)).getByRole("button", { name: "Edit" }));
    view.notes.notes = [{ ...MINE, version: 4 }];
    await user.type(screen.getByRole("textbox", { name: "Edit the note" }), " Now.");
    await user.click(screen.getByRole("button", { name: "Save" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Someone changed this note. Reload to see it.",
    );
  });

  it("shows a completed Loop's notes with no composer and says why", async () => {
    await renderTicket(ticketCard(), undefined, { notes: [MINE], loop: { stage: "completed" } });
    expect(await screen.findByText("This Loop is completed; notes are read-only.")).toBeVisible();
    expect(screen.queryByRole("textbox", { name: "Add a note" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Save note" })).toBeNull();
    expect(within(row(MINE.text)).queryByRole("button", { name: "Edit" })).toBeNull();
  });

  it("words the server's refusals and counts the notes", () => {
    const refusal = (code: string) => new ApiError("refused", { code, status: 409 });
    expect(noteErrorText(refusal("note_author_only"))).toBe(
      "Only the person who wrote a note can change it.",
    );
    expect(noteErrorText(refusal("loop_read_only"))).toBe(
      "This Loop is completed; notes are read-only.",
    );
    expect(notesHint(1)).toBe("1 note");
    expect(notesHint(3)).toBe("3 notes");
  });
});

/** A stand-in for the browser's EventSource that records its listeners. */
class FakeEventSource {
  static last: FakeEventSource | null = null;
  readonly listeners = new Map<string, () => void>();
  onopen: (() => void) | null = null;
  onerror: (() => void) | null = null;
  constructor(readonly url: string) {
    FakeEventSource.last = this;
  }
  addEventListener(type: string, listener: () => void) {
    this.listeners.set(type, listener);
  }
  removeEventListener(type: string) {
    this.listeners.delete(type);
  }
  close() {
    this.listeners.clear();
  }
}

describe("the card's events", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.useRealTimers();
  });

  it("refetch on a note being added, edited or deleted", () => {
    expect(CARD_EVENT_TYPES).toEqual(
      expect.arrayContaining(["note_added", "note_edited", "note_deleted"]),
    );
    vi.useFakeTimers();
    vi.stubGlobal("EventSource", FakeEventSource);
    const onEvent = vi.fn();
    renderHook(() => useCardEvents(BOARD_ID, LOOP_ID, "card-1", onEvent));
    const source = FakeEventSource.last;
    expect(source?.url).toBe(`/api/v1/boards/${BOARD_ID}/loops/${LOOP_ID}/cards/card-1/events`);
    source?.listeners.get("note_added")?.();
    vi.advanceTimersByTime(200);
    expect(onEvent).toHaveBeenCalledOnce();
    source?.listeners.get("note_deleted")?.();
    vi.advanceTimersByTime(200);
    expect(onEvent).toHaveBeenCalledTimes(2);
  });
});
