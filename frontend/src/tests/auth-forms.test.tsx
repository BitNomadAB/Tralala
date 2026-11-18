import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { delay, http } from "msw";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it } from "vitest";
import { AuthProvider } from "@/features/auth/AuthProvider";
import { EnrolPage } from "@/features/auth/EnrolPage";
import { LoginPage } from "@/features/auth/LoginPage";
import { apiPath, failure } from "./msw/envelope";
import { server } from "./msw/server";
import { MEMBER, MEMBER_PASSWORD, memberSession } from "./msw/session";

let session: ReturnType<typeof memberSession>["state"];

beforeEach(() => {
  const member = memberSession();
  session = member.state;
  server.use(...member.handlers);
});

function renderAt(path: string) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  render(
    <QueryClientProvider client={client}>
      <AuthProvider>
        <MemoryRouter initialEntries={[path]}>
          <Routes>
            <Route path="/login" element={<LoginPage />} />
            <Route path="/enrol" element={<EnrolPage />} />
            <Route path="/" element={<p>Workspace</p>} />
          </Routes>
        </MemoryRouter>
      </AuthProvider>
    </QueryClientProvider>,
  );
  return userEvent.setup();
}

const sent = (request: string) => session.requests.filter((entry) => entry === request);

describe("the sign-in form", () => {
  it("starts with both fields empty, so nobody is handed a username", () => {
    renderAt("/login");

    expect(screen.getByLabelText("Username")).toHaveValue("");
    expect(screen.getByLabelText("Username")).toHaveAttribute("autocomplete", "username");
    expect(screen.getByLabelText("Password")).toHaveValue("");
  });

  it("keeps Sign in focusable while the sign-in runs, and sends it once", async () => {
    let attempts = 0;
    server.use(
      http.post(apiPath("/auth/login"), async () => {
        attempts += 1;
        await delay("infinite");
      }),
    );
    const user = renderAt("/login");

    await user.type(screen.getByLabelText("Username"), MEMBER.name);
    await user.type(screen.getByLabelText("Password"), MEMBER_PASSWORD);
    await user.click(screen.getByRole("button", { name: "Sign in" }));

    const button = await screen.findByRole("button", { name: "Signing in…" });
    expect(button).toHaveAttribute("aria-disabled", "true");
    expect(button).toHaveFocus();
    await user.click(button);
    expect(attempts).toBe(1);
  });

  it("keeps Sign in enabled and says a missing password under that field", async () => {
    const user = renderAt("/login");

    await user.type(screen.getByLabelText("Username"), MEMBER.name);
    const button = screen.getByRole("button", { name: "Sign in" });
    expect(button).toBeEnabled();
    await user.click(button);

    const password = screen.getByLabelText("Password");
    await waitFor(() => expect(password).toHaveFocus());
    expect(password).toHaveAttribute("aria-invalid", "true");
    expect(password).toHaveAccessibleDescription("Error: Enter your password.");
    expect(screen.getByLabelText("Username")).not.toHaveAttribute("aria-invalid");
    expect(sent("POST /auth/login")).toEqual([]);

    // Typing takes the error away again.
    await user.type(password, "x");
    expect(password).not.toHaveAttribute("aria-invalid");
    expect(password).not.toHaveAccessibleDescription();
  });

  it("moves focus to the first field that is missing", async () => {
    const user = renderAt("/login");

    await user.clear(screen.getByLabelText("Username"));
    await user.click(screen.getByRole("button", { name: "Sign in" }));

    await waitFor(() => expect(screen.getByLabelText("Username")).toHaveFocus());
    expect(screen.getByLabelText("Username")).toHaveAccessibleDescription(
      "Error: Enter your username.",
    );
    expect(screen.getByLabelText("Password")).toHaveAccessibleDescription(
      "Error: Enter your password.",
    );
  });

  it("says a refused sign-in under the password and moves focus there", async () => {
    const user = renderAt("/login");

    await user.type(screen.getByLabelText("Username"), MEMBER.name);
    await user.type(screen.getByLabelText("Password"), "not-my-password");
    await user.click(screen.getByRole("button", { name: "Sign in" }));

    const password = screen.getByLabelText("Password");
    await waitFor(() => expect(password).toHaveFocus());
    expect(password).toHaveAccessibleDescription("Error: The username or password is not right.");
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();

    await user.clear(password);
    await user.type(password, MEMBER_PASSWORD);
    await user.click(screen.getByRole("button", { name: "Sign in" }));
    expect(await screen.findByText("Workspace")).toBeInTheDocument();
  });

  it("says a failure that is about no field as an alert above the button", async () => {
    server.use(
      http.post(apiPath("/auth/login"), () => failure(503, "unavailable", "The server is busy")),
    );
    const user = renderAt("/login");

    await user.type(screen.getByLabelText("Username"), MEMBER.name);
    await user.type(screen.getByLabelText("Password"), MEMBER_PASSWORD);
    await user.click(screen.getByRole("button", { name: "Sign in" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("The server is busy");
    expect(screen.getByLabelText("Password")).not.toHaveAttribute("aria-invalid");
  });
});

describe("the invitation form", () => {
  it("shows the username the link names, for the person and their password manager", () => {
    renderAt("/enrol?token=invite-token&user=ada%20member");

    const username = screen.getByLabelText("Username");
    expect(username).toHaveValue("ada member");
    expect(username).toHaveAttribute("readonly");
    expect(username).toHaveAttribute("autocomplete", "username");
  });

  it("leaves the username out when the token came without a link", () => {
    renderAt("/enrol");

    expect(screen.queryByLabelText("Username")).not.toBeInTheDocument();
  });

  it("says a mismatch only once the repeat field is left, and drops it when they match", async () => {
    const user = renderAt("/enrol?token=invite-token");

    await user.type(screen.getByLabelText("Password"), "chosen-password-1");
    const repeat = screen.getByLabelText("Repeat password");
    await user.type(repeat, "chosen");
    expect(repeat).not.toHaveAttribute("aria-invalid");

    await user.tab();
    expect(repeat).toHaveAttribute("aria-invalid", "true");
    expect(repeat).toHaveAccessibleDescription("Error: The two passwords do not match.");

    await user.type(repeat, "-password-1");
    expect(repeat).not.toHaveAttribute("aria-invalid");
    expect(screen.getByRole("button", { name: "Set password and sign in" })).toBeEnabled();
  });

  it("checks every field on submit and moves focus to the first problem", async () => {
    const user = renderAt("/enrol");

    await user.type(screen.getByLabelText("Password"), "short");
    await user.click(screen.getByRole("button", { name: "Set password and sign in" }));

    const token = screen.getByLabelText("Invitation token");
    await waitFor(() => expect(token).toHaveFocus());
    expect(token).toHaveAccessibleDescription(
      "Error: Paste the invitation token. Filled in from the link; paste it here if you only received the code.",
    );
    expect(screen.getByLabelText("Password")).toHaveAccessibleDescription(
      "Error: Use at least 8 characters. At least 8 characters.",
    );
    expect(screen.getByLabelText("Repeat password")).toHaveAccessibleDescription(
      "Error: Repeat the password.",
    );
    expect(sent("POST /auth/enrol")).toEqual([]);
  });

  it("says a used link under the token", async () => {
    server.use(
      http.post(apiPath("/auth/enrol"), () =>
        failure(401, "invite_used", "This invitation link was already used"),
      ),
    );
    const user = renderAt("/enrol?token=invite-token");

    await user.type(screen.getByLabelText("Password"), "chosen-password-1");
    await user.type(screen.getByLabelText("Repeat password"), "chosen-password-1");
    await user.click(screen.getByRole("button", { name: "Set password and sign in" }));

    const token = screen.getByLabelText("Invitation token");
    await waitFor(() => expect(token).toHaveFocus());
    expect(token).toHaveAttribute("aria-invalid", "true");
    expect(token).toHaveAccessibleDescription(
      /^Error: This invitation link was already used\. Filled in from the link/,
    );
  });
});
