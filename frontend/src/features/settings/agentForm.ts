import type { AgentPayload } from "@/lib/api";
import { PROVIDER_PRESETS, presetById, type ProviderPreset } from "@/lib/providers";
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

/** How long a call waits for an answer, unless the agent says otherwise; the API's default. */
export const DEFAULT_TIMEOUT_SECONDS = 180;
/** The longest wait the API accepts. */
export const MAX_TIMEOUT_SECONDS = 900;

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
    // A reasoning or local model needs minutes for a structured answer; the server's default too.
    timeoutSeconds: String(DEFAULT_TIMEOUT_SECONDS),
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

/** A field of the agent's request, spelled as the API names it when it refuses a save. */
export type AgentField = Exclude<keyof AgentPayload, "clear_api_key">;

/**
 * What ties an input to the request field it is sent as: its `name`, and `aria-invalid` while the
 * last save was refused for that field.
 */
export function fieldMark(invalid: ReadonlySet<string>, field: AgentField) {
  return { name: field, "aria-invalid": invalid.has(field) || undefined };
}

/**
 * Why the answer length cannot be saved for this preset, naming the provider's cap; null when it
 * can (empty, or no cap is known).
 */
export function answerLengthProblem(form: AgentForm, preset: ProviderPreset | undefined) {
  const cap = preset?.maxOutputTokens;
  const wanted = Number(form.maxTokens);
  if (cap === undefined || form.maxTokens.trim() === "" || !(wanted > cap)) return null;
  return `${preset?.label ?? "This provider"} answers at most ${cap.toLocaleString("en-US")} tokens; leave the field empty for its default.`;
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
    timeout_seconds: Number(form.timeoutSeconds) || DEFAULT_TIMEOUT_SECONDS,
    enabled: form.enabled,
  } satisfies AgentPayload;
}
