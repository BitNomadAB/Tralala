import { describe, expect, it } from "vitest";
import { PROVIDER_PRESETS, presetById, presetRequirements } from "@/lib/providers";

describe("provider presets", () => {
  it("gives every preset a distinct id", () => {
    const ids = PROVIDER_PRESETS.map((preset) => preset.id);
    expect(new Set(ids).size).toBe(ids.length);
  });

  it("keeps exactly one editable endpoint per local provider and one fixed endpoint per hosted one", () => {
    const hosted = PROVIDER_PRESETS.filter((preset) => preset.baseUrlFixed);
    const local = PROVIDER_PRESETS.filter((preset) => !preset.baseUrlFixed);
    // A hosted provider without an endpoint would leave the form unusable; a local one with a
    // locked endpoint could not be pointed at another machine.
    expect(hosted.every((preset) => preset.baseUrl.length > 0)).toBe(true);
    expect(local.some((preset) => preset.baseUrl.length === 0)).toBe(true);
  });

  it("asks for a key only where the provider needs one", () => {
    expect(presetRequirements(presetById("openai")!).apiKey).toBe("required");
    expect(presetRequirements(presetById("deepseek")!).apiKey).toBe("required");
    expect(presetRequirements(presetById("openrouter")!).apiKey).toBe("required");
    expect(presetRequirements(presetById("ollama")!).apiKey).toBe("not-needed");
    expect(presetRequirements(presetById("llamacpp")!).apiKey).toBe("not-needed");
    expect(presetRequirements(presetById("custom")!).apiKey).toBe("not-needed");
  });

  it("says which providers need a model name at all", () => {
    expect(presetRequirements(presetById("deepseek")!).model).toBe("required");
    expect(presetRequirements(presetById("ollama")!).model).toBe("required");
    // llama.cpp serves one model and ignores the name; custom is unknown.
    expect(presetRequirements(presetById("llamacpp")!).model).toBe("optional");
    expect(presetRequirements(presetById("custom")!).model).toBe("optional");
  });

  it("locks the endpoint only for hosted providers", () => {
    expect(presetRequirements(presetById("openai")!).endpointLocked).toBe(true);
    expect(presetRequirements(presetById("ollama")!).endpointLocked).toBe(false);
  });
});
