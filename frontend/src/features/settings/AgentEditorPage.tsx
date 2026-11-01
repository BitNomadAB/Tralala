import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, Copy, PlugZap, Trash2, Wand2 } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent } from "@/components/ui/dialog";
import { Field, Input, Select, Textarea } from "@/components/ui/input";
import { useToast } from "@/components/ui/toast";
import { ApiError, api } from "@/lib/api";
import { useAgent, useRoleTemplates } from "@/lib/queries";
import { PROVIDER_PRESETS, presetById } from "@/lib/providers";
import { formatDateTime } from "@/lib/utils";
import type { Agent, AgentTestResult, ConnectionType } from "@/lib/types";

const ADJECTIVES = [
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
const NOUNS = [
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

function randomName(): string {
  const adjective = ADJECTIVES[Math.floor(Math.random() * ADJECTIVES.length)];
  const noun = NOUNS[Math.floor(Math.random() * NOUNS.length)];
  return `${adjective} ${noun} ${Math.floor(10 + Math.random() * 90)}`;
}

export function AgentEditorPage() {
  const { agentId } = useParams();
  const isNew = !agentId || agentId === "new";
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const toast = useToast();
  const agentQuery = useAgent(String(agentId));
  const rolesQuery = useRoleTemplates();
  const roles = rolesQuery.data ?? [];

  const [hydratedId, setHydratedId] = useState<string | null>(isNew ? "new" : null);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [roleTemplateId, setRoleTemplateId] = useState("");
  const [override, setOverride] = useState("");
  const [connectionType, setConnectionType] = useState<ConnectionType>("openai_compatible");
  const [providerId, setProviderId] = useState("custom");
  const [baseUrl, setBaseUrl] = useState("");
  const [model, setModel] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [temperature, setTemperature] = useState("");
  const [maxTokens, setMaxTokens] = useState("");
  const [timeoutSeconds, setTimeoutSeconds] = useState("30");
  const [enabled, setEnabled] = useState(true);
  const [testResult, setTestResult] = useState<AgentTestResult | null>(null);
  const [confirming, setConfirming] = useState(false);

  useEffect(() => {
    const agent: Agent | undefined = agentQuery.data;
    if (!agent || hydratedId === agent.id) return;
    setName(agent.name);
    setDescription(agent.description);
    setRoleTemplateId(agent.role_template_id ?? "");
    setConnectionType(agent.connection_type);
    setBaseUrl(agent.base_url);
    setProviderId(
      PROVIDER_PRESETS.find(
        (preset) => preset.baseUrl && agent.base_url.startsWith(preset.baseUrl),
      )?.id ?? "custom",
    );
    setModel(agent.model ?? "");
    setTemperature(agent.temperature === null ? "" : String(agent.temperature));
    setMaxTokens(agent.max_output_tokens === null ? "" : String(agent.max_output_tokens));
    setTimeoutSeconds(String(agent.timeout_seconds));
    setEnabled(agent.enabled);
    setHydratedId(agent.id);
  }, [agentQuery.data, hydratedId]);

  useEffect(() => {
    if (isNew && !name) setName(randomName());
    // Only seed a default name once for a fresh agent.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isNew]);

  const invalidate = () => queryClient.invalidateQueries({ queryKey: ["agents"] });

  const payload = {
    name: name.trim(),
    description,
    role_template_id: roleTemplateId || null,
    role_prompt_override: override.trim() ? override.trim() : null,
    connection_type: connectionType,
    base_url: baseUrl.trim(),
    model: model.trim() || null,
    temperature: temperature.trim() === "" ? null : Number(temperature),
    max_output_tokens: maxTokens.trim() === "" ? null : Number(maxTokens),
    timeout_seconds: Number(timeoutSeconds) || 30,
    enabled,
  };

  const saveMutation = useMutation({
    mutationFn: () => {
      const body = apiKey.trim() ? { ...payload, api_key: apiKey.trim() } : payload;
      return isNew ? api.createAgent(body) : api.updateAgent(String(agentId), body);
    },
    onSuccess: (agent) => {
      invalidate();
      queryClient.setQueryData(["agent", agent.id], agent);
      toast.push({ title: "Agent saved", variant: "success" });
      navigate("/settings");
    },
    onError: (error) =>
      toast.push({
        title: "Could not save agent",
        description: error instanceof ApiError ? error.message : undefined,
        variant: "error",
      }),
  });

  const testMutation = useMutation({
    mutationFn: () =>
      api.testAgent(String(agentId), {
        connection_type: connectionType,
        base_url: baseUrl.trim(),
        ...(model.trim() ? { model: model.trim() } : {}),
        ...(apiKey.trim() ? { api_key: apiKey.trim() } : {}),
      }),
    onSuccess: (result) => {
      setTestResult(result);
      invalidate();
      queryClient.invalidateQueries({ queryKey: ["agent", agentId] });
      toast.push({
        title: result.ok ? "Connection works" : "Connection failed",
        description: result.message,
        variant: result.ok ? "success" : "error",
      });
    },
    onError: (error) =>
      toast.push({
        title: "Test failed",
        description: error instanceof ApiError ? error.message : undefined,
        variant: "error",
      }),
  });

  const duplicateMutation = useMutation({
    mutationFn: () => api.duplicateAgent(String(agentId)),
    onSuccess: (agent) => {
      invalidate();
      toast.push({ title: "Agent duplicated", variant: "success" });
      navigate(`/settings/agents/${agent.id}`);
    },
    onError: (error) =>
      toast.push({
        title: "Could not duplicate agent",
        description: error instanceof ApiError ? error.message : undefined,
        variant: "error",
      }),
  });

  const deleteMutation = useMutation({
    mutationFn: () => api.deleteAgent(String(agentId)),
    onSuccess: () => {
      invalidate();
      setConfirming(false);
      toast.push({ title: "Agent deleted", variant: "success" });
      navigate("/settings");
    },
    onError: (error) =>
      toast.push({
        title: "Could not delete agent",
        description: error instanceof ApiError ? error.message : undefined,
        variant: "error",
      }),
  });

  if (!isNew && agentQuery.isLoading) {
    return <p className="text-sm text-[var(--muted-foreground)]">Loading agent…</p>;
  }
  if (!isNew && agentQuery.error) {
    return (
      <p role="alert" className="text-sm text-[var(--destructive)]">
        {agentQuery.error instanceof ApiError ? agentQuery.error.message : "Agent unavailable."}
      </p>
    );
  }

  const stored = agentQuery.data;
  const canSave = Boolean(name.trim() && baseUrl.trim() && (roleTemplateId || override.trim()));

  return (
    <section className="flex max-w-3xl flex-col gap-6">
      <div>
        <button
          type="button"
          onClick={() => navigate("/settings")}
          className="inline-flex items-center gap-1.5 text-xs text-[var(--muted-foreground)] hover:text-[var(--foreground)]"
        >
          <ArrowLeft size={14} /> Settings
        </button>
        <h1 className="mt-1 flex items-center gap-2 text-xl font-semibold">
          {isNew ? "New AI agent" : `Edit ${name || "agent"}`}
          {stored ? (
            <Badge tone={stored.enabled ? "success" : "neutral"}>
              {stored.enabled ? "enabled" : "disabled"}
            </Badge>
          ) : null}
        </h1>
        <p className="text-xs text-[var(--muted-foreground)]">
          The agent is its own resource: it has a stable id, its own connection and credentials, and
          references a shared role template. Discussions snapshot the effective prompt, so central
          template edits never rewrite history.
        </p>
      </div>

      <form
        className="card-surface flex flex-col gap-4 p-5"
        onSubmit={(event) => {
          event.preventDefault();
          if (canSave) saveMutation.mutate();
        }}
      >
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="Agent name" htmlFor="agent-name">
            <div className="flex gap-1.5">
              <Input
                id="agent-name"
                value={name}
                onChange={(event) => setName(event.target.value)}
                required
                maxLength={200}
              />
              <Button
                type="button"
                variant="outline"
                title="Generate random name"
                aria-label="Generate random name"
                onClick={() => setName(randomName())}
              >
                <Wand2 size={14} />
              </Button>
            </div>
          </Field>
          <Field label="Role template" htmlFor="agent-role" hint="Applied to future discussions only.">
            <Select
              id="agent-role"
              value={roleTemplateId}
              onChange={(event) => setRoleTemplateId(event.target.value)}
            >
              <option value="">No template (use override)</option>
              {roles.map((role) => (
                <option key={role.id} value={role.id}>
                  {role.name}
                  {role.built_in ? "" : " (custom)"}
                </option>
              ))}
            </Select>
          </Field>
        </div>

        <Field label="Description" htmlFor="agent-description">
          <Textarea
            id="agent-description"
            className="min-h-16"
            value={description}
            onChange={(event) => setDescription(event.target.value)}
            maxLength={20000}
          />
        </Field>

        <Field
          label="Role prompt override (optional)"
          htmlFor="agent-override"
          hint="Replaces the template prompt for this agent without touching the shared template."
        >
          <Textarea
            id="agent-override"
            className="min-h-32 font-mono text-xs"
            value={override}
            onChange={(event) => setOverride(event.target.value)}
            maxLength={20000}
          />
        </Field>

        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="Connection type" htmlFor="agent-connection">
            <Select
              id="agent-connection"
              value={connectionType}
              onChange={(event) => setConnectionType(event.target.value as ConnectionType)}
            >
              <option value="openai_compatible">OpenAI-compatible API</option>
              <option value="a2a">A2A agent</option>
            </Select>
          </Field>
          <Field
            label="Provider preset"
            htmlFor="agent-provider"
            hint={presetById(providerId)?.hint ?? "Prefills the base URL and default model."}
          >
            <Select
              id="agent-provider"
              value={providerId}
              onChange={(event) => {
                const preset = presetById(event.target.value);
                setProviderId(event.target.value);
                if (!preset || preset.id === "custom") return;
                setBaseUrl(preset.baseUrl);
                setModel(preset.model);
              }}
            >
              {PROVIDER_PRESETS.map((preset) => (
                <option key={preset.id} value={preset.id}>
                  {preset.label}
                </option>
              ))}
            </Select>
          </Field>
          <Field
            label={connectionType === "a2a" ? "Agent endpoint or card URL" : "API base URL"}
            htmlFor="agent-base-url"
            hint="Credentials are encrypted; local endpoints are allowed."
          >
            <Input
              id="agent-base-url"
              value={baseUrl}
              onChange={(event) => setBaseUrl(event.target.value)}
              placeholder={
                connectionType === "a2a"
                  ? "http://127.0.0.1:9001"
                  : "http://127.0.0.1:8080/v1"
              }
              required
            />
          </Field>
          <Field label="Model identifier" htmlFor="agent-model">
            <Input
              id="agent-model"
              value={model}
              onChange={(event) => setModel(event.target.value)}
              placeholder="llama-3.1-8b-instruct"
            />
          </Field>
          <Field
            label={stored?.has_api_key ? "Replace API key" : "API key (optional)"}
            htmlFor="agent-api-key"
            hint={
              stored?.has_api_key
                ? `A key is stored (${stored.api_key_hint}). Leave empty to keep it.`
                : "Local endpoints usually need no key."
            }
          >
            <Input
              id="agent-api-key"
              type="password"
              autoComplete="off"
              value={apiKey}
              onChange={(event) => setApiKey(event.target.value)}
              placeholder={stored?.has_api_key ? "••••" : ""}
            />
          </Field>
          <Field label="Temperature" htmlFor="agent-temperature">
            <Input
              id="agent-temperature"
              type="number"
              step="0.1"
              min={0}
              max={2}
              value={temperature}
              onChange={(event) => setTemperature(event.target.value)}
            />
          </Field>
          <Field label="Max output tokens" htmlFor="agent-max-tokens">
            <Input
              id="agent-max-tokens"
              type="number"
              min={1}
              value={maxTokens}
              onChange={(event) => setMaxTokens(event.target.value)}
            />
          </Field>
          <Field label="Timeout (seconds)" htmlFor="agent-timeout">
            <Input
              id="agent-timeout"
              type="number"
              min={1}
              max={600}
              value={timeoutSeconds}
              onChange={(event) => setTimeoutSeconds(event.target.value)}
            />
          </Field>
          <label className="mt-6 flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={enabled}
              onChange={(event) => setEnabled(event.target.checked)}
            />
            Enabled for discussions
          </label>
        </div>

        {testResult ? (
          <div
            role="status"
            className={`rounded-lg border p-2 text-xs ${
              testResult.ok
                ? "border-[var(--success,var(--primary))] text-[var(--foreground)]"
                : "border-[var(--destructive)] text-[var(--destructive)]"
            }`}
          >
            <p className="font-medium">
              {testResult.status}
              {testResult.latency_ms !== null ? ` · ${testResult.latency_ms} ms` : ""}
            </p>
            <p>{testResult.message}</p>
            {testResult.models.length > 0 ? (
              <p className="mt-1 text-[var(--muted-foreground)]">
                {testResult.models.slice(0, 8).join(", ")}
              </p>
            ) : null}
          </div>
        ) : null}
        {stored?.last_tested_at ? (
          <p className="text-[11px] text-[var(--muted-foreground)]">
            Last test {stored.last_test_status} · {formatDateTime(stored.last_tested_at)}
          </p>
        ) : null}

        <div className="flex flex-wrap items-center justify-end gap-2 border-t border-[var(--border)] pt-3">
          {!isNew ? (
            <Button
              type="button"
              variant="danger"
              className="mr-auto"
              onClick={() => setConfirming(true)}
            >
              <Trash2 size={14} /> Delete
            </Button>
          ) : null}
          {!isNew ? (
            <Button
              type="button"
              variant="outline"
              disabled={testMutation.isPending}
              onClick={() => testMutation.mutate()}
            >
              <PlugZap size={14} /> {testMutation.isPending ? "Testing…" : "Test connection"}
            </Button>
          ) : null}
          {!isNew ? (
            <Button
              type="button"
              variant="outline"
              disabled={duplicateMutation.isPending}
              onClick={() => duplicateMutation.mutate()}
            >
              <Copy size={14} /> Duplicate
            </Button>
          ) : null}
          <Button type="button" variant="ghost" onClick={() => navigate("/settings")}>
            Cancel
          </Button>
          <Button type="submit" disabled={!canSave || saveMutation.isPending}>
            {saveMutation.isPending ? "Saving…" : "Save agent"}
          </Button>
        </div>
      </form>

      <Dialog open={confirming} onOpenChange={setConfirming}>
        <DialogContent
          title="Delete agent"
          description="Past discussions keep their role snapshots and messages."
        >
          <p className="text-sm">
            Delete <span className="font-semibold">{name}</span>?
          </p>
          <div className="mt-4 flex justify-end gap-2">
            <Button variant="ghost" onClick={() => setConfirming(false)}>
              Cancel
            </Button>
            <Button
              variant="danger"
              disabled={deleteMutation.isPending}
              onClick={() => deleteMutation.mutate()}
            >
              Delete agent
            </Button>
          </div>
        </DialogContent>
      </Dialog>
    </section>
  );
}
