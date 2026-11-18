import { useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { usePageTitle } from "@/app/usePageTitle";
import { Button } from "@/components/ui/button";
import { Field, Input } from "@/components/ui/input";
import { useFieldErrors } from "@/components/ui/useFieldErrors";
import { api, ApiError } from "@/lib/api";
import { describeError } from "@/lib/describeError";
import {
  confirmationProblem,
  MIN_PASSWORD_LENGTH,
  passwordProblem,
  problemAt,
  type FieldProblem,
} from "@/lib/fieldProblems";
import { useAuth } from "./useAuth";

/** The refusals that are about the token: the link is wrong, used or old. */
const TOKEN_REFUSALS: ReadonlySet<string> = new Set([
  "invite_invalid",
  "invite_used",
  "invite_expired",
]);

/**
 * Where a refusal of the invitation belongs: the token's own refusals under the token, the
 * password policy (`validation_failed`) under the password, anything else nowhere.
 */
function refusalProblems(error: unknown): FieldProblem[] {
  if (!(error instanceof ApiError)) return [];
  if (TOKEN_REFUSALS.has(error.code)) return [{ id: "enrol-token", message: error.message }];
  if (error.code === "validation_failed") {
    return [{ id: "enrol-password", message: error.message }];
  }
  return [];
}

/**
 * Public page behind an invitation link. The token is single use: it sets the password and signs the
 * person in, so no administrator ever has to know that password. A token can also be typed by hand
 * when the link only arrived as text.
 */
export function EnrolPage() {
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const { refresh } = useAuth();
  usePageTitle({ page: "enrol" });
  const [token, setToken] = useState(params.get("token") ?? "");
  // The invitation link names the account, so the person and their password manager see which
  // username the new password belongs to; a token typed by hand comes without it.
  const username = params.get("user") ?? "";
  const [password, setPassword] = useState("");
  const [confirmation, setConfirmation] = useState("");
  // A refusal about no field (a disabled account, the server is down) is said above the button.
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
  const fields = useFieldErrors();

  // A mismatch is said once the person has left the second field, or on submit, never while they
  // are still typing it; once said, it goes away as soon as the two match.
  function checkConfirmation(nextPassword: string, nextConfirmation: string, leaving: boolean) {
    if (!leaving && !fields.errorOf("enrol-confirmation")) return;
    if (leaving && nextConfirmation === "") return;
    fields.set("enrol-confirmation", confirmationProblem(nextPassword, nextConfirmation));
  }

  async function handleSubmit(event: React.SubmitEvent<HTMLFormElement>) {
    event.preventDefault();
    // The button stays focusable while the request runs (`aria-disabled`); a second press waits.
    if (pending) return;
    setError(null);
    const problems = [
      ...problemAt("enrol-token", token.trim() ? null : "Paste the invitation token."),
      ...problemAt("enrol-password", passwordProblem(password)),
      ...problemAt("enrol-confirmation", confirmationProblem(password, confirmation)),
    ];
    if (fields.report(problems)) return;
    setPending(true);
    try {
      await api.enrol(token.trim(), password);
      await refresh();
      void navigate("/", { replace: true });
    } catch (enrolError) {
      if (!fields.report(refusalProblems(enrolError))) {
        setError(describeError(enrolError, "Unable to use this invitation right now."));
      }
    } finally {
      setPending(false);
    }
  }

  return (
    <main className="relative flex min-h-screen items-center justify-center px-4">
      <form
        onSubmit={(event) => {
          void handleSubmit(event);
        }}
        className="card-surface flex w-full max-w-sm flex-col gap-4 p-7"
        aria-label="Accept invitation"
        noValidate
      >
        <div>
          <h1 className="text-lg font-semibold text-[var(--foreground)]">Choose your password</h1>
          <p className="mt-1 text-xs text-[var(--muted-foreground)]">
            An invitation is single use. Once you set a password you are signed in.
          </p>
        </div>
        <Field
          label="Invitation token"
          htmlFor="enrol-token"
          hint="Filled in from the link; paste it here if you only received the code."
          error={fields.errorOf("enrol-token")}
        >
          <Input
            id="enrol-token"
            name="token"
            value={token}
            onChange={(event) => {
              setToken(event.target.value);
              fields.set("enrol-token", null);
            }}
            autoComplete="one-time-code"
            required
          />
        </Field>
        {username ? (
          <Field label="Username" htmlFor="enrol-username" hint="You sign in with this name.">
            <Input
              id="enrol-username"
              name="username"
              autoComplete="username"
              value={username}
              readOnly
            />
          </Field>
        ) : null}
        <Field
          label="Password"
          htmlFor="enrol-password"
          hint={`At least ${MIN_PASSWORD_LENGTH} characters.`}
          error={fields.errorOf("enrol-password")}
        >
          <Input
            id="enrol-password"
            name="password"
            type="password"
            autoComplete="new-password"
            minLength={MIN_PASSWORD_LENGTH}
            value={password}
            onChange={(event) => {
              setPassword(event.target.value);
              fields.set("enrol-password", null);
              checkConfirmation(event.target.value, confirmation, false);
            }}
            required
          />
        </Field>
        <Field
          label="Repeat password"
          htmlFor="enrol-confirmation"
          error={fields.errorOf("enrol-confirmation")}
        >
          <Input
            id="enrol-confirmation"
            name="confirmation"
            type="password"
            autoComplete="new-password"
            minLength={MIN_PASSWORD_LENGTH}
            value={confirmation}
            onChange={(event) => {
              setConfirmation(event.target.value);
              checkConfirmation(password, event.target.value, false);
            }}
            onBlur={() => checkConfirmation(password, confirmation, true)}
            required
          />
        </Field>
        {error ? (
          <p role="alert" className="text-xs text-[var(--destructive)]">
            {error}
          </p>
        ) : null}
        <Button type="submit" aria-disabled={pending ? true : undefined}>
          {pending ? "Saving…" : "Set password and sign in"}
        </Button>
        <Link className="text-xs underline" to="/login">
          I already have a password
        </Link>
      </form>
    </main>
  );
}
