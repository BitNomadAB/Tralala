import { Wand2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Field, Input, Select, Textarea } from "@/components/ui/input";
import type { RoleTemplate } from "@/lib/types";
import { randomName, type AgentForm } from "./agentForm";

/** Name, role template, description and the role prompt override. */
export function AgentIdentityFields({
  form,
  onChange,
  roles,
}: {
  form: AgentForm;
  onChange: (patch: Partial<AgentForm>) => void;
  roles: RoleTemplate[];
}) {
  return (
    <>
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="Agent name" htmlFor="agent-name">
          <div className="flex gap-1.5">
            <Input
              id="agent-name"
              value={form.name}
              onChange={(event) => onChange({ name: event.target.value })}
              required
              maxLength={200}
            />
            <Button
              type="button"
              variant="outline"
              title="Generate random name"
              aria-label="Generate random name"
              onClick={() => onChange({ name: randomName() })}
            >
              <Wand2 size={14} />
            </Button>
          </div>
        </Field>
        <Field
          label="Role template"
          htmlFor="agent-role"
          hint="Applied to future discussions only."
        >
          <Select
            id="agent-role"
            value={form.roleTemplateId}
            onChange={(event) => onChange({ roleTemplateId: event.target.value })}
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
          value={form.description}
          onChange={(event) => onChange({ description: event.target.value })}
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
          value={form.override}
          onChange={(event) => onChange({ override: event.target.value })}
          maxLength={20000}
        />
      </Field>
    </>
  );
}
