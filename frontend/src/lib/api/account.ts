import type {
  Actor,
  ApiMeta,
  Credential,
  InviteCreated,
  Role,
  UserAccount,
  UserPreferences,
} from "../types";
import { json, request } from "./client";

/** Signing in and out, the session's own settings, access keys and user accounts. */
export const accountApi = {
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

  async meta(): Promise<ApiMeta> {
    return json(await request<ApiMeta>("/meta"));
  },

  async updatePreferences(payload: {
    theme_mode?: UserPreferences["theme_mode"];
    theme_kit?: UserPreferences["theme_kit"];
  }): Promise<UserPreferences> {
    return json(
      await request<UserPreferences>("/auth/preferences", { method: "PUT", body: payload }),
    );
  },

  async listCredentials(ownerId?: string): Promise<Credential[]> {
    const suffix = ownerId ? `?owner_id=${encodeURIComponent(ownerId)}` : "";
    return json(await request<Credential[]>(`/credentials${suffix}`));
  },

  async listMyCredentials(): Promise<Credential[]> {
    return json(await request<Credential[]>("/credentials/mine"));
  },

  async createCredential(payload: {
    name: string;
    scopes: string[];
    expires_in_days?: number | undefined;
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
    payload: { role?: Role | undefined; disabled?: boolean | undefined },
  ): Promise<UserAccount> {
    return json(await request<UserAccount>(`/users/${userId}`, { method: "PATCH", body: payload }));
  },

  async inviteUser(userId: string, expiresInHours?: number): Promise<InviteCreated> {
    return json(
      await request<InviteCreated>(`/users/${userId}/invite`, {
        method: "POST",
        body: expiresInHours ? { expires_in_hours: expiresInHours } : {},
      }),
    );
  },

  async enrol(token: string, password: string): Promise<{ actor: Actor; csrf_token: string }> {
    return json(
      await request<{ actor: Actor; csrf_token: string }>("/auth/enrol", {
        method: "POST",
        body: { token, password },
      }),
    );
  },

  async resetUserPassword(userId: string, newPassword: string): Promise<void> {
    await request(`/users/${userId}/password`, {
      method: "POST",
      body: { new_password: newPassword },
    });
  },
};
