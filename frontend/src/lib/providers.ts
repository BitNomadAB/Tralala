export interface ProviderPreset {
  id: string;
  label: string;
  baseUrl: string;
  model: string;
  hint?: string;
}

/**
 * Known OpenAI-compatible providers. Anything else is configured manually; the preset only prefills
 * the base URL and a sensible default model, it never restricts what an agent may use.
 */
export const PROVIDER_PRESETS: ProviderPreset[] = [
  {
    id: "custom",
    label: "Custom / self-hosted (OpenAI-compatible)",
    baseUrl: "",
    model: "",
    hint: "Point at llama.cpp, vLLM, LM Studio or any compatible gateway.",
  },
  {
    id: "deepseek",
    label: "DeepSeek",
    baseUrl: "https://api.deepseek.com/v1",
    model: "deepseek-flash",
    hint: "deepseek-flash (fast) or deepseek-v4-pro (deep reasoning), as reported by /models.",
  },
  {
    id: "openai",
    label: "OpenAI",
    baseUrl: "https://api.openai.com/v1",
    model: "gpt-4o-mini",
  },
  {
    id: "openrouter",
    label: "OpenRouter",
    baseUrl: "https://openrouter.ai/api/v1",
    model: "",
    hint: "Model ids are vendor-prefixed, for example anthropic/claude-sonnet-4.",
  },
  {
    id: "ollama",
    label: "Ollama (local)",
    baseUrl: "http://127.0.0.1:11434/v1",
    model: "llama3.1",
  },
  {
    id: "llamacpp",
    label: "llama.cpp / vLLM (local)",
    baseUrl: "http://127.0.0.1:8080/v1",
    model: "",
  },
];

export function presetById(id: string): ProviderPreset | undefined {
  return PROVIDER_PRESETS.find((preset) => preset.id === id);
}

export function providerLabelFor(baseUrl: string): string | undefined {
  const match = PROVIDER_PRESETS.find(
    (preset) => preset.baseUrl && baseUrl.startsWith(preset.baseUrl),
  );
  return match?.label;
}
