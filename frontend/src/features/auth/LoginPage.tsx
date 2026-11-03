import { useState } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { Button } from "@/components/ui/button";
import { Field, Input } from "@/components/ui/input";
import { ApiError } from "@/lib/api";
import { useAuth } from "./useAuth";

export function LoginPage() {
  const { login } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const [username, setUsername] = useState("admin");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  const target = (location.state as { from?: string } | null)?.from ?? "/";

  async function handleSubmit(event: React.SubmitEvent<HTMLFormElement>) {
    event.preventDefault();
    setPending(true);
    setError(null);
    try {
      await login(username, password);
      void navigate(target, { replace: true });
    } catch (loginError) {
      setError(
        loginError instanceof ApiError ? loginError.message : "Unable to sign in right now.",
      );
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
      >
        <div>
          <div className="flex items-center gap-2">
            <h1 className="text-lg font-semibold text-[var(--foreground)]">Tralala</h1>
          </div>
          <p className="mt-1 text-xs text-[var(--muted-foreground)]">
            Self-hosted boards for humans and agents.
          </p>
        </div>
        <Field label="Username" htmlFor="username">
          <Input
            id="username"
            name="username"
            autoComplete="username"
            value={username}
            onChange={(event) => setUsername(event.target.value)}
            required
          />
        </Field>
        <Field label="Password" htmlFor="password">
          <Input
            id="password"
            name="password"
            type="password"
            autoComplete="current-password"
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            required
          />
        </Field>
        {error ? (
          <p role="alert" className="text-xs text-[var(--destructive)]">
            {error}
          </p>
        ) : null}
        <Button type="submit" disabled={pending}>
          {pending ? "Signing in…" : "Sign in"}
        </Button>
        <p className="text-[11px] leading-relaxed text-[var(--muted-foreground)]">
          First run uses the administrator credentials configured on the server. If none was
          configured, the server generated one and wrote it to
          <code> data/.bootstrap-password</code>.
        </p>
        <p className="text-[11px] text-[var(--muted-foreground)]">
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
