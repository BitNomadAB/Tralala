import { describe, expect, it } from "vitest";
import {
  CONTAINER_HINT,
  PROVIDER_PRESETS,
  presetById,
  presetRequirements,
  type ProviderPreset,
} from "@/lib/providers";

/** The preset with this id; a missing one fails the test by name instead of as a null error. */
function preset(id: string): ProviderPreset {
  const found = presetById(id);
  if (!found) throw new Error(`no provider preset "${id}"`);
  return found;
}

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
    expect(presetRequirements(preset("openai")).apiKey).toBe("required");
    expect(presetRequirements(preset("deepseek")).apiKey).toBe("required");
    expect(presetRequirements(preset("openrouter")).apiKey).toBe("required");
    expect(presetRequirements(preset("ollama")).apiKey).toBe("not-needed");
    expect(presetRequirements(preset("llamacpp")).apiKey).toBe("not-needed");
    expect(presetRequirements(preset("custom")).apiKey).toBe("not-needed");
  });

  it("says which providers need a model name at all", () => {
    expect(presetRequirements(preset("deepseek")).model).toBe("required");
    expect(presetRequirements(preset("ollama")).model).toBe("required");
    // llama.cpp serves one model and ignores the name; custom is unknown.
    expect(presetRequirements(preset("llamacpp")).model).toBe("optional");
    expect(presetRequirements(preset("custom")).model).toBe("optional");
  });

  it("points the local presets at the host, not at the backend container", () => {
    expect(preset("ollama").baseUrl).toBe("http://host.docker.internal:11434/v1");
    expect(preset("llamacpp").baseUrl).toBe("http://host.docker.internal:8080/v1");
    for (const id of ["ollama", "llamacpp"]) {
      expect(preset(id).hint).toContain(CONTAINER_HINT);
    }
  });

  it("locks the endpoint only for hosted providers", () => {
    expect(presetRequirements(preset("openai")).endpointLocked).toBe(true);
    expect(presetRequirements(preset("ollama")).endpointLocked).toBe(false);
  });
});
