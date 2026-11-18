import { useMutation } from "@tanstack/react-query";
import { ShieldCheck } from "lucide-react";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Field, Input } from "@/components/ui/input";
import { useFieldErrors } from "@/components/ui/useFieldErrors";
import { useToast } from "@/components/ui/useToast";
import { useAuth } from "@/features/auth/useAuth";
import { api, ApiError } from "@/lib/api";
import { describeError } from "@/lib/describeError";
import {
  confirmationProblem,
  MIN_PASSWORD_LENGTH,
  passwordProblem,
  problemAt,
  type FieldProblem,
} from "@/lib/fieldProblems";

/**
 * Where a refused change belongs: a wrong current password under that field, the password policy
 * (`validation_failed`) under the new one, anything else in a toast.
 */
function refusalProblems(error: unknown): FieldProblem[] {
  if (!(error instanceof ApiError)) return [];
  if (error.code === "invalid_credentials") {
    return [{ id: "current-password", message: error.message }];
  }
  if (error.code === "validation_failed") return [{ id: "new-password", message: error.message }];
  return [];
}

export function SecurityCard() {
  const { signOutLocally } = useAuth();
  const toast = useToast();
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [confirm, setConfirm] = useState("");
  const fields = useFieldErrors();

  const mutation = useMutation({
    mutationFn: () => api.changePassword(current, next),
    onSuccess: () => {
      toast.push({
        title: "Password changed",
        description: "Every session was signed out. Sign in again with the new password.",
        variant: "success",
      });
      // The server ended every session, this one included.
      signOutLocally();
    },
    onError: (error) => {
      if (fields.report(refusalProblems(error))) return;
      toast.push({
        title: "Could not change the password",
        description: describeError(error, undefined),
        variant: "error",
      });
    },
  });

  // A mismatch is said once the person has left the repeat field, or on submit; once said, it goes
  // away as soon as the two match.
  function checkConfirmation(nextPassword: string, nextConfirmation: string, leaving: boolean) {
    if (!leaving && !fields.errorOf("repeat-password")) return;
    if (leaving && nextConfirmation === "") return;
    fields.set("repeat-password", confirmationProblem(nextPassword, nextConfirmation));
  }

  return (
    <form
      className="card-surface p-5"
      noValidate
      onSubmit={(event) => {
        event.preventDefault();
        const problems = [
          ...problemAt("current-password", current ? null : "Enter your current password."),
          ...problemAt("new-password", passwordProblem(next)),
          ...problemAt("repeat-password", confirmationProblem(next, confirm)),
        ];
        if (!fields.report(problems)) mutation.mutate();
      }}
    >
      <h2 className="text-sm font-semibold">Your password</h2>
      <p className="mt-1 text-xs text-[var(--muted-foreground)]">
        Changing it signs out every device, including this one.
      </p>
      <div className="mt-3 grid gap-3 sm:grid-cols-3">
        <Field
          label="Current password"
          htmlFor="current-password"
          error={fields.errorOf("current-password")}
        >
          <Input
            id="current-password"
            type="password"
            autoComplete="current-password"
            value={current}
            onChange={(event) => {
              setCurrent(event.target.value);
              fields.set("current-password", null);
            }}
            required
          />
        </Field>
        <Field
          label="New password"
          htmlFor="new-password"
          hint={`At least ${MIN_PASSWORD_LENGTH} characters.`}
          error={fields.errorOf("new-password")}
        >
          <Input
            id="new-password"
            type="password"
            autoComplete="new-password"
            minLength={MIN_PASSWORD_LENGTH}
            value={next}
            onChange={(event) => {
              setNext(event.target.value);
              fields.set("new-password", null);
              checkConfirmation(event.target.value, confirm, false);
            }}
            required
          />
        </Field>
        <Field
          label="Repeat new password"
          htmlFor="repeat-password"
          error={fields.errorOf("repeat-password")}
        >
          <Input
            id="repeat-password"
            type="password"
            autoComplete="new-password"
            value={confirm}
            onChange={(event) => {
              setConfirm(event.target.value);
              checkConfirmation(next, event.target.value, false);
            }}
            onBlur={() => checkConfirmation(next, confirm, true)}
            required
          />
        </Field>
      </div>
      <div className="mt-3 flex justify-end">
        <Button type="submit" size="sm" disabled={mutation.isPending}>
          <ShieldCheck size={14} /> Change password
        </Button>
      </div>
    </form>
  );
}
