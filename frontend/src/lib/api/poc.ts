import type {
  PocAnswer,
  PocDecision,
  PocDecisionList,
  PocDecisionPayload,
  PocStatus,
  StopList,
} from "../types";
import { json, request } from "./client";

const loopPath = (boardId: string, loopId: string): string =>
  `/boards/${encodeURIComponent(boardId)}/loops/${encodeURIComponent(loopId)}`;

/**
 * A Loop's POC decisions, what is missing from a person, and its stop list. Answering a decision
 * and writing the stop list are a signed-in person's acts (`403 human_action_required` for a key);
 * feedback is final (`409 poc_decision_answered`), and a Loop whose stage takes no new Ticket
 * refuses feedback with that Ticket's error. A stop list breaking its rules is `422 stops_invalid`.
 */
export const pocApi = {
  async listPocDecisions(
    boardId: string,
    loopId: string,
    params: { card_id?: string | undefined; status?: PocStatus | undefined } = {},
  ): Promise<PocDecisionList> {
    const query = new URLSearchParams();
    if (params.card_id) query.set("card_id", params.card_id);
    if (params.status) query.set("status", params.status);
    const text = query.toString();
    const suffix = text ? `?${text}` : "";
    return json(
      await request<PocDecisionList>(`${loopPath(boardId, loopId)}/poc-decisions${suffix}`),
    );
  },

  async recordPocDecision(
    boardId: string,
    loopId: string,
    payload: PocDecisionPayload,
  ): Promise<PocDecision> {
    return json(
      await request<PocDecision>(`${loopPath(boardId, loopId)}/poc-decisions`, {
        method: "POST",
        body: payload,
      }),
    );
  },

  async answerPocDecision(
    boardId: string,
    loopId: string,
    decisionId: string,
    answer: PocAnswer,
  ): Promise<PocDecision> {
    return json(
      await request<PocDecision>(
        `${loopPath(boardId, loopId)}/poc-decisions/${encodeURIComponent(decisionId)}/answer`,
        { method: "POST", body: answer },
      ),
    );
  },

  async getLoopStops(boardId: string, loopId: string): Promise<StopList> {
    return json(await request<StopList>(`${loopPath(boardId, loopId)}/stops`));
  },

  async saveLoopStops(boardId: string, loopId: string, stops: string[]): Promise<StopList> {
    return json(
      await request<StopList>(`${loopPath(boardId, loopId)}/stops`, {
        method: "PUT",
        body: { stops },
      }),
    );
  },
};
