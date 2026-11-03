import { useMutation, useQueryClient } from "@tanstack/react-query";
import { ShieldCheck } from "lucide-react";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Field, Input } from "@/components/ui/input";
import { useToast } from "@/components/ui/useToast";
import { ApiError, api } from "@/lib/api";

export function SecurityCard() {
  const queryClient = useQueryClient();
  const toast = useToast();
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [confirm, setConfirm] = useState("");

  const mutation = useMutation({
    mutationFn: () => api.changePassword(current, next),
    onSuccess: () => {
      toast.push({
        title: "Password changed",
        description: "Every session was signed out. Sign in again with the new password.",
        variant: "success",
      });
      queryClient.clear();
      queryClient.setQueryData(["me"], null);
    },
    onError: (error) => {
      toast.push({
        title: "Could not change the password",
        description: error instanceof ApiError ? error.message : undefined,
        variant: "error",
      });
    },
  });

  const mismatch = confirm.length > 0 && confirm !== next;

  return (
    <form
      className="card-surface p-5"
      onSubmit={(event) => {
        event.preventDefault();
        if (!mismatch) mutation.mutate();
      }}
    >
      <h2 className="text-sm font-semibold">Your password</h2>
      <p className="mt-1 text-xs text-[var(--muted-foreground)]">
        Changing it signs out every device, including this one.
      </p>
      <div className="mt-3 grid gap-3 sm:grid-cols-3">
        <Field label="Current password" htmlFor="current-password">
          <Input
            id="current-password"
            type="password"
            autoComplete="current-password"
            value={current}
            onChange={(event) => setCurrent(event.target.value)}
            required
          />
        </Field>
        <Field label="New password" htmlFor="new-password" hint="At least 8 characters.">
          <Input
            id="new-password"
            type="password"
            autoComplete="new-password"
            minLength={8}
            value={next}
            onChange={(event) => setNext(event.target.value)}
            required
          />
        </Field>
        <Field
          label="Repeat new password"
          htmlFor="repeat-password"
          hint={mismatch ? "The passwords do not match." : undefined}
        >
          <Input
            id="repeat-password"
            type="password"
            autoComplete="new-password"
            value={confirm}
            onChange={(event) => setConfirm(event.target.value)}
            required
          />
        </Field>
      </div>
      <div className="mt-3 flex justify-end">
        <Button
          type="submit"
          size="sm"
          disabled={mutation.isPending || next.length < 8 || mismatch || !current}
        >
          <ShieldCheck size={14} /> Change password
        </Button>
      </div>
    </form>
  );
}
