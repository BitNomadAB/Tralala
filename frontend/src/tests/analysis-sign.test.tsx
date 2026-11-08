import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http } from "msw";
import { describe, expect, it } from "vitest";
import { approvalLine } from "@/features/loops/briefApproval";
import { apiPath, ok } from "./msw/envelope";
import { LOOP_ID, LOOP_PATH } from "./msw/loops";
import { server } from "./msw/server";
import { BRIEF, briefDocuments, openBrief, TECHNICAL_DETAIL } from "./renderBrief";

const SECTIONS = ["In short", "Why", "What you decide", "How big", "For and against"];

function headings(): string[] {
  return screen
    .getAllByRole("heading")
    .map((heading) => heading.textContent ?? "")
    .filter((text) => SECTIONS.includes(text));
}

describe("the analysis brief as a sign", () => {
  it("reads in short, why, what you decide, how big, and for and against, in that order", async () => {
    openBrief(briefDocuments());
    expect(await screen.findByRole("heading", { name: "In short" })).toBeInTheDocument();
    expect(headings()).toEqual(SECTIONS);
    expect(screen.getByText("Yes, with conditions")).toBeInTheDocument();
    expect(screen.getByText("Yes, once we settle how long addresses are kept.")).toHaveClass(
      "text-[19px]",
    );
    expect(screen.getByText("We keep personal data longer than allowed.")).toBeInTheDocument();
    expect(screen.getByText("Who writes the e-mail?")).toHaveClass("text-[15px]");
    expect(screen.getByText("Medium.")).toBeInTheDocument();
    expect(
      within(screen.getByRole("list", { name: "For" })).getByRole("listitem"),
    ).toHaveTextContent("The sign-in can already send mail.");
    expect(screen.getByRole("list", { name: "Against" })).toHaveTextContent(
      "Some e-mails never arrive.",
    );
    // For you holds no finding's text and no id: those are in Raw text.
    const forYou = within(screen.getByRole("tabpanel", { name: "For you" }));
    expect(forYou.queryByText(TECHNICAL_DETAIL)).not.toBeInTheDocument();
    expect(forYou.queryByText("Someone has to write the e-mail.")).not.toBeInTheDocument();
    expect(forYou.queryByText(/F-0/)).not.toBeInTheDocument();
  });

  it("shows the findings a question rests on as chips, their ids on hover only", async () => {
    openBrief(briefDocuments());
    const rests = await screen.findByRole("list", { name: "Rests on" });
    const chips = within(rests).getAllByRole("listitem");
    expect(chips.map((chip) => chip.textContent)).toEqual([
      "Mail wording",
      "No longer in the technical version",
    ]);
    expect(within(rests).getByText("Mail wording")).toHaveAttribute("title", "F-03");
  });

  it("shows the findings and the technical analysis as written under Raw text", async () => {
    openBrief(briefDocuments());
    const user = userEvent.setup();
    await user.click(await screen.findByRole("tab", { name: "Raw text" }));
    expect(screen.getByRole("tab", { name: "Raw text" })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByText(TECHNICAL_DETAIL)).toBeVisible();
    expect(screen.getByText("F-03 · question")).toBeVisible();
    expect(screen.getByText(/"findings": \[/)).toBeVisible();
    expect(screen.getByRole("heading", { name: "In short", hidden: true })).not.toBeVisible();
    await user.click(screen.getByRole("tab", { name: "For you" }));
    expect(screen.getByRole("heading", { name: "In short" })).toBeVisible();
  });

  it("approves the revisions it names, once, from the end of the brief", async () => {
    document.cookie = "tralala_csrf=csrf-brief";
    const sent: { body: unknown; csrf: string | null }[] = [];
    server.use(
      http.post(apiPath(`${LOOP_PATH}/reviews/analysis`), async ({ request }) => {
        sent.push({ body: await request.json(), csrf: request.headers.get("X-CSRF-Token") });
        return ok({
          id: "appr-1",
          loop_id: LOOP_ID,
          scope: "analysis",
          decision: "approved",
          reviewer_actor_id: "u-1",
          reviewer_name: "Ada",
          feedback: "",
          revisions: {},
          created_at: "2026-11-08T10:00:00Z",
        });
      }),
    );
    openBrief(briefDocuments());
    await screen.findByRole("heading", { name: "In short" });
    const approve = screen.getByRole("button", { name: "Approve analysis" });
    expect(screen.getAllByRole("button", { name: "Approve analysis" })).toHaveLength(1);
    expect(
      screen.getByText("Approves revision 3 of this analysis, written from technical revision 2."),
    ).toBeInTheDocument();
    await userEvent.setup().click(approve);
    await screen.findByText("Decision recorded");
    expect(sent).toHaveLength(1);
    expect(sent[0]?.csrf).toBe("csrf-brief");
    expect(sent[0]?.body).toMatchObject({
      decision: "approved",
      revisions: { info: "info-1", analysis_ai: "ai-7", analysis: "an-9" },
    });
  });

  it("names the approved revision once it is approved", () => {
    const approval = {
      revisionNumber: 3,
      technicalRevisionNumber: null,
      approved: false,
      disabled: false,
      onApprove: () => undefined,
    };
    expect(approvalLine(approval)).toBe("Approves revision 3 of this analysis.");
    expect(approvalLine({ ...approval, approved: true })).toBe(
      "Approved: revision 3 of this analysis.",
    );
  });

  it("reads a brief written before the sign without its line and its size", async () => {
    const { size: _size, verdict_line: _line, ...old } = BRIEF;
    openBrief(briefDocuments({ current_payload: { ...old, decisions: [], cons: [] } }));
    expect(await screen.findByText("Yes, with conditions")).toBeInTheDocument();
    expect(headings()).toEqual(["In short", "Why", "What you decide", "For and against"]);
    expect(screen.queryByText(BRIEF.verdict_line ?? "")).not.toBeInTheDocument();
    expect(screen.getByText("Nothing for you to decide.")).toBeInTheDocument();
    expect(screen.getByText("Nothing against.")).toBeInTheDocument();
  });
});
