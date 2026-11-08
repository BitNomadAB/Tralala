import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { rewriteBlockedReason } from "@/features/loops/loopUi";
import { generationRun } from "./msw/loops";
import { briefDocuments, openBrief as open } from "./renderBrief";

describe("the brief for people", () => {
  it("names who wrote the analysis brief and never shows an id", async () => {
    open(briefDocuments());
    expect(await screen.findByText("Yes, with conditions")).toBeInTheDocument();
    expect(screen.getByText("Written by Coder")).toBeInTheDocument();
    const forYou = within(screen.getByRole("tabpanel", { name: "For you" }));
    expect(forYou.queryByText(/F-0/)).not.toBeInTheDocument();
  });

  it("switches between the brief for people and the version for AI", async () => {
    open(briefDocuments());
    const user = userEvent.setup();
    expect(await screen.findByRole("button", { name: "For people" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    await user.click(screen.getByRole("button", { name: "For AI" }));
    expect(screen.getByText("Analysis (AI)")).toBeInTheDocument();
    expect(screen.queryByText("Yes, with conditions")).not.toBeInTheDocument();
    // Without the brief on screen the review carries the approval again.
    expect(screen.getByRole("button", { name: "Approve analysis" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "For people" }));
    expect(screen.getByText("Yes, with conditions")).toBeInTheDocument();
  });

  it("shows the RoadMap brief in the plan's order, with the person's part", async () => {
    open(briefDocuments(), "roadmap");
    // The first of each title is the order of work; the disclosures name the Phases again.
    const [first] = await screen.findAllByText("Phase 1 — Mail");
    const [second] = screen.getAllByText("Phase 2 — Policy");
    if (!first || !second) throw new Error("both Phases are shown");
    expect(first.compareDocumentPosition(second) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(screen.getByRole("heading", { name: "Your part" })).toBeInTheDocument();
    const part = screen.getByText("Sign the retention policy.").closest("li");
    if (!part) throw new Error("the item is a list entry");
    expect(within(part).getByText("SES-1-2 Sign", { exact: false })).toBeInTheDocument();
    expect(screen.getByText("Written by Planner")).toBeInTheDocument();
  });

  it("says where a RoadMap item comes from, by the Phases' titles", async () => {
    open(briefDocuments(), "roadmap");
    const risk = (await screen.findByText("The mail provider may be late.")).closest("li");
    if (!risk) throw new Error("the item is a list entry");
    const user = userEvent.setup();
    await user.click(within(risk).getByText("Where does this come from?"));
    expect(within(risk).getByText("Phase 1 — Mail")).toBeVisible();
  });

  it("labels a view written before briefs as the earlier format", async () => {
    open(
      briefDocuments({
        current_payload: null,
        current_content: "People confirm by e-mail [F-02].",
        current_provenance: { written: true, agent_name: "Alpha" },
      }),
    );
    expect(await screen.findByText("Earlier format")).toBeInTheDocument();
    expect(screen.getByText("People confirm by e-mail [F-02].")).toBeInTheDocument();
  });

  it("says why it cannot be rewritten for people", async () => {
    open(briefDocuments({ state: "approved" }));
    expect(
      await screen.findByText("Approved: request changes or reset to rewrite"),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Rewrite for people/ })).toBeDisabled();
  });

  it("says that a brief is being written while its run is on", async () => {
    open(briefDocuments(), "roadmap", [
      generationRun("running", "writing_for_people", { id: "run-7", purpose: "roadmap_human" }),
    ]);
    expect(await screen.findByText("Writing for people...")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Rewrite for people/ })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Approve RoadMap" })).toBeDisabled();
  });

  it("names the reasons in the order a person meets them", () => {
    const base = { approved: false, writing: false, generating: false, hasTechnical: true };
    expect(rewriteBlockedReason(base)).toBeNull();
    expect(rewriteBlockedReason({ ...base, approved: true, writing: true })).toBe(
      "Writing for people...",
    );
    expect(rewriteBlockedReason({ ...base, hasTechnical: false })).toBe(
      "Generate the technical version first",
    );
  });
});
