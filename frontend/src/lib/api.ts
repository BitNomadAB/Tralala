import type {
  ActivityEntry,
  Actor,
  Agent,
  AgentDirectoryEntry,
  AgentTestResult,
  Board,
  BoardList,
  BoardTemplate,
  Card,
  CardDetail,
  Checklist,
  ChecklistItem,
  Comment,
  ConnectionType,
  Discussion,
  DiscussionBoard,
  DiscussionRun,
  DiscussionRunSummary,
  Credential,
  Label,
  MentionJob,
  PageMeta,
  Priority,
  Role,
  RoleTemplate,
  UserAccount,
  UserPreferences,
} from "./types";

export class ApiError extends Error {
  readonly code: string;
  readonly status: number;
  readonly retryable: boolean;
  readonly details: unknown;

  constructor(
    message: string,
    options: { code: string; status: number; retryable?: boolean; details?: unknown },
  ) {
    super(message);
    this.name = "ApiError";
    this.code = options.code;
    this.status = options.status;
    this.retryable = options.retryable ?? false;
    this.details = options.details;
  }
}

interface Envelope<T> {
  success: boolean;
  data: T;
  request_id: string;
  meta?: PageMeta;
}

interface ErrorEnvelope {
  success: false;
  error: { code: string; message: string; retryable?: boolean; details?: unknown };
  request_id: string;
}

export interface ApiResult<T> {
  data: T;
  meta?: PageMeta;
}

function readCookie(name: string): string | null {
  const match = document.cookie
    .split(";")
    .map((part) => part.trim())
    .find((part) => part.startsWith(`${name}=`));
  return match ? decodeURIComponent(match.slice(name.length + 1)) : null;
}

async function request<T>(
  path: string,
  options: { method?: string; body?: unknown; headers?: Record<string, string> } = {},
): Promise<ApiResult<T>> {
  const method = options.method ?? "GET";
  const headers: Record<string, string> = { Accept: "application/json", ...options.headers };
  if (method !== "GET" && method !== "HEAD") {
    const csrf = readCookie("tralala_csrf");
    if (csrf) headers["X-CSRF-Token"] = csrf;
  }
  let body: BodyInit | undefined;
  if (options.body instanceof Blob || options.body instanceof ArrayBuffer) {
    body = options.body as BodyInit;
  } else if (options.body !== undefined) {
    headers["Content-Type"] = "application/json";
    body = JSON.stringify(options.body);
  }

  const response = await fetch(`/api/v1${path}`, {
    method,
    headers,
    body,
    credentials: "include",
  });

  if (response.status === 204) {
    return { data: undefined as T };
  }

  const payload = (await response.json().catch(() => null)) as
    | Envelope<T>
    | ErrorEnvelope
    | null;

  if (!response.ok || payload === null || payload.success === false) {
    const error = (payload as ErrorEnvelope | null)?.error;
    if (response.status === 401) {
      window.dispatchEvent(new CustomEvent("tralala:unauthorized"));
    }
    throw new ApiError(error?.message ?? `Request failed (${response.status})`, {
      code: error?.code ?? `http_${response.status}`,
      status: response.status,
      retryable: error?.retryable,
      details: error?.details,
    });
  }

  return { data: payload.data, meta: payload.meta };
}

const json = <T,>(result: ApiResult<T>): T => result.data;

export interface TemplatePayload {
  name: string;
  description?: string;
  lists?: string[];
  labels?: Array<{ name: string; color: string }>;
}

export interface RoleTemplatePayload {
  name?: string;
  description?: string;
  system_prompt?: string;
}

export interface AgentPayload {
  name?: string;
  description?: string;
  role_template_id?: string | null;
  role_prompt_override?: string | null;
  connection_type?: ConnectionType;
  base_url?: string;
  model?: string | null;
  api_key?: string | null;
  clear_api_key?: boolean;
  temperature?: number | null;
  max_output_tokens?: number | null;
  timeout_seconds?: number;
  enabled?: boolean;
}

