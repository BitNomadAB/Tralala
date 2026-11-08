import { screen, waitFor, within } from "@testing-library/react";
import { http } from "msw";
import { describe, expect, it } from "vitest";
import type { TicketFace } from "@/lib/types";
import { CARD_PATH, ticketCard } from "./msw/cards";
import { apiPath, failure } from "./msw/envelope";
import { server } from "./msw/server";
import { PREREQUISITE_KEY } from "./msw/ticketView";
import { renderTicket, writes } from "./renderTicket";

const FACE: TicketFace = {
  summary: "Old keys stop working after a day.",
  why: "A leaked key works forever today. Nobody notices.",
  if_skipped: "A stolen key keeps opening sessions.",
  pros: ["Leaks stop mattering after a day.", "Nothing to remember.", "Same for every board."],
  cons: ["Long jobs sign in again.", "One more setting."],
  steps: [
    "Make a new key every night.",
    "Keep yesterday's key for one more day.",
    "Refuse a session signed by an older key.",
    "Show the key's age in Settings.",
    "Say in the sign-in page why a session ended.",
  ],
};

const CRITERION = "The signing route rotates `session_keys` at 00:00 UTC";
const EVIDENCE = "pytest tests/unit/test_keys.py passes";

function faceCard(extra: Parameters<typeof ticketCard>[0] = {}) {
  return ticketCard({
    summary: FACE.summary,
    summary_source: "plan",
    face: FACE,
    description: "## Source\n\nRotate `signing_key` in `core/keys.py`.",
    acceptance_criteria: [CRITERION, "A test proves the old key is refused"],
    expected_evidence: [EVIDENCE],
    ...extra,
  });
}

const panel = (name: "For you" | "Raw text") => screen.getByRole("tabpanel", { name });

describe("For you", () => {
  it("shows the steps, the foot line and the three sections, and no AI text", async () => {
    await renderTicket(faceCard());
    const forYou = panel("For you");
    await within(forYou).findByText("0 notes");
    const steps = within(forYou).getByRole("list", { name: "Steps" });
    expect(within(steps).getAllByRole("listitem")).toHaveLength(5);
    expect(steps).toHaveTextContent("1Make a new key every night.");
    expect(forYou).toHaveTextContent(
      "Five of five. A Ticket that needs more steps is split into another Ticket when the RoadMap is written.",
    );
    const titles = Array.from(forYou.querySelectorAll("summary")).map((node) => node.textContent);
    expect(titles).toEqual([
      "Why it is needed",
      "If we skip it",
      "Pro and con3 for, 2 against",
      "Your notes0 notes",
    ]);
    expect(within(forYou).getByRole("list", { name: "For" })).toHaveTextContent("+Nothing");
    expect(within(forYou).getByRole("list", { name: "Against" })).toHaveTextContent("–One more");
    expect(forYou).toHaveTextContent(FACE.why);
    for (const text of [CRITERION, EVIDENCE, "signing_key", "Written before Tickets"]) {
      expect(forYou).not.toHaveTextContent(text);
    }
  });

  it("counts fewer than five steps and leaves out a section the face has nothing for", async () => {
    await renderTicket(
      faceCard({ face: { ...FACE, if_skipped: "", pros: [], cons: [], steps: ["One."] } }),
    );
    const forYou = panel("For you");
    await within(forYou).findByText("0 notes");
    expect(forYou).toHaveTextContent("1 of 5");
    const titles = Array.from(forYou.querySelectorAll("summary")).map((node) => node.textContent);
    expect(titles).toEqual(["Why it is needed", "Your notes0 notes"]);
  });

  it("shows a Ticket without a face by its description, with the quiet line and only Your notes", async () => {
    await renderTicket(ticketCard({ description: "## Launch plan\n\n- **Publish** the notes" }));
    const forYou = panel("For you");
    expect(within(forYou).getByRole("heading", { name: "Launch plan" })).toBeInTheDocument();
    expect(forYou).toHaveTextContent("Written before Tickets had a plain summary.");
    const notes = forYou.querySelectorAll("details");
    expect(notes).toHaveLength(1);
    expect(notes[0]).toHaveTextContent("Your notes");
    // Open from the start: the Ticket has no face to read first.
    expect(notes[0]).toHaveAttribute("open");
  });
});

