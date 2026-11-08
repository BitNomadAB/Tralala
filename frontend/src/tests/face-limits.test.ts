import { describe, expect, it } from "vitest";
import {
  draftOf,
  faceCounts,
  faceErrors,
  faceOf,
  listItems,
  sentenceCount,
  wordCount,
} from "@/features/cards/faceLimits";
import { planEntryText, prosConsHint, stepsFoot } from "@/features/cards/ticketText";
import { ApiError } from "@/lib/api";
import { attachmentKindsText } from "@/lib/api/attachmentRules";
import { READINESS } from "./msw/ticketView";

describe("the face's counting rules, as the server's", () => {
  it("counts words as whitespace tokens", () => {
    expect(wordCount("")).toBe(0);
    expect(wordCount("  Old keys\tstop\nworking.  ")).toBe(4);
  });

  it.each([
    ["", 0],
    ["One sentence.", 1],
    ["One. Two! Three?", 3],
    ["No stop at the end", 1],
    ["Ends here. And then some", 2],
    ["e.g. this", 2],
    ["Version 3.5 ships", 1],
    ["Wait... what?!", 2],
  ])("counts %j as %i sentences", (text, count) => {
    expect(sentenceCount(text)).toBe(count);
  });

  it("reads a list one item per line, without the empty ones", () => {
    expect(listItems("  one \n\n two\n   ")).toEqual(["one", "two"]);
  });

  it("counts every field against its limit, and marks what is over or missing", () => {
    const counts = faceCounts({
      summary: "",
      why: "One. Two. Three. Four.",
      if_skipped: "It stays.",
      pros: "a\nb\nc\nd",
      cons: "",
      steps: "1\n2\n3\n4",
    });
    expect(counts.summary).toEqual({ text: "0 of 20 words", over: true });
    expect(counts.why).toEqual({ text: "4 of 3 sentences", over: true });
    expect(counts.if_skipped).toEqual({ text: "1 of 3 sentences", over: false });
    expect(counts.pros).toEqual({ text: "4 of 3 points", over: true });
    expect(counts.cons).toEqual({ text: "0 of 3 points", over: false });
    expect(counts.steps).toEqual({ text: "4 of 5 steps", over: false });
  });

  it("turns a face into a draft and back", () => {
    const face = {
      summary: "Keys rotate.",
      why: "Leaks.",
      if_skipped: "Risk.",
      pros: ["Safe"],
      cons: [],
      steps: ["One", "Two"],
    };
    expect(faceOf(draftOf(face, "ignored"))).toEqual(face);
    expect(draftOf(null, "A summary")).toEqual({
      summary: "A summary",
      why: "",
      if_skipped: "",
      pros: "",
      cons: "",
      steps: "",
    });
  });
});

describe("a face_invalid refusal", () => {
  const refusal = (details: unknown) =>
    new ApiError("The face for people does not keep its template", {
      code: "face_invalid",
      status: 422,
      details,
    });

  it("puts each message under the field its entry names", () => {
    const errors = faceErrors(
      refusal({
        errors: ["Ticket K, steps[2]: empty. Remove it or write it.", "Ticket K, why: missing."],
        faces: [
          { ticket_id: "K", field: "steps[2]", rule: "empty_item" },
          { ticket_id: "K", field: "why", rule: "missing" },
        ],
      }),
    );
    expect(errors).toEqual({
      fields: {
        steps: ["Ticket K, steps[2]: empty. Remove it or write it."],
        why: ["Ticket K, why: missing."],
      },
      other: [],
    });
  });

  it("reads the field from the message when no entry names it, and keeps the rest apart", () => {
    const errors = faceErrors(
      refusal({ errors: ['Ticket "Rotate", if_skipped: 4 sentences, at most 3.', "Odd."] }),
    );
    expect(errors).toEqual({
      fields: { if_skipped: ['Ticket "Rotate", if_skipped: 4 sentences, at most 3.'] },
      other: ["Odd."],
    });
    expect(faceErrors(refusal(null))).toEqual({
      fields: {},
      other: ["The face for people does not keep its template"],
    });
  });

  it("is null for any other error", () => {
    expect(faceErrors(new ApiError("No", { code: "version_conflict", status: 409 }))).toBeNull();
    expect(faceErrors(new TypeError("Failed to fetch"))).toBeNull();
  });
});

describe("the face's lines", () => {
  it("says how many steps of five, and why there are no more at five", () => {
    expect(stepsFoot(4)).toBe("4 of 5");
    expect(stepsFoot(5)).toBe(
      "Five of five. A Ticket that needs more steps is split into another Ticket when the RoadMap is written.",
    );
    expect(prosConsHint({ pros: ["a", "b", "c"], cons: ["d", "e"] })).toBe("3 for, 2 against");
  });

  it("names the accepted kinds of file and the size limit in words", () => {
    expect(attachmentKindsText()).toBe(
      "Documents, presentations, spreadsheets, PDF, text, Markdown, JSON and images, up to 8 MB each.",
    );
  });

  it("writes the plan entry without computed fields, with its prerequisites by key", () => {
    const item = READINESS.items[1];
    if (!item) throw new Error("the readiness fixture has two items");
    const text = planEntryText(
      { ...item, objective: "Rotate keys", human_instructions: "", completed_at: "x" },
      READINESS,
    );
    expect(JSON.parse(text)).toEqual({
      id: "SES-1-PH01-001",
      title: "SES-1-PH01-001",
      phase: 1,
      objective: "Rotate keys",
      required_actor: "any",
      execution_mode: "normal",
      depends_on: ["SES-1-PH01-000"],
      workplace: "unknown",
    });
    expect(text).toContain('\n  "phase": 1,');
  });
});
