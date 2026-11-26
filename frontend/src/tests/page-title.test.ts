import { describe, expect, it } from "vitest";
import { pageTitle } from "@/app/usePageTitle";

describe("a page's document title", () => {
  it("names each fixed page, then the product", () => {
    expect(pageTitle({ page: "login" })).toBe("Sign in · Tralala");
    expect(pageTitle({ page: "enrol" })).toBe("Choose your password · Tralala");
    expect(pageTitle({ page: "boards" })).toBe("Boards · Tralala");
    expect(pageTitle({ page: "discussions" })).toBe("Discussions · Tralala");
    expect(pageTitle({ page: "settings" })).toBe("Settings · Tralala");
    expect(pageTitle({ page: "repositories" })).toBe("Repositories · Settings · Tralala");
    expect(pageTitle({ page: "error" })).toBe("Page could not be shown · Tralala");
  });

  it("names the board, the Loop and the Ticket a page shows, most specific first", () => {
    expect(pageTitle({ page: "board", board: "Payments" })).toBe("Payments · Tralala");
    expect(pageTitle({ page: "history", board: "Payments" })).toBe(
      "Board history · Payments · Tralala",
    );
    expect(pageTitle({ page: "loop", loop: "Session limits", board: "Payments" })).toBe(
      "Session limits · Payments · Tralala",
    );
    expect(
      pageTitle({
        page: "ticket",
        ticketKey: "SES-1-004",
        ticket: "Rotate the signing key",
        loop: "Session limits",
      }),
    ).toBe("SES-1-004 Rotate the signing key · Session limits · Tralala");
    expect(pageTitle({ page: "discussion", question: "Is a day long enough?" })).toBe(
      "Is a day long enough? · Discussion · Tralala",
    );
    expect(pageTitle({ page: "board-discussion", title: "Export", board: "Payments" })).toBe(
      "Export · Payments · Tralala",
    );
  });

  it("names the kind of page while its name is loading", () => {
    expect(pageTitle({ page: "board", board: undefined })).toBe("Board · Tralala");
    expect(pageTitle({ page: "history", board: undefined })).toBe("Board history · Tralala");
    expect(pageTitle({ page: "loop", loop: undefined, board: undefined })).toBe("Loop · Tralala");
    expect(pageTitle({ page: "ticket", ticketKey: null, ticket: undefined, loop: undefined })).toBe(
      "Ticket · Tralala",
    );
    expect(pageTitle({ page: "ticket", ticketKey: null, ticket: "Unplanned", loop: "L" })).toBe(
      "Unplanned · L · Tralala",
    );
    expect(pageTitle({ page: "discussion", question: undefined })).toBe("Discussion · Tralala");
    expect(pageTitle({ page: "board-discussion", title: undefined, board: undefined })).toBe(
      "Discussion · Tralala",
    );
  });

  it("says whether a settings editor makes something new or edits a named thing", () => {
    expect(pageTitle({ page: "board-template", isNew: true, template: undefined })).toBe(
      "New board template · Settings · Tralala",
    );
    expect(pageTitle({ page: "board-template", isNew: false, template: "Kanban" })).toBe(
      "Kanban · Board template · Tralala",
    );
    expect(pageTitle({ page: "board-template", isNew: false, template: undefined })).toBe(
      "Board template · Tralala",
    );
    expect(pageTitle({ page: "role-template", isNew: false, role: "Architect" })).toBe(
      "Architect · Role template · Tralala",
    );
    expect(pageTitle({ page: "role-template", isNew: true, role: undefined })).toBe(
      "New role template · Settings · Tralala",
    );
    expect(pageTitle({ page: "agent", isNew: false, agent: "Alpha" })).toBe(
      "Alpha · AI agent · Tralala",
    );
    expect(pageTitle({ page: "agent", isNew: true, agent: undefined })).toBe(
      "New AI agent · Settings · Tralala",
    );
  });

  it("keeps a name on one line and cuts a long one", () => {
    expect(pageTitle({ page: "board", board: "  Payments\n  team  " })).toBe(
      "Payments team · Tralala",
    );
    const question = `Should ${"the session ".repeat(12)}end?`;
    const [first] = pageTitle({ page: "discussion", question }).split(" · ");
    expect(first?.length).toBeLessThanOrEqual(80);
    expect(first).toBe(`Should ${"the session ".repeat(6).trimEnd()}…`);
    expect(pageTitle({ page: "board", board: "   " })).toBe("Board · Tralala");
  });
});
