import type { BoardTemplate, RoleTemplate } from "../types";
import { json, request } from "./client";

export interface TemplatePayload {
  name: string;
  description?: string;
  lists?: string[];
  labels?: { name: string; color: string }[];
}

export interface RoleTemplatePayload {
  name?: string;
  description?: string;
  system_prompt?: string;
}

/** Board templates and role templates, both registry data. */
export const templatesApi = {
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
    loopId: string,
    payload: { name: string; description?: string },
  ): Promise<BoardTemplate> {
    return json(
      await request<BoardTemplate>(`/boards/${boardId}/loops/${loopId}/templates`, {
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
    return json(await request<RoleTemplate>("/role-templates", { method: "POST", body: payload }));
  },

  async updateRoleTemplate(roleId: string, payload: RoleTemplatePayload): Promise<RoleTemplate> {
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
};
