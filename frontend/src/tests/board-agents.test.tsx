import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { generationAgents } from "@/lib/boardAgents";
import type { Agent } from "@/lib/types";

function agent(overrides: Partial<Agent> & Pick<Agent, "id" | "name">): Agent {
  return {
    description: "",
    role_template_id: null,
    role_template_name: null,
    role_template_scope: "board",
    role_template_updated_at: null,
    has_role_override: false,
    connection_type: "openai_compatible",
    base_url: null,
    model: null,
    enabled: true,
    has_api_key: false,
    api_key_hint: null,
    created_at: "2026-11-01T00:00:00Z",
    updated_at: "2026-11-01T00:00:00Z",
    ...overrides,
  } as Agent;
}

describe("generationAgents", () => {
  it("offers every enabled generator when the board lists none", () => {
    const result = generationAgents(
      [
        agent({ id: "b", name: "Beta" }),
        agent({ id: "a", name: "Alpha" }),
        agent({ id: "off", name: "Off", enabled: false }),
        agent({ id: "a2a", name: "Remote", connection_type: "a2a" }),
      ],
      [],
    );
    expect(result.restrictedToBoard).toBe(false);
    expect(result.agents.map((entry) => entry.name)).toEqual(["Alpha", "Beta"]);
  });

  it("narrows the list to the board's agents", () => {
    const result = generationAgents(
      [
        agent({ id: "a", name: "Alpha" }),
        agent({ id: "b", name: "Beta" }),
        agent({ id: "c", name: "Gamma" }),
      ],
      ["c", "a"],
    );
    expect(result.restrictedToBoard).toBe(true);
    expect(result.agents.map((entry) => entry.name)).toEqual(["Alpha", "Gamma"]);
  });

  it("keeps a board agent that cannot generate out of the choice", () => {
    const result = generationAgents(
      [agent({ id: "a", name: "Alpha", enabled: false }), agent({ id: "b", name: "Beta" })],
      ["a"],
    );
    expect(result.restrictedToBoard).toBe(true);
    expect(result.agents).toEqual([]);
  });

  it("never offers an organisation profile for a Loop", () => {
    const result = generationAgents(
      [
        agent({ id: "coord", name: "Coordinator", role_template_scope: "organisation" }),
        agent({ id: "board", name: "Board agent" }),
      ],
      [],
    );
    expect(result.agents.map((entry) => entry.name)).toEqual(["Board agent"]);
    expect(result.restrictedToBoard).toBe(false);
  });

  it("treats a missing board as unrestricted", () => {
    const result = generationAgents([agent({ id: "a", name: "Alpha" })], undefined);
    expect(result.restrictedToBoard).toBe(false);
    expect(result.agents).toHaveLength(1);
  });
});

describe("screen smoke", () => {
  it("renders nothing surprising for an empty agent list", () => {
    render(<p>{generationAgents([], []).agents.length}</p>);
    expect(screen.getByText("0")).toBeInTheDocument();
  });
});
