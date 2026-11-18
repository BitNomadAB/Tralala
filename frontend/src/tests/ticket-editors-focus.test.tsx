import { screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { TicketFace } from "@/lib/types";
import { announcer } from "./announcer";
import { ticketCard } from "./msw/cards";
import { cardNote } from "./msw/notes";
import { renderTicket } from "./renderTicket";

const FACE: TicketFace = {
  summary: "Old keys stop working after a day.",
  why: "A leaked key works forever today.",
  if_skipped: "A stolen key keeps opening sessions.",
  pros: ["Leaks stop mattering after a day."],
  cons: ["Long jobs sign in again."],
  steps: ["Make a new key every night."],
};

const faceCard = () => ticketCard({ summary: FACE.summary, face: FACE, description: "Old text" });

const MINE = cardNote();
const SECOND = cardNote({ id: "note-2", text: "Ask the owner first." });

function noteRow(text: string): HTMLElement {
  const item = screen.getByText(text).closest("li");
  if (!item) throw new Error(`no note holds "${text}"`);
  return item;
}

describe("the focus around the face's editor", () => {
  it("starts on the first field, and Cancel gives it back to Edit", async () => {
    const { user } = await renderTicket(faceCard());
    const edit = screen.getByRole("button", { name: "Edit what will be done" });
    await user.click(edit);
    const form = screen.getByRole("form", { name: "Edit the face" });
    expect(within(form).getByLabelText("Summary")).toHaveFocus();
    await user.click(within(form).getByRole("button", { name: "Cancel" }));
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Edit what will be done" })).toHaveFocus(),
    );
  });

  it("gives it back to Edit after a save, and says the face is saved", async () => {
    const { user } = await renderTicket(faceCard());
    await user.click(screen.getByRole("button", { name: "Edit what will be done" }));
    const form = screen.getByRole("form", { name: "Edit the face" });
    await user.click(within(form).getByRole("button", { name: "Save" }));
    const edit = await screen.findByRole("button", { name: "Edit what will be done" });
    await waitFor(() => expect(edit).toHaveFocus());
    await waitFor(() => expect(announcer()).toHaveTextContent("Face saved"));
  });
});

describe("the focus around the description's editor", () => {
  it("starts in the field; Save and Cancel give it back to Edit description", async () => {
    const { user } = await renderTicket(faceCard());
    await user.click(screen.getByRole("tab", { name: "Raw text" }));
    await user.click(screen.getByRole("button", { name: "Edit description" }));
    const field = screen.getByLabelText("Card description (Markdown)");
    await waitFor(() => expect(field).toHaveFocus());
    await user.click(screen.getByRole("button", { name: "Cancel" }));
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Edit description" })).toHaveFocus(),
    );

    await user.click(screen.getByRole("button", { name: "Edit description" }));
    await user.type(screen.getByLabelText("Card description (Markdown)"), " and new");
    await user.click(screen.getByRole("button", { name: "Save description" }));
    const edit = await screen.findByRole("button", { name: "Edit description" });
    await waitFor(() => expect(edit).toHaveFocus());
    await waitFor(() => expect(announcer()).toHaveTextContent("Description saved"));
  });
});

describe("the focus around the notes", () => {
  it("starts in the note's field; Cancel and Save give it back to its Edit", async () => {
    const { user } = await renderTicket(ticketCard(), undefined, { notes: [MINE] });
    await screen.findByText(MINE.text);
    await user.click(within(noteRow(MINE.text)).getByRole("button", { name: "Edit" }));
    expect(screen.getByRole("textbox", { name: "Edit the note" })).toHaveFocus();
    await user.click(screen.getByRole("button", { name: "Cancel" }));
    await waitFor(() =>
      expect(within(noteRow(MINE.text)).getByRole("button", { name: "Edit" })).toHaveFocus(),
    );

    await user.click(within(noteRow(MINE.text)).getByRole("button", { name: "Edit" }));
    await user.type(screen.getByRole("textbox", { name: "Edit the note" }), " Today.");
    await user.click(screen.getByRole("button", { name: "Save" }));
    const edited = `${MINE.text} Today.`;
    await screen.findByText(edited);
    await waitFor(() =>
      expect(within(noteRow(edited)).getByRole("button", { name: "Edit" })).toHaveFocus(),
    );
    await waitFor(() => expect(announcer()).toHaveTextContent("Note saved"));
  });

  it("hands the focus to the next note after a delete, then to Your notes", async () => {
    const { user } = await renderTicket(ticketCard(), undefined, { notes: [MINE, SECOND] });
    await screen.findByText(SECOND.text);
    await user.click(within(noteRow(MINE.text)).getByRole("button", { name: "Edit" }));
    await user.click(screen.getByRole("button", { name: "Delete" }));
    await user.click(screen.getByRole("button", { name: "Delete" }));
    await waitFor(() => expect(screen.queryByText(MINE.text)).toBeNull());
    await waitFor(() =>
      expect(within(noteRow(SECOND.text)).getByRole("button", { name: "Edit" })).toHaveFocus(),
    );
    await waitFor(() => expect(announcer()).toHaveTextContent("Note deleted"));

    await user.click(within(noteRow(SECOND.text)).getByRole("button", { name: "Edit" }));
    await user.click(screen.getByRole("button", { name: "Delete" }));
    await user.click(screen.getByRole("button", { name: "Delete" }));
    await waitFor(() => expect(screen.queryByText(SECOND.text)).toBeNull());
    await waitFor(() =>
      expect(screen.getByText("Your notes", { selector: "summary" })).toHaveFocus(),
    );
  });

  it("keeps the composer's focus after a new note, and says it is saved", async () => {
    const { user } = await renderTicket();
    const box = screen.getByRole("textbox", { name: "Add a note" });
    await user.type(box, "Ask the owner first.");
    await user.click(screen.getByRole("button", { name: "Save note" }));
    await screen.findByText("Ask the owner first.", { selector: "p" });
    await waitFor(() => expect(box).toHaveFocus());
    await waitFor(() => expect(announcer()).toHaveTextContent("Note saved"));
  });
});

describe("a posted comment", () => {
  it("is announced, and the focus stays in the emptied field", async () => {
    const { user } = await renderTicket();
    const box = screen.getByRole("textbox", { name: "New comment" });
    await user.type(box, "Looks right.");
    await user.click(screen.getByRole("button", { name: "Send comment" }));
    await waitFor(() => expect(box).toHaveValue(""));
    await waitFor(() => expect(announcer()).toHaveTextContent("Comment posted"));
  });
});
