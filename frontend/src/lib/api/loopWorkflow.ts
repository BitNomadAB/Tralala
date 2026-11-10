import type {
  Card,
  DocumentKind,
  GenerationPurpose,
  GenerationRun,
  LoopAgentPreferences,
  LoopApproval,
  LoopDocuments,
  LoopPlanView,
  LoopReadiness,
  QaCycle,
} from "../types";
import { json, request } from "./client";

/** A Loop's planning documents and reviews, its plan, generation runs, implementation and QA. */
export const loopWorkflowApi = {
  async getLoopDocuments(boardId: string, loopId: string): Promise<LoopDocuments> {
    return json(await request<LoopDocuments>(`/boards/${boardId}/loops/${loopId}/documents`));
  },

  async saveInfo(
    boardId: string,
    loopId: string,
    payload: { content: string; note?: string; expected_revision_id?: string | null },
  ): Promise<LoopDocuments> {
    return json(
      await request<LoopDocuments>(`/boards/${boardId}/loops/${loopId}/documents/info`, {
        method: "PUT",
        body: payload,
      }),
    );
  },

  async listDocumentRevisions(
    boardId: string,
    loopId: string,
    kind: DocumentKind,
  ): Promise<Record<string, unknown>[]> {
    return json(
      await request<Record<string, unknown>[]>(
        `/boards/${boardId}/loops/${loopId}/documents/${kind}/revisions`,
      ),
    );
  },

  async submitCandidate(
    boardId: string,
    loopId: string,
    payload: Record<string, unknown>,
  ): Promise<LoopDocuments> {
    return json(
      await request<LoopDocuments>(`/boards/${boardId}/loops/${loopId}/candidates`, {
        method: "POST",
        body: payload,
      }),
    );
  },

  async reviewAnalysis(
    boardId: string,
    loopId: string,
    payload: {
      decision: "approved" | "changes_requested";
      version: number;
      revisions: Record<string, string>;
      feedback?: string;
    },
  ): Promise<LoopApproval> {
    return json(
      await request<LoopApproval>(`/boards/${boardId}/loops/${loopId}/reviews/analysis`, {
        method: "POST",
        body: payload,
      }),
    );
  },

  async reviewRoadmap(
    boardId: string,
    loopId: string,
    payload: {
      decision: "approved" | "changes_requested";
      version: number;
      revisions: Record<string, string>;
      feedback?: string;
    },
  ): Promise<LoopApproval> {
    return json(
      await request<LoopApproval>(`/boards/${boardId}/loops/${loopId}/reviews/roadmap`, {
        method: "POST",
        body: payload,
      }),
    );
  },

  async resetScope(
    boardId: string,
    loopId: string,
    scope: "analysis" | "roadmap",
    payload: { version: number },
  ): Promise<{ scope: string; approval_id: string | null; cleared: string[]; version: number }> {
    return json(
      await request<{
        scope: string;
        approval_id: string | null;
        cleared: string[];
        version: number;
      }>(`/boards/${boardId}/loops/${loopId}/reviews/${scope}/reset`, {
        method: "POST",
        body: payload,
      }),
    );
  },

  async getLoopPlan(boardId: string, loopId: string): Promise<LoopPlanView> {
    return json(await request<LoopPlanView>(`/boards/${boardId}/loops/${loopId}/plan`));
  },

  async getReadiness(boardId: string, loopId: string): Promise<LoopReadiness> {
    return json(await request<LoopReadiness>(`/boards/${boardId}/loops/${loopId}/readiness`));
  },

  /** A run for `purpose`; `instructions` is what a person adds to it (a RoadMap written again). */
  async startGeneration(
    boardId: string,
    loopId: string,
    purpose: GenerationPurpose,
    agentId?: string,
    instructions?: string,
  ): Promise<GenerationRun> {
    return json(
      await request<GenerationRun>(`/boards/${boardId}/loops/${loopId}/generation-runs`, {
        method: "POST",
        body: {
          purpose,
          ...(agentId ? { agent_id: agentId } : {}),
          ...(instructions ? { instructions } : {}),
        },
      }),
    );
  },

  async listGenerationRuns(boardId: string, loopId: string): Promise<GenerationRun[]> {
    return json(
      await request<GenerationRun[]>(`/boards/${boardId}/loops/${loopId}/generation-runs`),
    );
  },

  async getLoopAgents(boardId: string, loopId: string): Promise<LoopAgentPreferences> {
    return json(await request<LoopAgentPreferences>(`/boards/${boardId}/loops/${loopId}/agents`));
  },

  async setLoopAgents(
    boardId: string,
    loopId: string,
    payload: {
      analysis_agent_id?: string | null;
      roadmap_agent_id?: string | null;
      qa_agent_id?: string | null;
    },
  ): Promise<LoopAgentPreferences> {
    return json(
      await request<LoopAgentPreferences>(`/boards/${boardId}/loops/${loopId}/agents`, {
        method: "PUT",
        body: payload,
      }),
    );
  },

  async getGenerationRun(boardId: string, loopId: string, runId: string): Promise<GenerationRun> {
    return json(
      await request<GenerationRun>(`/boards/${boardId}/loops/${loopId}/generation-runs/${runId}`),
    );
  },

  /** Stops a queued or running run; a run that already finished is returned unchanged. */
  async cancelGenerationRun(
    boardId: string,
    loopId: string,
    runId: string,
  ): Promise<GenerationRun> {
    return json(
      await request<GenerationRun>(
        `/boards/${boardId}/loops/${loopId}/generation-runs/${runId}/cancel`,
        { method: "POST" },
      ),
    );
  },

  async acceptImplementation(
    boardId: string,
    loopId: string,
    payload: {
      version: number;
      accepted: boolean;
      qa_status: "not_tested" | "tested_with_issues" | "passed";
      attestation?: Record<string, string>;
      note?: string;
    },
  ): Promise<Record<string, unknown>> {
    return json(
      await request<Record<string, unknown>>(`/boards/${boardId}/loops/${loopId}/completion`, {
        method: "POST",
        body: payload,
      }),
    );
  },

  async getQaCycle(boardId: string, loopId: string): Promise<QaCycle> {
    return json(await request<QaCycle>(`/boards/${boardId}/loops/${loopId}/qa`));
  },

  async submitQaInstructions(
    boardId: string,
    loopId: string,
    payload: Record<string, unknown>,
  ): Promise<QaCycle> {
    return json(
      await request<QaCycle>(`/boards/${boardId}/loops/${loopId}/qa/instructions`, {
        method: "PUT",
        body: payload,
      }),
    );
  },

  async submitQaResults(
    boardId: string,
    loopId: string,
    payload: { results: Record<string, string>[] },
  ): Promise<QaCycle> {
    return json(
      await request<QaCycle>(`/boards/${boardId}/loops/${loopId}/qa/results`, {
        method: "POST",
        body: payload,
      }),
    );
  },

  async decideQa(
    boardId: string,
    loopId: string,
    payload: {
      version: number;
      cycle_id: string;
      decision: "accepted" | "rejected";
      not_applicable_approvals?: string[];
      note?: string;
    },
  ): Promise<Record<string, unknown>> {
    return json(
      await request<Record<string, unknown>>(`/boards/${boardId}/loops/${loopId}/qa/decision`, {
        method: "POST",
        body: payload,
      }),
    );
  },

  async confirmHumanTicket(
    boardId: string,
    loopId: string,
    cardId: string,
    payload: { version: number; note?: string },
  ): Promise<Card> {
    return json(
      await request<Card>(`/boards/${boardId}/loops/${loopId}/cards/${cardId}/confirm`, {
        method: "POST",
        body: payload,
      }),
    );
  },
};
