import type { AgentPayload } from "@/lib/api";
import { PROVIDER_PRESETS, presetById } from "@/lib/providers";
import type { Agent, ConnectionType } from "@/lib/types";

const ADJECTIVES: readonly [string, ...string[]] = [
  "Curious",
  "Careful",
  "Pragmatic",
  "Bold",
  "Thorough",
  "Skeptical",
  "Swift",
  "Calm",
  "Precise",
  "Inventive",
];
const NOUNS: readonly [string, ...string[]] = [
  "Otter",
  "Badger",
  "Heron",
  "Lynx",
  "Marten",
  "Falcon",
  "Beaver",
  "Raven",
  "Ibex",
  "Pike",
];

/** One word at random; the fallback never runs, the tuple type proves the list is not empty. */
function pick(words: readonly [string, ...string[]]): string {
  return words[Math.floor(Math.random() * words.length)] ?? words[0];
}

export function randomName(): string {
  return `${pick(ADJECTIVES)} ${pick(NOUNS)} ${Math.floor(10 + Math.random() * 90)}`;
}

/** The agent editor's fields as typed, before they become a request. */
export interface AgentForm {
  name: string;
  description: string;
  roleTemplateId: string;
  override: string;
  connectionType: ConnectionType;
  providerId: string;
  baseUrl: string;
  model: string;
  apiKey: string;
  /** Unticked by default: the field is available until you say the endpoint needs no credential. */
  noKey: boolean;
  temperature: string;
  maxTokens: string;
  timeoutSeconds: string;
  enabled: boolean;
}

/** A fresh agent starts with a generated name; an existing one is filled in once it loads. */
export function emptyAgentForm(isNew: boolean): AgentForm {
  return {
    name: isNew ? randomName() : "",
    description: "",
    roleTemplateId: "",
    override: "",
    connectionType: "openai_compatible",
    providerId: "custom",
    baseUrl: "",
    model: "",
    apiKey: "",
    noKey: false,
    temperature: "",
    maxTokens: "",
    timeoutSeconds: "30",
    enabled: true,
  };
}

/** The form filled from a stored agent. The override and a typed key are not part of an agent. */
export function hydrateAgentForm(current: AgentForm, loaded: Agent): AgentForm {
  return {
    ...current,
    name: loaded.name,
    description: loaded.description,
    roleTemplateId: loaded.role_template_id ?? "",
    connectionType: loaded.connection_type,
    baseUrl: loaded.base_url,
    providerId:
      PROVIDER_PRESETS.find(
        (preset) => preset.baseUrl && loaded.base_url.startsWith(preset.baseUrl),
      )?.id ?? "custom",
    model: loaded.model ?? "",
    noKey: !loaded.has_api_key,
    temperature: loaded.temperature === null ? "" : String(loaded.temperature),
    maxTokens: loaded.max_output_tokens === null ? "" : String(loaded.max_output_tokens),
    timeoutSeconds: String(loaded.timeout_seconds),
    enabled: loaded.enabled,
  };
}

/**
 * The form after choosing a provider preset. A known local preset needs no key; anything you point
 * at yourself may or may not. Leaving a hosted provider clears what its preset filled in.
 */
export function withProvider(form: AgentForm, providerId: string): AgentForm {
  const previous = presetById(form.providerId);
  const chosen = presetById(providerId);
  if (!chosen) return { ...form, providerId };
  const next = { ...form, providerId, noKey: chosen.id !== "custom" && !chosen.requiresApiKey };
  if (chosen.id !== "custom") return { ...next, baseUrl: chosen.baseUrl, model: chosen.model };
  if (previous?.baseUrlFixed) return { ...next, baseUrl: "", model: "" };
  return next;
}

/** Everything the agent stores except its credential. */
export function agentPayload(form: AgentForm) {
  return {
    name: form.name.trim(),
    description: form.description,
    role_template_id: form.roleTemplateId || null,
    role_prompt_override: form.override.trim() ? form.override.trim() : null,
    connection_type: form.connectionType,
    base_url: form.baseUrl.trim(),
    model: form.model.trim() || null,
    temperature: form.temperature.trim() === "" ? null : Number(form.temperature),
    max_output_tokens: form.maxTokens.trim() === "" ? null : Number(form.maxTokens),
    timeout_seconds: Number(form.timeoutSeconds) || 30,
    enabled: form.enabled,
  } satisfies AgentPayload;
}
