/**
 * The typed REST client: one module per domain, composed into the single `api` object every
 * caller uses. `client.ts` holds the envelope, the CSRF header and `ApiError`.
 */
import { accountApi } from "./account";
import { agentsApi } from "./agents";
import { attachmentsApi } from "./attachments";
import { boardsApi } from "./boards";
import { cardsApi } from "./cards";
import { discussionsApi } from "./discussions";
import { loopsApi } from "./loops";
import { loopWorkflowApi } from "./loopWorkflow";
import { templatesApi } from "./templates";
import { ticketWorkApi } from "./ticketWork";

export { ApiError, type ApiResult } from "./client";
export type { AgentPayload } from "./agents";
export type { RoleTemplatePayload, TemplatePayload } from "./templates";

export const api = {
  ...accountApi,
  ...boardsApi,
  ...templatesApi,
  ...agentsApi,
  ...loopsApi,
  ...loopWorkflowApi,
  ...cardsApi,
  ...ticketWorkApi,
  ...attachmentsApi,
  ...discussionsApi,
};
