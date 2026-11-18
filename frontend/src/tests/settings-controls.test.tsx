import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { delay, http } from "msw";
import { useState, type ReactNode } from "react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { describe, expect, it } from "vitest";
import { ToastProvider } from "@/components/ui/toast";
import { AgentEditorPage } from "@/features/settings/AgentEditorPage";
import { AgentTestResultPanel } from "@/features/settings/AgentTestResultPanel";
import { AppearanceCard } from "@/features/settings/AppearanceCard";
import { CredentialRow } from "@/features/settings/CredentialRow";
import { credentialState } from "@/features/settings/credentialState";
import type { Credential } from "@/lib/types";
import type { ThemeKit, ThemeMode } from "@/themes/theme";
import { ThemeContext } from "@/themes/useTheme";
import { apiPath, ok } from "./msw/envelope";
import { server } from "./msw/server";

/** The theme as the provider keeps it, without the account it is saved to. */
function Theme({ children }: { children: ReactNode }) {
  const [mode, setMode] = useState<ThemeMode>("dark");
  const [kit, setKit] = useState<ThemeKit>("carenomad");
  return (
    <ThemeContext.Provider value={{ mode, kit, resolved: "dark", setMode, setKit }}>
      {children}
    </ThemeContext.Provider>
  );
}

const KEY: Credential = {
  id: "key-1",
  actor_id: "agent-1",
  actor_name: null,
  owner_actor_id: "user-1",
  owner_name: null,
  name: "laptop",
  scopes: ["boards:read"],
  created_at: "2026-11-01T09:00:00Z",
  expires_at: "2026-12-01T09:00:00Z",
  last_used_at: null,
  revoked_at: null,
};

function renderRow(credential: Credential) {
  render(
    <ul>
      <CredentialRow
        credential={credential}
        showOwner={false}
        rotating={false}
        revoking={false}
        hintId="hint"
        onRotate={() => undefined}
        onRevoke={() => undefined}
      />
    </ul>,
  );
}

describe("the appearance choices", () => {
  it("are two radio groups with one Tab stop each, moved and chosen with the arrow keys", async () => {
    render(
      <Theme>
        <AppearanceCard />
      </Theme>,
    );
    const user = userEvent.setup();
    const kits = screen.getByRole("radiogroup", { name: "Theme kit" });
    const careNomad = within(kits).getByRole("radio", { name: /^CareNomad/ });
    expect(careNomad).toBeChecked();
    expect(within(kits).getByRole("radio", { name: /^MatchMap/ })).toHaveAttribute(
      "tabindex",
      "-1",
    );

    await user.tab();
    expect(careNomad).toHaveFocus();
    await user.keyboard("{ArrowRight}");
    const matchMap = within(kits).getByRole("radio", { name: /^MatchMap/ });
    expect(matchMap).toHaveFocus();
    expect(matchMap).toBeChecked();
    expect(matchMap).toHaveAttribute("tabindex", "0");
    // The arrows wrap, and Up and Down move as well as Left and Right.
    await user.keyboard("{ArrowUp}{ArrowLeft}");
    expect(within(kits).getByRole("radio", { name: /^Classic/ })).toHaveFocus();
    expect(within(kits).getByRole("radio", { name: /^Classic/ })).toBeChecked();

    // Tab leaves the group for the next one, landing on its chosen radio.
    await user.tab();
    const modes = screen.getByRole("radiogroup", { name: "Theme mode" });
    expect(within(modes).getByRole("radio", { name: /^Dark/ })).toHaveFocus();
    await user.keyboard("{ArrowDown}");
    expect(within(modes).getByRole("radio", { name: /^Light/ })).toBeChecked();
  });
});

describe("an agent access key", () => {
  it("is active, expired or revoked, never active once past its expiry", () => {
    const now = new Date("2026-11-15T00:00:00Z").getTime();
    expect(credentialState(KEY, now)).toBe("active");
    expect(credentialState({ ...KEY, expires_at: null }, now)).toBe("active");
    expect(credentialState({ ...KEY, expires_at: "2026-11-01T00:00:00Z" }, now)).toBe("expired");
    expect(credentialState({ ...KEY, revoked_at: "2026-11-02T00:00:00Z" }, now)).toBe("revoked");
  });

  it("shows an expired key as expired", () => {
    renderRow({ ...KEY, expires_at: "2020-01-01T00:00:00Z" });
    expect(screen.getByText("expired", { exact: true })).toBeInTheDocument();
    expect(screen.queryByText("active", { exact: true })).not.toBeInTheDocument();
  });

  it("keeps a revoked key's buttons focusable, unavailable and described as revoked", () => {
    renderRow({ ...KEY, revoked_at: "2026-11-02T00:00:00Z" });
    for (const name of ["Rotate laptop", "Revoke laptop"]) {
      const button = screen.getByRole("button", { name, description: "revoked" });
      expect(button).toHaveAttribute("aria-disabled", "true");
      expect(button).toBeEnabled();
    }
  });
});

describe("the connection test", () => {
  it("speaks the summary only, and lets a keyboard scroll the raw answer", () => {
    render(
      <AgentTestResultPanel
        result={{
          ok: false,
          status: "http_400",
          message: "Model Not Exist",
          latency_ms: 12,
          models: ["a", "b"],
        }}
      />,
    );
    const status = screen.getByRole("status", { name: "Connection test result" });
    expect(status).toHaveTextContent("http_400 · 12 ms");
    expect(status).toHaveTextContent("Model Not Exist");
    expect(status).not.toHaveTextContent('"models"');
    const raw = screen.getByRole("group", { name: "Raw test result" });
    expect(raw).toHaveAttribute("tabindex", "0");
    expect(raw).toHaveTextContent('"status": "http_400"');
  });

  it("keeps Test connection focusable and says why it waits", async () => {
    server.use(
      http.get(apiPath("/role-templates"), () => ok([])),
      http.post(apiPath("/agents/test"), async () => {
        await delay("infinite");
      }),
    );
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={queryClient}>
        <ToastProvider>
          <MemoryRouter initialEntries={["/settings/agents/new"]}>
            <Routes>
              <Route path="/settings/agents/:agentId" element={<AgentEditorPage />} />
            </Routes>
          </MemoryRouter>
        </ToastProvider>
      </QueryClientProvider>,
    );
    const user = userEvent.setup();

    expect(
      screen.getByRole("button", {
        name: "Test connection",
        description: "Fill in the endpoint first.",
      }),
    ).toHaveAttribute("aria-disabled", "true");
    expect(screen.getByRole("link", { name: "Settings" })).toHaveAttribute("href", "/settings");

    await user.type(screen.getByLabelText("API base URL"), "http://127.0.0.1:8080/v1");
    const test = screen.getByRole("button", { name: "Test connection" });
    expect(test).not.toHaveAttribute("aria-disabled");
    await user.click(test);
    expect(
      await screen.findByRole("button", { name: "Test connection", description: "Testing…" }),
    ).toHaveFocus();
  });
});
