import { ArrowLeft, Copy, PlugZap, Trash2 } from "lucide-react";
import { useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent } from "@/components/ui/dialog";
import { describeError, fieldErrors } from "@/lib/describeError";
import { presetById, presetRequirements } from "@/lib/providers";
import { useAgent, useRoleTemplates } from "@/lib/queries";
import type { Agent, AgentTestResult } from "@/lib/types";
import { formatDateTime } from "@/lib/utils";
import { AgentConnectionFields, AgentTuningFields } from "./AgentConnectionFields";
import {
  answerLengthProblem,
  emptyAgentForm,
  hydrateAgentForm,
  withProvider,
  type AgentForm,
} from "./agentForm";
import { AgentIdentityFields } from "./AgentIdentityFields";
import { AgentTestResultPanel } from "./AgentTestResultPanel";
import { useAgentActions } from "./useAgentActions";

export function AgentEditorPage() {
  const { agentId } = useParams();
  const isNew = !agentId || agentId === "new";
  const navigate = useNavigate();
  const agentQuery = useAgent(String(agentId));
  const rolesQuery = useRoleTemplates();
  const roles = rolesQuery.data ?? [];

  const [hydratedId, setHydratedId] = useState<string | null>(isNew ? "new" : null);
  const [form, setForm] = useState<AgentForm>(() => emptyAgentForm(isNew));
  const update = (patch: Partial<AgentForm>) => {
    setForm((current) => ({ ...current, ...patch }));
  };
  const [testResult, setTestResult] = useState<AgentTestResult | null>(null);
  // What the endpoint says it serves, filled by the connection test. Kept in state rather than on
  // the agent: it is a hint for the form, not part of the agent's configuration.
  const testModels = testResult?.models ?? [];
  const [confirming, setConfirming] = useState(false);

  // Fill the form from the loaded agent once per agent, while rendering rather than in an effect, so
  // the first paint already shows it (React: "adjusting state when a prop changes").
  const loaded: Agent | undefined = agentQuery.data;
  if (loaded && hydratedId !== loaded.id) {
    setForm((current) => hydrateAgentForm(current, loaded));
    setHydratedId(loaded.id);
  }

  const actions = useAgentActions({
    agentId,
    form,
    onTested: setTestResult,
    onDeleted: () => setConfirming(false),
  });
  // The inputs the last save was refused for, by the field the API named; the next save clears them.
  const invalid = new Set(fieldErrors(actions.save.error).map(({ field }) => field));

  if (!isNew && agentQuery.isLoading) {
    return <p className="text-sm text-[var(--muted-foreground)]">Loading agent…</p>;
  }
  if (!isNew && agentQuery.error) {
    return (
      <p role="alert" className="text-sm text-[var(--destructive)]">
        {describeError(agentQuery.error, "Agent unavailable.")}
      </p>
    );
  }

  const stored = agentQuery.data;
  const preset = presetById(form.providerId);
  const requirements = presetRequirements(
    preset ?? {
      id: "custom",
      label: "Custom",
      baseUrl: "",
      model: "",
      baseUrlFixed: false,
      requiresApiKey: false,
      requiresModel: false,
    },
  );
  const hasStoredKey = Boolean(stored?.has_api_key);
  const endpointLocked = form.connectionType === "openai_compatible" && requirements.endpointLocked;
  const keyMissing =
    form.connectionType === "openai_compatible" &&
    requirements.apiKey === "required" &&
    !form.noKey &&
    !form.apiKey.trim() &&
    !hasStoredKey;
  const modelMissing =
    form.connectionType === "openai_compatible" &&
    requirements.model === "required" &&
    !form.model.trim();
  // A preset that documents its cap refuses a longer answer here, before the provider does.
  const lengthProblem =
    form.connectionType === "openai_compatible" ? answerLengthProblem(form, preset) : null;
  const canSave = Boolean(
    form.name.trim() &&
    form.baseUrl.trim() &&
    (form.roleTemplateId || form.override.trim()) &&
    !keyMissing &&
    !modelMissing &&
    !lengthProblem,
  );

  return (
    <section className="flex max-w-3xl flex-col gap-6">
      <div>
        <button
          type="button"
          onClick={() => {
            void navigate("/settings");
          }}
          className="inline-flex items-center gap-1.5 text-xs text-[var(--muted-foreground)] hover:text-[var(--foreground)]"
        >
          <ArrowLeft size={14} /> Settings
        </button>
        <h1 className="mt-1 flex items-center gap-2 text-xl font-semibold">
          {isNew ? "New AI agent" : `Edit ${form.name || "agent"}`}
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
          if (canSave) actions.save.mutate();
        }}
      >
        <AgentIdentityFields form={form} onChange={update} roles={roles} invalid={invalid} />

        <div className="grid gap-4 sm:grid-cols-2">
          <AgentConnectionFields
            form={form}
            onChange={update}
            onProviderChange={(providerId) =>
              setForm((current) => withProvider(current, providerId))
            }
            preset={preset}
            requirements={requirements}
            endpointLocked={endpointLocked}
            testModels={testModels}
            stored={stored}
            invalid={invalid}
          />
          <AgentTuningFields
            form={form}
            onChange={update}
            invalid={invalid}
            lengthProblem={lengthProblem}
          />
        </div>

        {testResult ? <AgentTestResultPanel result={testResult} /> : null}
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
          <Button
            type="button"
            variant="outline"
            disabled={actions.test.isPending || !form.baseUrl.trim() || keyMissing}
            title={
              keyMissing
                ? "This provider needs a key before it can be tested"
                : !form.baseUrl.trim()
                  ? "Fill in the endpoint first"
                  : undefined
            }
            onClick={() => actions.test.mutate()}
          >
            <PlugZap size={14} /> {actions.test.isPending ? "Testing…" : "Test connection"}
          </Button>
          {!isNew ? (
            <Button
              type="button"
              variant="outline"
              disabled={actions.duplicate.isPending}
              onClick={() => actions.duplicate.mutate()}
            >
              <Copy size={14} /> Duplicate
            </Button>
          ) : null}
          <Button
            type="button"
            variant="ghost"
            onClick={() => {
              void navigate("/settings");
            }}
          >
            Cancel
          </Button>
          <Button type="submit" disabled={!canSave || actions.save.isPending}>
            {actions.save.isPending ? "Saving…" : "Save agent"}
          </Button>
        </div>
      </form>

      <Dialog open={confirming} onOpenChange={setConfirming}>
        <DialogContent
          title="Delete agent"
          description="Past discussions keep their role snapshots and messages."
        >
          <p className="text-sm">
            Delete <span className="font-semibold">{form.name}</span>?
          </p>
          <div className="mt-4 flex justify-end gap-2">
            <Button variant="ghost" onClick={() => setConfirming(false)}>
              Cancel
            </Button>
            <Button
              variant="danger"
              disabled={actions.remove.isPending}
              onClick={() => actions.remove.mutate()}
            >
              Delete agent
            </Button>
          </div>
        </DialogContent>
      </Dialog>
    </section>
  );
}
