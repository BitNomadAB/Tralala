import { useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { Button } from "@/components/ui/button";
import { Field, Input } from "@/components/ui/input";
import { api } from "@/lib/api";
import { describeError } from "@/lib/describeError";
import { useAuth } from "./useAuth";

/**
 * Public page behind an invitation link. The token is single use: it sets the password and signs the
 * person in, so no administrator ever has to know that password. A token can also be typed by hand
 * when the link only arrived as text.
 */
export function EnrolPage() {
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const { refresh } = useAuth();
  const [token, setToken] = useState(params.get("token") ?? "");
  const [password, setPassword] = useState("");
  const [confirmation, setConfirmation] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  const mismatch = confirmation.length > 0 && confirmation !== password;
  const ready = token.trim().length > 0 && password.length >= 8 && password === confirmation;

  async function handleSubmit(event: React.SubmitEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!ready) return;
    setPending(true);
    setError(null);
    try {
      await api.enrol(token.trim(), password);
      await refresh();
      void navigate("/", { replace: true });
    } catch (enrolError) {
      setError(describeError(enrolError, "Unable to use this invitation right now."));
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
        >
          <Input
            id="enrol-token"
            name="token"
            value={token}
            onChange={(event) => setToken(event.target.value)}
            autoComplete="one-time-code"
            required
          />
        </Field>
        <Field label="Password" htmlFor="enrol-password" hint="At least 8 characters.">
          <Input
            id="enrol-password"
            name="password"
            type="password"
            autoComplete="new-password"
            minLength={8}
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            required
          />
        </Field>
        <Field label="Repeat password" htmlFor="enrol-confirmation">
          <Input
            id="enrol-confirmation"
            name="confirmation"
            type="password"
            autoComplete="new-password"
            minLength={8}
            value={confirmation}
            onChange={(event) => setConfirmation(event.target.value)}
            required
          />
        </Field>
        {mismatch ? (
          <p role="alert" className="text-xs text-[var(--destructive)]">
            The two passwords do not match.
          </p>
        ) : null}
        {error ? (
          <p role="alert" className="text-xs text-[var(--destructive)]">
            {error}
          </p>
        ) : null}
        <Button type="submit" disabled={!ready || pending}>
          {pending ? "Saving…" : "Set password and sign in"}
        </Button>
        <Link className="text-[11px] underline" to="/login">
          I already have a password
        </Link>
      </form>
    </main>
  );
}
