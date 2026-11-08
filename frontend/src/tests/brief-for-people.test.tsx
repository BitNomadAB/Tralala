import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http } from "msw";
import { describe, expect, it } from "vitest";
import { rewriteBlockedReason } from "@/features/loops/loopUi";
import type {
  DocumentKind,
  GenerationRun,
  HumanBrief,
  LoopDocument,
  RoadmapBrief,
} from "@/lib/types";
import { apiPath, ok } from "./msw/envelope";
import {
  DOCUMENTS,
  emptyDocument,
  generationRun,
  LOOP_ID,
  LOOP_PATH,
  planningDialogHandlers,
} from "./msw/loops";
import { server } from "./msw/server";
import { renderDocuments } from "./renderDocuments";

const BRIEF: HumanBrief = {
  schema_version: 1,
  obstacles: [
    { level: "legal", text: "We keep personal data longer than allowed.", finding_ids: ["F-02"] },
  ],
  pros: [{ text: "The sign-in can already send mail.", finding_ids: ["F-01"] }],
  cons: [{ text: "Some e-mails never arrive.", finding_ids: ["F-02", "F-09"] }],
  decisions: [{ question: "Who writes the e-mail?", finding_ids: ["F-03"] }],
  verdict: "yes_with_conditions",
  verdict_reason: "It works once retention is settled.",
  summary: "People confirm their address by e-mail.",
  recommendation: "Go ahead after the retention question is answered.",
};
const ANALYSIS_AI = {
  findings: [
    { id: "F-01", title: "Reuse the sign-in", category: "reuse" },
    { id: "F-02", title: "Retention of addresses", category: "legal" },
    { id: "F-03", title: "Mail wording", category: "question" },
  ],
};
const P1 = "11111111-1111-4111-8111-111111111111";
const P2 = "11111111-1111-4111-8111-111111111112";
const T2 = "22222222-2222-4222-8222-222222222222";
const ROADMAP_BRIEF: RoadmapBrief = {
  schema_version: 1,
  order: [
    { phase_id: P2, what_happens: "The policy is signed.", done_when: "It is signed." },
    { phase_id: P1, what_happens: "The e-mail goes out.", done_when: "It arrives." },
  ],
  your_part: [{ text: "Sign the retention policy.", phase_ids: [P2], ticket_ids: [T2] }],
  could_block: [{ text: "The mail provider may be late.", phase_ids: [P1] }],
  summary: "Two Phases: the e-mail, then the policy.",
};
const ROADMAP_AI = {
  phases: [
    { id: P1, number: 1, name: "Mail", tickets: [] },
    { id: P2, number: 2, name: "Policy", tickets: [{ id: T2, key: "SES-1-2", title: "Sign" }] },
  ],
};

function document(
  kind: DocumentKind,
  content: string,
  extra: Partial<LoopDocument> = {},
): LoopDocument {
  return {
    ...emptyDocument(kind),
    state: "ready_for_review",
    current_revision_id: `${kind}-1`,
    current_revision_number: 1,
    current_content: content,
    ...extra,
  };
}

const briefDocuments = (analysis: Partial<LoopDocument> = {}) => ({
  ...DOCUMENTS,
  info: document("info", "Users must confirm."),
  analysis_ai: document("analysis_ai", "```json\n{}\n```", { current_payload: ANALYSIS_AI }),
  analysis: document("analysis", "# Analysis", {
    current_payload: { ...BRIEF },
    current_provenance: { written: true, author: "Coder", through: "mcp" },
    ...analysis,
  }),
  roadmap_ai: document("roadmap_ai", "```json\n{}\n```", { current_payload: ROADMAP_AI }),
  roadmap: document("roadmap", "# RoadMap", {
    current_payload: { ...ROADMAP_BRIEF },
    current_provenance: { written: true, agent_name: "Planner" },
  }),
});

function open(
  documents: Record<DocumentKind, LoopDocument>,
  initialTab: "analysis" | "roadmap" = "analysis",
  runs: GenerationRun[] = [],
) {
  const { handlers } = planningDialogHandlers(runs);
  server.use(
    http.get(apiPath(`${LOOP_PATH}/documents`), () =>
      ok({ loop_id: LOOP_ID, loop_version: 1, documents, approvals: {} }),
    ),
    ...handlers,
  );
  renderDocuments(initialTab);
}

describe("the brief for people", () => {
  it("shows the verdict and the sections, never the ids", async () => {
    open(briefDocuments());
    expect(await screen.findByText("Yes, with conditions")).toBeInTheDocument();
    expect(screen.getByText("It works once retention is settled.")).toBeInTheDocument();
    for (const heading of ["What stands in the way", "For", "Against", "What you need to decide"]) {
      expect(screen.getByRole("heading", { name: heading })).toBeInTheDocument();
    }
    expect(screen.getByText("Who writes the e-mail?")).toBeInTheDocument();
    expect(screen.getByText("Written by Coder")).toBeInTheDocument();
    expect(screen.queryByText(/F-0/)).not.toBeInTheDocument();
  });

  it("says where each item comes from, by the findings' titles", async () => {
    open(briefDocuments());
    const against = (await screen.findByText("Some e-mails never arrive.")).closest("li");
    if (!against) throw new Error("the item is a list entry");
    const user = userEvent.setup();
    await user.click(within(against).getByText("Where does this come from?"));
    expect(within(against).getByText("Retention of addresses")).toBeVisible();
    expect(within(against).getByText("No longer in the technical version")).toBeVisible();
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
