import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent } from "@/components/ui/dialog";
import { HeldButton } from "@/components/ui/held-button";
import { Field, Input } from "@/components/ui/input";
import { useFieldErrors } from "@/components/ui/useFieldErrors";
import { useToast } from "@/components/ui/useToast";
import { api, ApiError } from "@/lib/api";
import { describeError } from "@/lib/describeError";
import { MIN_PASSWORD_LENGTH, passwordProblem, problemAt } from "@/lib/fieldProblems";
import type { UserAccount } from "@/lib/types";

/** The form inside the dialog; it mounts each time the dialog opens, so it starts empty. */
function ResetPasswordForm({ user, onDone }: { user: UserAccount; onDone: () => void }) {
  const queryClient = useQueryClient();
  const toast = useToast();
  const [password, setPassword] = useState("");
  const fields = useFieldErrors();

  const resetMutation = useMutation({
    mutationFn: () => api.resetUserPassword(user.id, password),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["users"] });
      toast.push({ title: "Password reset", description: "Existing sessions were signed out." });
      onDone();
    },
    onError: (error) => {
      // The password policy refuses with `validation_failed`; that is about the one field here.
      if (error instanceof ApiError && error.code === "validation_failed") {
        fields.report([{ id: "reset-password", message: error.message }]);
        return;
      }
      toast.push({
        title: "Could not reset the password",
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
        if (!fields.report(problemAt("reset-password", passwordProblem(password)))) {
          resetMutation.mutate();
        }
      }}
    >
      <Field
        label="New password"
        htmlFor="reset-password"
        hint={`At least ${MIN_PASSWORD_LENGTH} characters.`}
        error={fields.errorOf("reset-password")}
      >
        <Input
          id="reset-password"
          type="password"
          autoComplete="new-password"
          minLength={MIN_PASSWORD_LENGTH}
          value={password}
          onChange={(event) => {
            setPassword(event.target.value);
            fields.set("reset-password", null);
          }}
          required
        />
      </Field>
      <div className="flex justify-end gap-2">
        <Button variant="ghost" onClick={onDone}>
          Cancel
        </Button>
        <HeldButton type="submit" held={resetMutation.isPending}>
          Reset password
        </HeldButton>
      </div>
    </form>
  );
}

/** An administrator sets a new password for someone; every session of theirs ends. */
export function ResetPasswordDialog({
  user,
  onClose,
}: {
  user: UserAccount | null;
  onClose: () => void;
}) {
  return (
    <Dialog open={user !== null} onOpenChange={(open) => !open && onClose()}>
      <DialogContent
        title={`Reset password for ${user?.name ?? ""}`}
        description="They are signed out everywhere and must use the new password."
      >
        {user ? <ResetPasswordForm user={user} onDone={onClose} /> : null}
      </DialogContent>
    </Dialog>
  );
}
