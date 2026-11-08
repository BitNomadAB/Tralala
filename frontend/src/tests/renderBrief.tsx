import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render } from "@testing-library/react";
import { http } from "msw";
import { ToastProvider } from "@/components/ui/toast";
import { LoopDocumentDialog } from "@/features/loops/LoopDocumentDialog";
import type {
  DocumentKind,
  GenerationRun,
  HumanBrief,
  LoopDocument,
  RoadmapBrief,
} from "@/lib/types";
import { apiPath, ok } from "./msw/envelope";
import {
  BOARD_ID,
  DOCUMENTS,
  emptyDocument,
  LOOP,
  LOOP_ID,
  LOOP_PATH,
  planningDialogHandlers,
} from "./msw/loops";
import { server } from "./msw/server";

/** An analysis brief that keeps the sign: a verdict line, a reason, a question, a size. */
export const BRIEF: HumanBrief = {
  schema_version: 1,
  obstacles: [
    { level: "legal", text: "We keep personal data longer than allowed.", finding_ids: ["F-02"] },
  ],
  pros: [{ text: "The sign-in can already send mail.", finding_ids: ["F-01"] }],
  cons: [{ text: "Some e-mails never arrive.", finding_ids: ["F-02", "F-09"] }],
  decisions: [{ question: "Who writes the e-mail?", finding_ids: ["F-03", "F-09"] }],
  size: { kind: "medium", text: "One new e-mail and a rule for how long we keep addresses." },
  verdict: "yes_with_conditions",
  verdict_line: "Yes, once we settle how long addresses are kept.",
  verdict_reason: "It works once retention is settled.",
  summary: "People confirm their address by e-mail.",
  recommendation: "Go ahead after the retention question is answered.",
};
export const TECHNICAL_DETAIL = "The mailer has no template for the confirmation.";
export const ANALYSIS_AI = {
  findings: [
    { id: "F-01", title: "Reuse the sign-in", category: "reuse" },
    { id: "F-02", title: "Retention of addresses", category: "legal" },
    {
      id: "F-03",
      title: "Mail wording",
      category: "question",
      technical_detail: TECHNICAL_DETAIL,
      plain_language: "Someone has to write the e-mail.",
    },
  ],
};
const P1 = "11111111-1111-4111-8111-111111111111";
const P2 = "11111111-1111-4111-8111-111111111112";
const T2 = "22222222-2222-4222-8222-222222222222";
export const ROADMAP_BRIEF: RoadmapBrief = {
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

/** The Loop's documents with both briefs; `analysis` changes the analysis for people. */
export const briefDocuments = (analysis: Partial<LoopDocument> = {}) => ({
  ...DOCUMENTS,
  info: document("info", "Users must confirm."),
  analysis_ai: document("analysis_ai", "```json\n{}\n```", {
    current_payload: ANALYSIS_AI,
    current_revision_id: "ai-7",
    current_revision_number: 2,
  }),
  analysis: document("analysis", "# Analysis", {
    current_payload: { ...BRIEF },
    current_provenance: { written: true, author: "Coder", through: "mcp" },
    current_revision_id: "an-9",
    current_revision_number: 3,
    ...analysis,
  }),
  roadmap_ai: document("roadmap_ai", "```json\n{}\n```", { current_payload: ROADMAP_AI }),
  roadmap: document("roadmap", "# RoadMap", {
    current_payload: { ...ROADMAP_BRIEF },
    current_provenance: { written: true, agent_name: "Planner" },
  }),
});

/** The planning dialog over `documents`, as a person who may review, on `initialTab`. */
export function openBrief(
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
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  render(
    <QueryClientProvider client={queryClient}>
      <ToastProvider>
        <LoopDocumentDialog
          boardId={BOARD_ID}
          loop={LOOP}
          initialTab={initialTab}
          isHuman
          readOnly={false}
          onClose={() => undefined}
          onChanged={() => undefined}
        />
      </ToastProvider>
    </QueryClientProvider>,
  );
}
