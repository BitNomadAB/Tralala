import { useMutation } from "@tanstack/react-query";
import { ShieldCheck } from "lucide-react";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent } from "@/components/ui/dialog";
import { HeldButton } from "@/components/ui/held-button";
import { Field, FieldMessage, Input } from "@/components/ui/input";
import { useFieldErrors } from "@/components/ui/useFieldErrors";
import { useToast } from "@/components/ui/useToast";
import { DECIDE_LABEL, DECIDE_SCOPE, DECIDE_WARNING } from "@/lib/agentAccess";
import { api, ApiError } from "@/lib/api";
import { describeError } from "@/lib/describeError";
import { fieldProblems, problemAt, type FieldProblem } from "@/lib/fieldProblems";
import type { Credential } from "@/lib/types";

/** The first scope checkbox: where focus goes when the scopes are what is wrong. */
const SCOPES_ID = "credential-scopes";
const SCOPES_ERROR_ID = "credential-scopes-error";
/** The right to decide in the editor, offered apart from the scopes with its warning. */
const DECIDE_ID = "credential-decide";
const DECIDE_WARNING_ID = "credential-decide-warning";
const DECIDE_ERROR_ID = "credential-decide-error";

/** The request fields of a new access, by the control that sends them, in the order they show. */
const ACCESS_CONTROLS = {
  name: "credential-name",
  scopes: SCOPES_ID,
  expires_in_days: "credential-expiry",
};

/** Where a refused access belongs: a scope the role may not grant, a missing expiry, a named field. */
function refusalProblems(error: unknown): FieldProblem[] {
  const named = fieldProblems(error, ACCESS_CONTROLS);
  if (named.length > 0 || !(error instanceof ApiError)) return named;
  if (error.code === "forbidden_scope") return [{ id: SCOPES_ID, message: error.message }];
  if (error.code === "editor_decisions_off" || error.code === "decide_needs_access") {
    return [{ id: DECIDE_ID, message: error.message }];
  }
  if (error.code === "expiry_required") {
    return [{ id: "credential-expiry", message: error.message }];
  }
  return [];
}

interface NewAccessProps {
  isAdmin: boolean;
  /** The scopes this person may grant. */
  scopeChoices: readonly string[];
  /** Whether the installation lets this person give the key the right to decide in the editor. */
  offerDecide: boolean;
  defaultExpiry: string;
  expiryHint: string;
  /** The created access, with its token shown once. */
  onIssued: (credential: Credential) => void;
}

/** The form inside the dialog; it mounts each time the dialog opens, so it starts afresh. */
function NewAccessForm({
  isAdmin,
  scopeChoices,
  offerDecide,
  defaultExpiry,
  expiryHint,
  onIssued,
  onCancel,
}: NewAccessProps & { onCancel: () => void }) {
  const toast = useToast();
  const [name, setName] = useState("");
  // Start from the smallest useful set instead of the first N scopes in the catalogue, and keep it
  // when the scope list is still loading: both are valid for every role.
  const [scopes, setScopes] = useState<string[]>(() => {
    const candidates = ["boards:read", "cards:read"];
    const known = scopeChoices.length > 0 ? scopeChoices : candidates;
    return candidates.filter((scope) => known.includes(scope));
  });
  const [expires, setExpires] = useState(defaultExpiry);
  // Never given by default: a person ticks it themselves, beside the warning.
  const [decide, setDecide] = useState(false);
  const fields = useFieldErrors();
  const scopesError = fields.errorOf(SCOPES_ID);
  const decideError = fields.errorOf(DECIDE_ID);

  const createMutation = useMutation({
    mutationFn: () =>
      api.createCredential({
        name: name.trim(),
        scopes: offerDecide && decide ? [...scopes, DECIDE_SCOPE] : scopes,
        expires_in_days: expires.trim() === "" ? undefined : Number(expires),
      }),
    onSuccess: onIssued,
    onError: (error) => {
      if (fields.report(refusalProblems(error))) return;
      toast.push({
        title: "Could not create the agent access",
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
          ...problemAt("credential-name", name.trim() ? null : "Name the agent access."),
          ...problemAt(SCOPES_ID, scopes.length > 0 ? null : "Choose at least one scope."),
        ];
        if (!fields.report(problems)) createMutation.mutate();
      }}
    >
      <Field
        label="Agent name"
        htmlFor="credential-name"
        hint="Name it after the machine that will hold the key."
        error={fields.errorOf("credential-name")}
      >
        <Input
          id="credential-name"
          value={name}
          onChange={(event) => {
            setName(event.target.value);
            fields.set("credential-name", null);
          }}
          required
          maxLength={200}
        />
      </Field>
      <fieldset
        className="flex flex-col gap-1.5"
        aria-describedby={scopesError ? SCOPES_ERROR_ID : undefined}
      >
        <legend className="text-xs font-medium uppercase tracking-wide text-[var(--muted-foreground)]">
          Scopes
        </legend>
        {scopeChoices.map((scope, position) => (
          <label key={scope} className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              {...(position === 0 ? { id: SCOPES_ID } : {})}
              checked={scopes.includes(scope)}
              onChange={(event) => {
                fields.set(SCOPES_ID, null);
                setScopes((current) =>
                  event.target.checked
                    ? [...current, scope]
                    : current.filter((value) => value !== scope),
                );
              }}
            />
            {scope}
          </label>
        ))}
        {scopesError ? <FieldMessage id={SCOPES_ERROR_ID}>{scopesError}</FieldMessage> : null}
      </fieldset>
      {offerDecide ? (
        <div className="flex flex-col gap-1">
          <label className="flex items-center gap-2 text-sm font-medium">
            <input
              type="checkbox"
              id={DECIDE_ID}
              checked={decide}
              aria-describedby={
                decideError ? `${DECIDE_ERROR_ID} ${DECIDE_WARNING_ID}` : DECIDE_WARNING_ID
              }
              aria-invalid={decideError ? true : undefined}
              onChange={(event) => {
                fields.set(DECIDE_ID, null);
                setDecide(event.target.checked);
              }}
            />
            {DECIDE_LABEL}
          </label>
          {decideError ? <FieldMessage id={DECIDE_ERROR_ID}>{decideError}</FieldMessage> : null}
          <p id={DECIDE_WARNING_ID} className="text-xs text-[var(--foreground)]">
            {DECIDE_WARNING}
          </p>
        </div>
      ) : null}
      <Field
        label="Expires in days"
        htmlFor="credential-expiry"
        hint={expiryHint}
        error={fields.errorOf("credential-expiry")}
      >
        <Input
          id="credential-expiry"
          type="number"
          min={isAdmin ? 0 : 1}
          max={3650}
          value={expires}
          onChange={(event) => {
            setExpires(event.target.value);
            fields.set("credential-expiry", null);
          }}
        />
      </Field>
      <div className="flex justify-end gap-2">
        <Button variant="ghost" onClick={onCancel}>
          Cancel
        </Button>
        <HeldButton type="submit" held={createMutation.isPending}>
          <ShieldCheck size={14} /> Create access
        </HeldButton>
      </div>
    </form>
  );
}

/** A person issues a key for an interaction agent on their own machine. */
export function NewAccessDialog({
  open,
  onOpenChange,
  ...props
}: NewAccessProps & { open: boolean; onOpenChange: (open: boolean) => void }) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        title="New interaction agent access"
        description="Scopes decide what the agent may do. Grant what it needs, nothing more."
      >
        <NewAccessForm {...props} onCancel={() => onOpenChange(false)} />
      </DialogContent>
    </Dialog>
  );
}
