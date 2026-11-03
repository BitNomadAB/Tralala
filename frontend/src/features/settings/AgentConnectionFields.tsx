import { Field, Input, Select } from "@/components/ui/input";
import { PROVIDER_PRESETS, type PresetRequirements, type ProviderPreset } from "@/lib/providers";
import type { Agent, ConnectionType } from "@/lib/types";
import type { AgentForm } from "./agentForm";

/** How Tralala reaches the agent: transport, provider preset, endpoint, model and credential. */
export function AgentConnectionFields({
  form,
  onChange,
  onProviderChange,
  preset,
  requirements,
  endpointLocked,
  testModels,
  stored,
}: {
  form: AgentForm;
  onChange: (patch: Partial<AgentForm>) => void;
  onProviderChange: (providerId: string) => void;
  preset: ProviderPreset | undefined;
  requirements: PresetRequirements;
  endpointLocked: boolean;
  testModels: string[];
  stored: Agent | undefined;
}) {
  const { connectionType, noKey } = form;
  const hasStoredKey = Boolean(stored?.has_api_key);
  return (
    <>
      <Field
        label="Connection type"
        htmlFor="agent-connection"
        hint={
          connectionType === "a2a"
            ? "An agent that already runs outside Tralala. It brings its own tools, memory and way of working; the role here only decides how it answers in this board."
            : "A model endpoint you point Tralala at. It has no tools or memory of its own here: Tralala sends the role prompt and the conversation, and the model answers as that role."
        }
      >
        <Select
          id="agent-connection"
          value={connectionType}
          onChange={(event) => onChange({ connectionType: event.target.value as ConnectionType })}
        >
          <option value="openai_compatible">OpenAI-compatible API — a model you point at</option>
          <option value="a2a">A2A agent — an agent that already exists</option>
        </Select>
      </Field>
      {connectionType === "openai_compatible" ? (
        <Field
          label="Provider preset"
          htmlFor="agent-provider"
          hint={preset?.hint ?? "Prefills the base URL and default model."}
        >
          <Select
            id="agent-provider"
            value={form.providerId}
            onChange={(event) => onProviderChange(event.target.value)}
          >
            {PROVIDER_PRESETS.map((entry) => (
              <option key={entry.id} value={entry.id}>
                {entry.label}
              </option>
            ))}
          </Select>
        </Field>
      ) : null}
      <Field
        label={connectionType === "a2a" ? "Agent endpoint or card URL" : "API base URL"}
        htmlFor="agent-base-url"
        hint={
          endpointLocked
            ? "Fixed by the preset. Choose Custom to point somewhere else."
            : "Credentials are encrypted; local endpoints are allowed."
        }
      >
        <Input
          id="agent-base-url"
          value={form.baseUrl}
          onChange={(event) => onChange({ baseUrl: event.target.value })}
          placeholder={
            connectionType === "a2a" ? "http://127.0.0.1:9001" : "http://127.0.0.1:8080/v1"
          }
          readOnly={endpointLocked}
          required
        />
        {preset?.docsUrl ? (
          <a
            className="text-[11px] underline text-[var(--muted-foreground)]"
            href={preset.docsUrl}
            target="_blank"
            rel="noreferrer noopener"
          >
            {preset.label} API documentation
          </a>
        ) : null}
      </Field>
      <Field
        label={
          connectionType === "a2a"
            ? "Model identifier"
            : requirements.model === "required"
              ? "Model identifier (required)"
              : "Model identifier (optional)"
        }
        htmlFor="agent-model"
        hint={
          connectionType === "a2a"
            ? "Optional. The A2A agent chooses its own model."
            : testModels.length > 0
              ? `${testModels.length} model(s) reported by the endpoint — pick one, or type a name it accepts.`
              : (preset?.hint ?? "Run the connection test to see which models the endpoint offers.")
        }
      >
        <Input
          id="agent-model"
          value={form.model}
          onChange={(event) => onChange({ model: event.target.value })}
          placeholder={
            connectionType === "a2a" ? "" : (preset?.modelPlaceholder ?? "llama-3.1-8b-instruct")
          }
          list={testModels.length > 0 ? "agent-model-options" : undefined}
        />
        {testModels.length > 0 ? (
          <datalist id="agent-model-options">
            {testModels.map((name) => (
              <option key={name} value={name} />
            ))}
          </datalist>
        ) : null}
      </Field>
      <Field
        label={
          noKey
            ? "API key (not used)"
            : hasStoredKey
              ? "Replace API key"
              : requirements.apiKey === "required" && connectionType !== "a2a"
                ? "API key (required)"
                : "API key (optional)"
        }
        htmlFor="agent-api-key"
        hint={
          hasStoredKey
            ? `A key is stored${stored?.api_key_hint ? ` (${stored.api_key_hint})` : ""}. Leave empty to keep it.`
            : connectionType === "a2a"
              ? "Only if the agent card requires one."
              : requirements.apiKey === "required"
                ? "This provider rejects calls without a key."
                : "Not used by this provider; a local endpoint accepts calls without one."
        }
      >
        <Input
          id="agent-api-key"
          type="password"
          autoComplete="off"
          value={noKey ? "" : form.apiKey}
          disabled={noKey}
          onChange={(event) => onChange({ apiKey: event.target.value })}
          placeholder={noKey ? "not used" : stored?.has_api_key ? "••••" : ""}
        />
        <label className="mt-1 flex items-center gap-2 text-xs">
          <input
            type="checkbox"
            checked={noKey}
            onChange={(event) =>
              onChange(event.target.checked ? { noKey: true, apiKey: "" } : { noKey: false })
            }
          />
          This endpoint needs no key
        </label>
        {noKey ? (
          <p className="text-[11px] text-[var(--muted-foreground)]">
            No <code>Authorization</code> header is sent, in the test or in a call. A model on the
            same machine or network usually works this way.
          </p>
        ) : null}
      </Field>
    </>
  );
}

/** Sampling, limits and whether discussions may use the agent. */
export function AgentTuningFields({
  form,
  onChange,
}: {
  form: AgentForm;
  onChange: (patch: Partial<AgentForm>) => void;
}) {
  return (
    <>
      <Field label="Temperature" htmlFor="agent-temperature">
        <Input
          id="agent-temperature"
          type="number"
          step="0.1"
          min={0}
          max={2}
          value={form.temperature}
          onChange={(event) => onChange({ temperature: event.target.value })}
        />
      </Field>
      <Field label="Max output tokens" htmlFor="agent-max-tokens">
        <Input
          id="agent-max-tokens"
          type="number"
          min={1}
          value={form.maxTokens}
          onChange={(event) => onChange({ maxTokens: event.target.value })}
        />
      </Field>
      <Field label="Timeout (seconds)" htmlFor="agent-timeout">
        <Input
          id="agent-timeout"
          type="number"
          min={1}
          max={600}
          value={form.timeoutSeconds}
          onChange={(event) => onChange({ timeoutSeconds: event.target.value })}
        />
      </Field>
      <label className="mt-6 flex items-center gap-2 text-sm">
        <input
          type="checkbox"
          checked={form.enabled}
          onChange={(event) => onChange({ enabled: event.target.checked })}
        />
        Enabled for discussions
      </label>
    </>
  );
}
