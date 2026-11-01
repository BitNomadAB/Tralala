import { describe, expect, it } from "vitest";
import { activeMention, applyMention, matchingAgents } from "@/lib/mentions";

const agents = [
  { id: "a1", name: "Review Bot" },
  { id: "a2", name: "Oddy Qwen Coder" },
  { id: "a3", name: "Architect" },
];

describe("mention composer", () => {
  it("detects a token at the caret but not inside an e-mail address", () => {
    expect(activeMention("Please @Re", 10)).toEqual({ start: 7, end: 10, query: "Re" });
    expect(activeMention("mail me at dev@example.com", 25)).toBeNull();
    expect(activeMention("done @[Review Bot] thanks", 20)).toBeNull();
    expect(activeMention("text after a newline\n@Ar", 25)).toEqual({
      start: 21,
      end: 25,
      query: "Ar",
    });
  });

  it("replaces the typed token with the bracketed form and moves the caret", () => {
    const token = activeMention("Please @Odd", 11);
    expect(token).not.toBeNull();
    const result = applyMention("Please @Odd", token!, "Oddy Qwen Coder");
    expect(result.text).toBe("Please @[Oddy Qwen Coder] ");
    expect(result.caret).toBe(result.text.length);
  });

  it("keeps the text after the caret when completing a mention", () => {
    const token = activeMention("Ask @Arc about it", 8);
    const result = applyMention("Ask @Arc about it", token!, "Architect");
    expect(result.text).toBe("Ask @[Architect] about it");
    expect(result.caret).toBe("Ask @[Architect]".length);
  });

  it("filters agents case-insensitively", () => {
    expect(matchingAgents(agents, "re").map((agent) => agent.name)).toEqual(["Review Bot"]);
    expect(matchingAgents(agents, "")).toHaveLength(3);
    expect(matchingAgents(agents, "zzz")).toHaveLength(0);
  });
});