export const api = {
  async login(username: string, password: string): Promise<Actor> {
    const result = await request<{ actor: Actor; csrf_token: string }>("/auth/login", {
      method: "POST",
      body: { username, password },
    });
    return result.data.actor;
  },

  async logout(): Promise<void> {
    await request("/auth/logout", { method: "POST" });
  },

  async me(): Promise<Actor> {
    return json(await request<Actor>("/auth/me"));
  },

  async updatePreferences(payload: {
    theme_mode?: UserPreferences["theme_mode"];
    theme_kit?: UserPreferences["theme_kit"];
  }): Promise<UserPreferences> {
    return json(await request<UserPreferences>("/auth/preferences", { method: "PUT", body: payload }));
  },

  async listBoards(
    params: {
      q?: string;
      status?: string;
      sort?: string;
      order?: string;
      limit?: number;
    } = {},
  ) {
    const query = new URLSearchParams(
      Object.entries(params).filter(([, value]) => Boolean(value)) as [string, string][],
    );
    const result = await request<Board[]>(`/boards?${query.toString()}`);
    return { items: result.data, meta: result.meta };
  },

  async getBoard(boardId: string): Promise<Board> {
    return json(await request<Board>(`/boards/${boardId}`));
  },

  async createBoard(payload: {
    name: string;
    description?: string;
    template_id?: string | null;
  }): Promise<Board> {
    return json(await request<Board>("/boards", { method: "POST", body: payload }));
  },

  async listTemplates(): Promise<BoardTemplate[]> {
    return json(await request<{ items: BoardTemplate[] }>("/templates")).items;
  },

  async getTemplate(templateId: string): Promise<BoardTemplate> {
    return json(await request<BoardTemplate>(`/templates/${templateId}`));
  },

  async createTemplate(payload: TemplatePayload): Promise<BoardTemplate> {
    return json(await request<BoardTemplate>("/templates", { method: "POST", body: payload }));
  },

  async updateTemplate(templateId: string, payload: TemplatePayload): Promise<BoardTemplate> {
    return json(
      await request<BoardTemplate>(`/templates/${templateId}`, {
        method: "PATCH",
        body: payload,
      }),
    );
  },

  async deleteTemplate(templateId: string): Promise<void> {
    await request(`/templates/${templateId}`, { method: "DELETE" });
  },

  async saveBoardAsTemplate(
    boardId: string,
    payload: { name: string; description?: string },
  ): Promise<BoardTemplate> {
    return json(
      await request<BoardTemplate>(`/boards/${boardId}/templates`, {
        method: "POST",
        body: payload,
      }),
    );
  },

  async listRoleTemplates(): Promise<RoleTemplate[]> {
    return json(await request<RoleTemplate[]>("/role-templates"));
  },

  async getRoleTemplate(roleId: string): Promise<RoleTemplate> {
    return json(await request<RoleTemplate>(`/role-templates/${roleId}`));
  },

  async createRoleTemplate(payload: RoleTemplatePayload): Promise<RoleTemplate> {
    return json(
      await request<RoleTemplate>("/role-templates", { method: "POST", body: payload }),
    );
  },

  async updateRoleTemplate(
    roleId: string,
    payload: RoleTemplatePayload,
  ): Promise<RoleTemplate> {
    return json(
      await request<RoleTemplate>(`/role-templates/${roleId}`, {
        method: "PATCH",
        body: payload,
      }),
    );
  },

  async duplicateRoleTemplate(roleId: string, name?: string): Promise<RoleTemplate> {
    return json(
      await request<RoleTemplate>(`/role-templates/${roleId}/duplicate`, {
        method: "POST",
        body: name ? { name } : {},
      }),
    );
  },

  async restoreRoleTemplate(roleId: string): Promise<RoleTemplate> {
    return json(
      await request<RoleTemplate>(`/role-templates/${roleId}/restore-defaults`, {
        method: "POST",
        body: {},
      }),
    );
  },

  async deleteRoleTemplate(roleId: string): Promise<void> {
    await request(`/role-templates/${roleId}`, { method: "DELETE" });
  },

  async listAgents(params: { q?: string; enabled?: boolean } = {}): Promise<Agent[]> {
    const query = new URLSearchParams(
      Object.entries(params)
        .filter(([, value]) => value !== undefined && value !== "")
        .map(([key, value]) => [key, String(value)]) as [string, string][],
    );
    return json(await request<Agent[]>(`/agents?${query.toString()}`));
  },

  async getAgent(agentId: string): Promise<Agent> {
    return json(await request<Agent>(`/agents/${agentId}`));
  },

  async listAgentDirectory(): Promise<AgentDirectoryEntry[]> {
    return json(await request<AgentDirectoryEntry[]>("/agents/directory"));
  },

  async createAgent(payload: AgentPayload): Promise<Agent> {
    return json(await request<Agent>("/agents", { method: "POST", body: payload }));
  },

  async updateAgent(agentId: string, payload: AgentPayload): Promise<Agent> {
    return json(await request<Agent>(`/agents/${agentId}`, { method: "PATCH", body: payload }));
  },

  async duplicateAgent(agentId: string, name?: string): Promise<Agent> {
    return json(
      await request<Agent>(`/agents/${agentId}/duplicate`, {
        method: "POST",
        body: name ? { name } : {},
      }),
    );
  },

  async testAgent(
    agentId: string,
    payload: {
      connection_type?: ConnectionType;
      base_url?: string;
      model?: string;
      api_key?: string;
    } = {},
  ): Promise<AgentTestResult> {
    return json(
      await request<AgentTestResult>(`/agents/${agentId}/test`, {
        method: "POST",
        body: payload,
      }),
    );
  },

  async listDiscussionBoards(): Promise<DiscussionBoard[]> {
    return json(await request<{ items: DiscussionBoard[] }>("/discussions/overview")).items;
  },

  async listDiscussions(boardId: string): Promise<Discussion[]> {
    return json(await request<{ items: Discussion[] }>(`/boards/${boardId}/discussions`)).items;
  },

  async getDiscussion(boardId: string, discussionId: string): Promise<Discussion> {
    return json(await request<Discussion>(`/boards/${boardId}/discussions/${discussionId}`));
  },

  async createDiscussion(
    boardId: string,
    payload: {
      card_id: string;
      title?: string;
      goal: string;
      mode?: string;
      participant_ids?: string[];
      max_rounds?: number;
    },
  ): Promise<Discussion> {
    return json(
      await request<Discussion>(`/boards/${boardId}/discussions`, { method: "POST", body: payload }),
    );
  },

  async startDiscussion(
    boardId: string,
    discussionId: string,
    payload: {
      rounds?: number;
      autonomous?: boolean;
      token_budget?: number;
      time_budget_seconds?: number;
    } = {},
  ): Promise<DiscussionRunSummary> {
    return json(
      await request(`/boards/${boardId}/discussions/${discussionId}/start`, {
        method: "POST",
        body: payload,
      }),
    );
  },

  async listDiscussionRuns(boardId: string, discussionId: string): Promise<DiscussionRun[]> {
    return json(
      await request<{ items: DiscussionRun[] }>(
        `/boards/${boardId}/discussions/${discussionId}/runs`,
      ),
    ).items;
  },

  async getDiscussionRun(
    boardId: string,
    discussionId: string,
    runId: string,
  ): Promise<DiscussionRun> {
    return json(
      await request<DiscussionRun>(
        `/boards/${boardId}/discussions/${discussionId}/runs/${runId}`,
      ),
    );
  },

  async controlDiscussionRun(
    boardId: string,
    discussionId: string,
    runId: string,
    action: "pause" | "resume" | "stop",
  ): Promise<DiscussionRunSummary> {
    return json(
      await request(`/boards/${boardId}/discussions/${discussionId}/runs/${runId}/${action}`, {
        method: "POST",
        body: {},
      }),
    );
  },

  async reviewDiscussion(
    boardId: string,
    discussionId: string,
    payload: { decision: "approve" | "veto" | "rework"; reason?: string },
  ): Promise<Discussion> {
    return json(
      await request<Discussion>(`/boards/${boardId}/discussions/${discussionId}/review`, {
        method: "POST",
        body: payload,
      }),
    );
  },

  async postDiscussionMessage(
    boardId: string,
    discussionId: string,
    payload: { content: string; parent_message_id?: string },
  ): Promise<Discussion> {
    return json(
      await request<Discussion>(`/boards/${boardId}/discussions/${discussionId}/messages`, {
        method: "POST",
        body: payload,
      }),
    );
  },

  async deleteAgent(agentId: string): Promise<void> {
    await request(`/agents/${agentId}`, { method: "DELETE" });
  },

  async updateBoard(
    boardId: string,
    payload: { name?: string; description?: string },
  ): Promise<Board> {
    return json(await request<Board>(`/boards/${boardId}`, { method: "PATCH", body: payload }));
  },

  async archiveBoard(boardId: string): Promise<Board> {
    return json(await request<Board>(`/boards/${boardId}/archive`, { method: "POST" }));
  },

  async restoreBoard(boardId: string): Promise<Board> {
    return json(await request<Board>(`/boards/${boardId}/restore`, { method: "POST" }));
  },

  async duplicateBoard(boardId: string): Promise<Board> {
    return json(await request<Board>(`/boards/${boardId}/duplicate`, { method: "POST" }));
  },

  async deleteBoard(boardId: string, confirmName: string): Promise<void> {
    await request(`/boards/${boardId}`, { method: "DELETE", body: { confirm_name: confirmName } });
  },

  exportUrl(boardId: string): string {
    return `/api/v1/boards/${boardId}/export`;
  },

  async importBoard(file: File): Promise<Board> {
    return json(
      await request<Board>("/boards/import", {
        method: "POST",
        body: file,
        headers: { "Content-Type": "application/zip" },
      }),
    );
  },

  async listLists(boardId: string): Promise<BoardList[]> {
    return json(await request<BoardList[]>(`/boards/${boardId}/lists`));
  },

  async createList(boardId: string, name: string): Promise<BoardList> {
    return json(
      await request<BoardList>(`/boards/${boardId}/lists`, { method: "POST", body: { name } }),
    );
  },

  async renameList(boardId: string, listId: string, name: string): Promise<BoardList> {
    return json(
      await request<BoardList>(`/boards/${boardId}/lists/${listId}`, {
        method: "PATCH",
        body: { name },
      }),
    );
  },

  async moveList(boardId: string, listId: string, position: number): Promise<BoardList[]> {
    return json(
      await request<BoardList[]>(`/boards/${boardId}/lists/${listId}/move`, {
        method: "POST",
        body: { position },
      }),
    );
  },

  async archiveList(boardId: string, listId: string): Promise<BoardList> {
    return json(
      await request<BoardList>(`/boards/${boardId}/lists/${listId}/archive`, { method: "POST" }),
    );
  },

  async listCards(
    boardId: string,
    params: { list_id?: string; limit?: number; include_archived?: boolean } = {},
  ): Promise<Card[]> {
    const query = new URLSearchParams(
      Object.entries(params)
        .filter(([, value]) => value !== undefined && value !== "")
        .map(([key, value]) => [key, String(value)]),
    );
    return json(await request<Card[]>(`/boards/${boardId}/cards?${query.toString()}`));
  },

  async searchCards(
    boardId: string,
    params: {
      q?: string;
      label?: string;
      priority?: Priority;
      overdue?: boolean;
      completed?: boolean;
      include_archived?: boolean;
      limit?: number;
    },
  ): Promise<{ items: Card[]; meta?: PageMeta }> {
    const query = new URLSearchParams(
      Object.entries(params)
        .filter(([, value]) => value !== undefined && value !== "" && value !== false)
        .map(([key, value]) => [key, String(value)]),
    );
    const result = await request<Card[]>(`/boards/${boardId}/search?${query.toString()}`);
    return { items: result.data, meta: result.meta };
  },

  async getCard(boardId: string, cardId: string): Promise<CardDetail> {
    const result = await request<CardDetail>(
      `/boards/${boardId}/cards/${cardId}?include=checklists,comments`,
    );
    return result.data;
  },

  async createCard(
    boardId: string,
    payload: {
      list_id: string;
      title: string;
      description?: string;
      priority?: Priority;
      due_at?: string | null;
      labels?: string[];
    },
  ): Promise<Card> {
    return json(
      await request<Card>(`/boards/${boardId}/cards`, { method: "POST", body: payload }),
    );
  },

  async updateCard(
    boardId: string,
    cardId: string,
    payload: {
      version: number;
      title?: string;
      description?: string;
      priority?: Priority;
      due_at?: string;
      clear_due_at?: boolean;
      completed?: boolean;
      labels?: string[];
    },
  ): Promise<Card> {
    return json(
      await request<Card>(`/boards/${boardId}/cards/${cardId}`, {
        method: "PATCH",
        body: payload,
      }),
    );
  },

  async moveCard(
    boardId: string,
    cardId: string,
    payload: { version: number; list_id: string; position: number },
  ): Promise<Card> {
    return json(
      await request<Card>(`/boards/${boardId}/cards/${cardId}/move`, {
        method: "POST",
        body: payload,
      }),
    );
  },

  async archiveCard(boardId: string, cardId: string): Promise<Card> {
    return json(
      await request<Card>(`/boards/${boardId}/cards/${cardId}/archive`, { method: "POST" }),
    );
  },

  async restoreCard(boardId: string, cardId: string): Promise<Card> {
    return json(
      await request<Card>(`/boards/${boardId}/cards/${cardId}/restore`, { method: "POST" }),
    );
  },

  async retryMigration(boardId: string): Promise<{ status: string; to_revision: string | null }> {
    return json(
      await request(`/boards/${boardId}/migrate`, { method: "POST" }),
    );
  },

  async listLabels(boardId: string): Promise<Label[]> {
    return json(await request<Label[]>(`/boards/${boardId}/labels`));
  },

  async createLabel(boardId: string, name: string, color: string): Promise<Label> {
    return json(
      await request<Label>(`/boards/${boardId}/labels`, {
        method: "POST",
        body: { name, color },
      }),
    );
  },

  async addChecklist(boardId: string, cardId: string, title: string): Promise<Checklist> {
    return json(
      await request<Checklist>(`/boards/${boardId}/cards/${cardId}/checklists`, {
        method: "POST",
        body: { title },
      }),
    );
  },

  async addChecklistItem(
    boardId: string,
    checklistId: string,
    text: string,
  ): Promise<ChecklistItem> {
    return json(
      await request<ChecklistItem>(`/boards/${boardId}/checklists/${checklistId}/items`, {
        method: "POST",
        body: { text },
      }),
    );
  },

  async updateChecklistItem(
    boardId: string,
    itemId: string,
    payload: { text?: string; completed?: boolean },
  ): Promise<ChecklistItem> {
    return json(
      await request<ChecklistItem>(`/boards/${boardId}/checklist-items/${itemId}`, {
        method: "PATCH",
        body: payload,
      }),
    );
  },

  async deleteChecklistItem(boardId: string, itemId: string): Promise<void> {
    await request(`/boards/${boardId}/checklist-items/${itemId}`, { method: "DELETE" });
  },

  async addComment(boardId: string, cardId: string, content: string): Promise<Comment> {
    return json(
      await request<Comment>(`/boards/${boardId}/cards/${cardId}/comments`, {
        method: "POST",
        body: { content },
      }),
    );
  },

  async listMentions(boardId: string, cardId: string): Promise<MentionJob[]> {
    return json(await request<MentionJob[]>(`/boards/${boardId}/cards/${cardId}/mentions`));
  },

  async retryMention(boardId: string, cardId: string, jobId: string): Promise<MentionJob> {
    return json(
      await request<MentionJob>(
        `/boards/${boardId}/cards/${cardId}/mentions/${jobId}/retry`,
        { method: "POST" },
      ),
    );
  },

  async listActivity(
    boardId: string,
    params: { entity_id?: string; limit?: number } = {},
  ): Promise<ActivityEntry[]> {
    const query = new URLSearchParams(
      Object.entries(params)
        .filter(([, value]) => value !== undefined)
        .map(([key, value]) => [key, String(value)]),
    );
    return json(await request<ActivityEntry[]>(`/boards/${boardId}/activity?${query.toString()}`));
  },

  async listCredentials(): Promise<Credential[]> {
    return json(await request<Credential[]>("/credentials"));
  },

  async createCredential(payload: {
    name: string;
    scopes: string[];
    expires_in_days?: number;
  }): Promise<Credential> {
    return json(await request<Credential>("/credentials", { method: "POST", body: payload }));
  },

  async revokeCredential(credentialId: string): Promise<void> {
    await request(`/credentials/${credentialId}/revoke`, { method: "POST" });
  },

  async rotateCredential(credentialId: string): Promise<Credential> {
    return json(
      await request<Credential>(`/credentials/${credentialId}/rotate`, { method: "POST" }),
    );
  },

  async changePassword(currentPassword: string, newPassword: string): Promise<void> {
    await request("/auth/password", {
      method: "POST",
      body: { current_password: currentPassword, new_password: newPassword },
    });
  },

  async listUsers(): Promise<UserAccount[]> {
    return json(await request<UserAccount[]>("/users"));
  },

  async createUser(payload: { name: string; password: string; role: Role }): Promise<UserAccount> {
    return json(await request<UserAccount>("/users", { method: "POST", body: payload }));
  },

  async updateUser(
    userId: string,
    payload: { role?: Role; disabled?: boolean },
  ): Promise<UserAccount> {
    return json(await request<UserAccount>(`/users/${userId}`, { method: "PATCH", body: payload }));
  },

  async resetUserPassword(userId: string, newPassword: string): Promise<void> {
    await request(`/users/${userId}/password`, {
      method: "POST",
      body: { new_password: newPassword },
    });
  },
};


