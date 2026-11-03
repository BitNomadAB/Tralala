import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { useToast } from "@/components/ui/useToast";
import { ApiError, api } from "@/lib/api";
import type { AgentTestResult } from "@/lib/types";
import { agentPayload, type AgentForm } from "./agentForm";

/** Save, connection test, duplicate and delete for the agent editor. */
export function useAgentActions({
  agentId,
  form,
  onTested,
  onDeleted,
}: {
  agentId: string | undefined;
  form: AgentForm;
  onTested: (result: AgentTestResult) => void;
  onDeleted: () => void;
}) {
  const isNew = !agentId || agentId === "new";
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const toast = useToast();
  const invalidate = () => queryClient.invalidateQueries({ queryKey: ["agents"] });

  const save = useMutation({
    mutationFn: () => {
      // "No key" on an existing agent has to clear a stored one, which the API spells
      // `clear_api_key`; a new agent simply never receives a key.
      const credentials = form.noKey
        ? isNew
          ? {}
          : { clear_api_key: true }
        : form.apiKey.trim()
          ? { api_key: form.apiKey.trim() }
          : {};
      const body = { ...agentPayload(form), ...credentials };
      return isNew ? api.createAgent(body) : api.updateAgent(agentId, body);
    },
    onSuccess: (agent) => {
      void invalidate();
      queryClient.setQueryData(["agent", agent.id], agent);
      toast.push({ title: "Agent saved", variant: "success" });
      void navigate("/settings");
    },
    onError: (error) => {
      toast.push({
        title: "Could not save agent",
        description: error instanceof ApiError ? error.message : undefined,
        variant: "error",
      });
    },
  });

  const test = useMutation({
    mutationFn: () => {
      const connection = {
        connection_type: form.connectionType,
        base_url: form.baseUrl.trim(),
        ...(form.model.trim() ? { model: form.model.trim() } : {}),
        ...(!form.noKey && form.apiKey.trim() ? { api_key: form.apiKey.trim() } : {}),
        // Explicit: omitting the key means "use the one stored on the agent".
        ...(form.noKey ? { no_api_key: true } : {}),
      };
      // A new agent has no row to test against, so the form asks the endpoint directly. Saving
      // first would put a configuration in the registry that nobody has proved works.
      return isNew
        ? api.probeAgent({ ...connection, timeout_seconds: Number(form.timeoutSeconds) || 30 })
        : api.testAgent(agentId, connection);
    },
    onSuccess: (result) => {
      onTested(result);
      void invalidate();
      void queryClient.invalidateQueries({ queryKey: ["agent", agentId] });
      toast.push({
        title: result.ok ? "Connection works" : "Connection failed",
        description: result.message,
        variant: result.ok ? "success" : "error",
      });
    },
    onError: (error) => {
      toast.push({
        title: "Test failed",
        description: error instanceof ApiError ? error.message : undefined,
        variant: "error",
      });
    },
  });

  const duplicate = useMutation({
    mutationFn: () => api.duplicateAgent(String(agentId)),
    onSuccess: (agent) => {
      void invalidate();
      toast.push({ title: "Agent duplicated", variant: "success" });
      void navigate(`/settings/agents/${agent.id}`);
    },
    onError: (error) => {
      toast.push({
        title: "Could not duplicate agent",
        description: error instanceof ApiError ? error.message : undefined,
        variant: "error",
      });
    },
  });

  const remove = useMutation({
    mutationFn: () => api.deleteAgent(String(agentId)),
    onSuccess: () => {
      void invalidate();
      onDeleted();
      toast.push({ title: "Agent deleted", variant: "success" });
      void navigate("/settings");
    },
    onError: (error) => {
      toast.push({
        title: "Could not delete agent",
        description: error instanceof ApiError ? error.message : undefined,
        variant: "error",
      });
    },
  });

  return { save, test, duplicate, remove };
}
