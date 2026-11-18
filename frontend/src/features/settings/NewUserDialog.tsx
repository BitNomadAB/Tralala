import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent } from "@/components/ui/dialog";
import { Field, Input, Select } from "@/components/ui/input";
import { useFieldErrors } from "@/components/ui/useFieldErrors";
import { useToast } from "@/components/ui/useToast";
import { api, ApiError } from "@/lib/api";
import { describeError } from "@/lib/describeError";
import {
  fieldProblems,
  MIN_PASSWORD_LENGTH,
  passwordProblem,
  problemAt,
  type FieldProblem,
} from "@/lib/fieldProblems";
import { ROLES, type Role } from "@/lib/types";

/** The request fields of a new user, by the control that sends them, in the order they show. */
const USER_CONTROLS = { name: "user-name", password: "user-password", role: "user-role" };

/**
 * Where a refused account belongs: a taken name (409) under the username, the password policy
 * (`validation_failed` naming no field) under the password, a field the server names under it.
 */
function newUserRefusal(error: unknown): FieldProblem[] {
  const named = fieldProblems(error, USER_CONTROLS);
  if (named.length > 0 || !(error instanceof ApiError)) return named;
  if (error.status === 409) return [{ id: "user-name", message: error.message }];
  if (error.code === "validation_failed") return [{ id: "user-password", message: error.message }];
  return [];
}

/** The form inside the dialog; it mounts each time the dialog opens, so it starts empty. */
function NewUserForm({ onDone }: { onDone: () => void }) {
  const queryClient = useQueryClient();
  const toast = useToast();
  const [name, setName] = useState("");
  const [password, setPassword] = useState("");
  const [role, setRole] = useState<Role>("member");
  const fields = useFieldErrors();

  const createMutation = useMutation({
    mutationFn: () => api.createUser({ name: name.trim(), password, role }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["users"] });
      toast.push({ title: "User created", variant: "success" });
      onDone();
    },
    onError: (error) => {
      if (fields.report(newUserRefusal(error))) return;
      toast.push({
        title: "Could not create the user",
        description: describeError(error, undefined),
        variant: "error",
      });
    },
  });

  return (
    <form
      className="flex flex-col gap-3"
      noValidate
      onSubmit={(event) => {
        event.preventDefault();
        const problems = [
          ...problemAt("user-name", name.trim() ? null : "Enter a username."),
          ...problemAt("user-password", passwordProblem(password)),
        ];
        if (!fields.report(problems)) createMutation.mutate();
      }}
    >
      <Field label="Username" htmlFor="user-name" error={fields.errorOf("user-name")}>
        <Input
          id="user-name"
          value={name}
          onChange={(event) => {
            setName(event.target.value);
            fields.set("user-name", null);
          }}
          required
          maxLength={100}
        />
      </Field>
      <Field
        label="Initial password"
        htmlFor="user-password"
        hint={`At least ${MIN_PASSWORD_LENGTH} characters.`}
        error={fields.errorOf("user-password")}
      >
        <Input
          id="user-password"
          type="password"
          autoComplete="new-password"
          minLength={MIN_PASSWORD_LENGTH}
          value={password}
          onChange={(event) => {
            setPassword(event.target.value);
            fields.set("user-password", null);
          }}
          required
        />
      </Field>
      <Field label="Role" htmlFor="user-role" error={fields.errorOf("user-role")}>
        <Select
          id="user-role"
          value={role}
          onChange={(event) =>
            setRole(ROLES.find((value) => value === event.target.value) ?? "member")
          }
        >
          {ROLES.map((value) => (
            <option key={value} value={value}>
              {value}
            </option>
          ))}
        </Select>
      </Field>
      <div className="flex justify-end gap-2">
        <Button variant="ghost" onClick={onDone}>
          Cancel
        </Button>
        <Button type="submit" disabled={createMutation.isPending}>
          Create user
        </Button>
      </div>
    </form>
  );
}

/** An administrator creates an account that can sign in right away. */
export function NewUserDialog({
  open,
  onOpenChange,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent title="New user" description="They can sign in right away.">
        <NewUserForm onDone={() => onOpenChange(false)} />
      </DialogContent>
    </Dialog>
  );
}