describe("Raw text", () => {
  it("shows what the agent wrote as it is, and remembers the choice while the view is open", async () => {
    const { user } = await renderTicket(faceCard());
    await user.click(screen.getByRole("tab", { name: "Raw text" }));
    const raw = panel("Raw text");
    expect(raw).toHaveTextContent(
      "Written by the agent that planned the Loop. Read over /mcp by your coding session.",
    );
    const labels = within(raw)
      .getAllByRole("heading", { level: 4 })
      .map((node) => node.textContent);
    expect(labels).toEqual([
      "Summary for AI",
      "Description",
      "Accepted when",
      "Evidence",
      "Plan entry",
    ]);
    const pre = Array.from(raw.querySelectorAll("pre")).map((node) => node.textContent);
    expect(pre[1]).toBe("## Source\n\nRotate `signing_key` in `core/keys.py`.");
    expect(pre[2]).toBe(`${CRITERION}\nA test proves the old key is refused`);
    expect(pre[3]).toBe(EVIDENCE);
    const entry: unknown = JSON.parse(pre[4] ?? "");
    expect(entry).toEqual({
      id: "SES-1-PH01-001",
      title: "SES-1-PH01-001",
      phase: 1,
      required_actor: "any",
      execution_mode: "normal",
      depends_on: [PREREQUISITE_KEY],
      workplace: "unknown",
    });
    // Switching the Activity tab leaves the choice as it is.
    await user.click(screen.getByRole("tab", { name: "History" }));
    expect(screen.getByRole("tab", { name: "Raw text" })).toHaveAttribute("aria-selected", "true");
    expect(screen.queryByRole("button", { name: "Edit what will be done" })).toBeNull();
  });

  it("leaves out the blocks an unplanned Ticket has nothing for", async () => {
    const { user } = await renderTicket(ticketCard({ plan_item_id: null, ticket_key: null }));
    await user.click(screen.getByRole("tab", { name: "Raw text" }));
    const labels = within(panel("Raw text"))
      .getAllByRole("heading", { level: 4 })
      .map((node) => node.textContent);
    // The description stays, empty, so a person can write one.
    expect(labels).toEqual(["Description"]);
  });

  it("edits the description inline and saves it with the version", async () => {
    const { view, user } = await renderTicket(faceCard());
    await user.click(screen.getByRole("tab", { name: "Raw text" }));
    await user.click(screen.getByRole("button", { name: "Edit description" }));
    const field = screen.getByLabelText("Card description (Markdown)");
    const save = screen.getByRole("button", { name: "Save description" });
    expect(save).toBeDisabled();
    await user.clear(field);
    await user.type(field, "Rotate daily.");
    await user.click(screen.getByRole("tab", { name: "Preview" }));
    expect(screen.getByRole("tabpanel", { name: "Preview" })).toHaveTextContent("Rotate daily.");
    await user.click(save);
    await waitFor(() => expect(screen.queryByLabelText("Card description (Markdown)")).toBeNull());
    expect(writes(view)).toEqual([
      { route: `PATCH ${CARD_PATH}`, body: { version: 3, description: "Rotate daily." } },
    ]);
    expect(panel("Raw text")).toHaveTextContent("Rotate daily.");
    expect(screen.getByRole("tab", { name: "Raw text" })).toHaveAttribute("aria-selected", "true");
  });

  it("offers no edit on a completed Loop", async () => {
    const { user } = await renderTicket(faceCard(), undefined, { loop: { stage: "completed" } });
    await waitFor(() =>
      expect(screen.queryByRole("button", { name: "Edit what will be done" })).toBeNull(),
    );
    await user.click(screen.getByRole("tab", { name: "Raw text" }));
    expect(screen.queryByRole("button", { name: "Edit description" })).toBeNull();
  });
});

describe("editing the face", () => {
  it("shows live counters and sends the whole face with the version", async () => {
    const { view, user } = await renderTicket(faceCard());
    await user.click(screen.getByRole("button", { name: "Edit what will be done" }));
    const form = screen.getByRole("form", { name: "Edit the face" });
    expect(form).toHaveTextContent("7 of 20 words");
    expect(form).toHaveTextContent("5 of 5 steps");
    expect(form).toHaveTextContent("2 of 3 sentences");
    expect(form).toHaveTextContent("3 of 3 points");
    const steps = within(form).getByLabelText("What will be done");
    await user.clear(steps);
    await user.type(steps, "Make a new key every night.{Enter}Refuse an older key.");
    expect(form).toHaveTextContent("2 of 5 steps");
    const why = within(form).getByLabelText("Why it is needed");
    await user.type(why, " It hurts. Twice");
    expect(form).toHaveTextContent("4 of 3 sentences");
    await user.clear(why);
    await user.type(why, "Leaked keys work forever.");
    await user.click(within(form).getByRole("button", { name: "Save" }));
    await waitFor(() => expect(screen.queryByRole("form", { name: "Edit the face" })).toBeNull());
    expect(writes(view)).toEqual([
      {
        route: `PATCH ${CARD_PATH}`,
        body: {
          version: 3,
          summary: FACE.summary,
          why: "Leaked keys work forever.",
          if_skipped: FACE.if_skipped,
          pros: FACE.pros,
          cons: FACE.cons,
          steps: ["Make a new key every night.", "Refuse an older key."],
        },
      },
    ]);
    const forYou = panel("For you");
    const shown = within(forYou).getByRole("list", { name: "Steps" });
    expect(within(shown).getAllByRole("listitem")).toHaveLength(2);
    expect(forYou).toHaveTextContent("2 of 5");
  });

  it("shows each message of a 422 under its field, as the server words it", async () => {
    const { user } = await renderTicket(faceCard());
    const steps = "Ticket SES-1-PH01-001, steps[0]: looks like a code symbol (rotateKeys).";
    const summary = "Ticket SES-1-PH01-001, summary: 22 words, at most 20.";
    server.use(
      http.patch(apiPath(CARD_PATH), () =>
        failure(422, "face_invalid", "The face for people does not keep its template", {
          errors: [summary, steps],
          error_count: 2,
          faces: [
            { ticket_id: "SES-1-PH01-001", field: "summary", rule: "words" },
            { ticket_id: "SES-1-PH01-001", field: "steps[0]", rule: "code_symbol" },
          ],
        }),
      ),
    );
    await user.click(screen.getByRole("button", { name: "Edit what will be done" }));
    const form = screen.getByRole("form", { name: "Edit the face" });
    await user.click(within(form).getByRole("button", { name: "Save" }));
    const alerts = await within(form).findAllByRole("alert");
    expect(alerts.map((alert) => alert.textContent)).toEqual([summary, steps]);
    const summaryField = within(form).getByLabelText("Summary");
    expect(summaryField).toHaveAttribute("aria-invalid", "true");
    expect(summaryField.parentElement).toHaveTextContent(summary);
    expect(within(form).getByLabelText("What will be done").parentElement).toHaveTextContent(steps);
    // The draft stays open to fix; Cancel puts the face back.
    await user.click(within(form).getByRole("button", { name: "Cancel" }));
    expect(within(panel("For you")).getByRole("list", { name: "Steps" })).toBeInTheDocument();
  });
});
