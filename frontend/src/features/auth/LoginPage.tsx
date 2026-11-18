import { useState } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { usePageTitle } from "@/app/usePageTitle";
import { HeldButton } from "@/components/ui/held-button";
import { Field, Input } from "@/components/ui/input";
import { TralalaLogo } from "@/components/ui/tralala-logo";
import { useFieldErrors } from "@/components/ui/useFieldErrors";
import { ApiError } from "@/lib/api";
import { describeError } from "@/lib/describeError";
import { problemAt } from "@/lib/fieldProblems";
import { useAuth } from "./useAuth";

/** Said under the password when the server refuses the pair; it does not tell which one is wrong. */
const WRONG_CREDENTIALS = "The username or password is not right.";

export function LoginPage() {
  const { login } = useAuth();
  usePageTitle({ page: "login" });
  const navigate = useNavigate();
  const location = useLocation();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  // A refusal that is about no field (the server is down, too many attempts) is said above Sign in.
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
  const fields = useFieldErrors();

  const target = (location.state as { from?: string } | null)?.from ?? "/";

  async function handleSubmit(event: React.SubmitEvent<HTMLFormElement>) {
    event.preventDefault();
    // Sign in stays focusable while a sign-in runs (`aria-disabled`), so a second press waits here.
    if (pending) return;
    setError(null);
    const missing = [
      ...problemAt("username", username.trim() ? null : "Enter your username."),
      ...problemAt("password", password ? null : "Enter your password."),
    ];
    if (fields.report(missing)) return;
    setPending(true);
    try {
      await login(username, password);
      void navigate(target, { replace: true });
    } catch (loginError) {
      if (loginError instanceof ApiError && loginError.code === "invalid_credentials") {
        fields.report([{ id: "password", message: WRONG_CREDENTIALS }]);
      } else {
        setError(describeError(loginError, "Unable to sign in right now."));
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
        aria-label="Sign in"
        noValidate
      >
        <div>
          <div className="flex items-center gap-2.5">
            <TralalaLogo className="h-9" />
            <h1 className="text-lg font-semibold text-[var(--foreground)]">Tralala</h1>
          </div>
          <p className="mt-1 text-xs text-[var(--muted-foreground)]">
            Self-hosted boards for humans and agents.
          </p>
        </div>
        <Field label="Username" htmlFor="username" error={fields.errorOf("username")}>
          <Input
            id="username"
            name="username"
            autoComplete="username"
            value={username}
            onChange={(event) => {
              setUsername(event.target.value);
              fields.set("username", null);
            }}
            required
          />
        </Field>
        <Field label="Password" htmlFor="password" error={fields.errorOf("password")}>
          <Input
            id="password"
            name="password"
            type="password"
            autoComplete="current-password"
            value={password}
            onChange={(event) => {
              setPassword(event.target.value);
              fields.set("password", null);
            }}
            required
          />
        </Field>
        {error ? (
          <p role="alert" className="text-xs text-[var(--destructive)]">
            {error}
          </p>
        ) : null}
        <HeldButton type="submit" held={pending}>
          {pending ? "Signing in…" : "Sign in"}
        </HeldButton>
        <p className="text-xs leading-relaxed text-[var(--muted-foreground)]">
          First run uses the administrator credentials configured on the server. If none was
          configured, the server generated one and wrote it to
          <code> data/.bootstrap-password</code>.
        </p>
        <p className="text-xs text-[var(--muted-foreground)]">
          Got an invitation link? Open it directly, or{" "}
          <Link className="underline" to="/enrol">
            enter its token here
          </Link>
          .
        </p>
      </form>
    </main>
  );
}
