import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Bot, Plus, Power, Trash2 } from "lucide-react";
import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent } from "@/components/ui/dialog";
import { useToast } from "@/components/ui/useToast";
import { api } from "@/lib/api";
import { describeError } from "@/lib/describeError";
import { providerLabelFor } from "@/lib/providers";
import { useAgents } from "@/lib/queries";
import type { Agent } from "@/lib/types";
import { formatDateTime } from "@/lib/utils";

function testTone(agent: Agent): "success" | "danger" | "neutral" {
  if (!agent.last_test_status) return "neutral";
  return agent.last_test_status === "connected" ? "success" : "danger";
}

/** What the last connection test found about tool calling; nothing before the first test. */
function ToolCalling({ agent }: { agent: Agent }) {
  if (!agent.last_tested_at) return null;
  return agent.supports_tools ? (
    <span title="A run lets this agent read the board's repositories itself">
      reads repositories with tools
    </span>
  ) : (
    <span title="A run sends this agent a fixed snapshot of the board's repositories">
      no tool calling
    </span>
  );
}

export function AgentsCard() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const toast = useToast();
  const { data: agents = [], isLoading } = useAgents();
  const [deleting, setDeleting] = useState<Agent | null>(null);

  const invalidate = () => queryClient.invalidateQueries({ queryKey: ["agents"] });

  const toggleMutation = useMutation({
    mutationFn: (agent: Agent) => api.updateAgent(agent.id, { enabled: !agent.enabled }),
    onSuccess: (agent) => {
      void invalidate();
      toast.push({
        title: agent.enabled ? "Agent enabled" : "Agent disabled",
        variant: "success",
      });
    },
    onError: (error) => {
      toast.push({
        title: "Could not update agent",
        description: describeError(error, undefined),
        variant: "error",
      });
    },
  });

  const deleteMutation = useMutation({
    mutationFn: (agent: Agent) => api.deleteAgent(agent.id),
    onSuccess: () => {
      void invalidate();
      setDeleting(null);
      toast.push({ title: "Agent deleted", variant: "success" });
    },
    onError: (error) => {
      toast.push({
        title: "Could not delete agent",
        description: describeError(error, undefined),
        variant: "error",
      });
    },
  });

  return (
    <div className="card-surface p-5">
      <div className="flex flex-wrap items-center gap-2">
        <h2 className="text-sm font-semibold">AI agents</h2>
        <Button
          size="sm"
          className="ml-auto"
          onClick={() => {
            void navigate("/settings/agents/new");
          }}
        >
          <Plus size={14} /> New agent
        </Button>
      </div>
      <p className="mt-1 text-xs text-[var(--muted-foreground)]">
        Agent identities with their own model connection and role assignment. Credentials are
        encrypted on the server and never shown again after saving.
      </p>

      <div className="mt-3 max-h-80 overflow-y-auto rounded-lg border border-[var(--border)]">
        {isLoading ? (
          <p className="p-3 text-xs text-[var(--muted-foreground)]">Loading agents…</p>
        ) : agents.length === 0 ? (
          <p className="p-3 text-xs text-[var(--muted-foreground)]">
            No agents yet. Create one to connect a local model or an A2A agent.
          </p>
        ) : (
          <ul className="divide-y divide-[var(--border)]">
            {agents.map((agent) => (
              <li key={agent.id} className="flex items-start gap-3 p-3">
                <div className="min-w-0 flex-1">
                  <p className="flex flex-wrap items-center gap-1.5 text-sm font-medium">
                    <Bot size={14} className="shrink-0 text-[var(--muted-foreground)]" />
                    <span className="truncate">{agent.name}</span>
                    <Badge tone={agent.enabled ? "success" : "neutral"}>
                      {agent.enabled ? "enabled" : "disabled"}
                    </Badge>
                    {agent.has_role_override ? <Badge tone="brand">override</Badge> : null}
                    {agent.role_template_scope === "organisation" ? (
                      <Badge tone="brand">organisation</Badge>
                    ) : null}
                  </p>
                  <p className="mt-1 text-[11px] text-[var(--muted-foreground)]">
                    {agent.role_template_name ?? "No role"} ·{" "}
                    {providerLabelFor(agent.base_url) ??
                      (agent.connection_type === "a2a" ? "A2A" : "OpenAI-compatible")}{" "}
                    · {agent.model ?? "no model"} · {agent.base_url}
                  </p>
                  <p className="mt-1 flex flex-wrap items-center gap-1.5 text-[11px] text-[var(--muted-foreground)]">
                    <Badge tone={testTone(agent)}>{agent.last_test_status ?? "not tested"}</Badge>
                    {agent.last_tested_at ? (
                      <span>tested {formatDateTime(agent.last_tested_at)}</span>
                    ) : null}
                    {agent.has_api_key ? <span>key {agent.api_key_hint}</span> : null}
                    <ToolCalling agent={agent} />
                  </p>
                </div>
                <div className="flex shrink-0 items-center gap-1">
                  <Button
                    size="sm"
                    variant="secondary"
                    aria-label={`Edit ${agent.name}`}
                    onClick={() => {
                      void navigate(`/settings/agents/${agent.id}`);
                    }}
                  >
                    Edit
                  </Button>
                  <Button
                    size="icon"
                    variant="ghost"
                    title={agent.enabled ? "Disable agent" : "Enable agent"}
                    aria-label={`${agent.enabled ? "Disable" : "Enable"} ${agent.name}`}
                    onClick={() => toggleMutation.mutate(agent)}
                  >
                    <Power size={14} />
                  </Button>
                  <Button
                    size="icon"
                    variant="ghost"
                    title="Delete agent"
                    aria-label={`Delete ${agent.name}`}
                    onClick={() => setDeleting(agent)}
                  >
                    <Trash2 size={14} />
                  </Button>
                </div>
              </li>
            ))}
          </ul>
        )}
      </div>

      <Dialog open={Boolean(deleting)} onOpenChange={(open) => !open && setDeleting(null)}>
        <DialogContent
          title="Delete agent"
          description="Past discussions keep their role snapshots and messages."
        >
          <p className="text-sm">
            Delete <span className="font-semibold">{deleting?.name}</span>?
          </p>
          <div className="mt-4 flex justify-end gap-2">
            <Button variant="ghost" onClick={() => setDeleting(null)}>
              Cancel
            </Button>
            <Button
              variant="danger"
              disabled={deleteMutation.isPending}
              onClick={() => deleting && deleteMutation.mutate(deleting)}
            >
              Delete agent
            </Button>
          </div>
        </DialogContent>
      </Dialog>
    </div>
  );
}
