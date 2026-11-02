export interface ProviderPreset {
  id: string;
  label: string;
  /** The endpoint this provider serves. Empty means "fill it in yourself". */
  baseUrl: string;
  model: string;
  hint?: string;
  /** A hosted provider has one endpoint; a local one runs wherever you installed it. */
  baseUrlFixed: boolean;
  /** Whether a call is expected to carry a credential. */
  requiresApiKey: boolean;
  /** Whether the endpoint needs a model name at all. */
  requiresModel: boolean;
  modelPlaceholder?: string;
  docsUrl?: string;
}

/**
 * Known OpenAI-compatible providers. A preset prefills the endpoint and says what the provider
 * actually needs, so the form stops asking for a key a local server does not use and stops letting a
 * hosted provider be saved without one. It never restricts what an agent may use: anything else is
 * configured as "Custom".
 */
export const PROVIDER_PRESETS: ProviderPreset[] = [
  {
    id: "custom",
    label: "Custom / self-hosted (OpenAI-compatible)",
    baseUrl: "",
    model: "",
    hint: "Point at llama.cpp, vLLM, LM Studio or any compatible gateway. Nothing is assumed about the key.",
    baseUrlFixed: false,
    requiresApiKey: false,
    requiresModel: false,
    modelPlaceholder: "the name the endpoint reports",
  },
  {
    id: "deepseek",
    label: "DeepSeek",
    baseUrl: "https://api.deepseek.com/v1",
    model: "deepseek-flash",
    hint: "deepseek-flash (fast) or deepseek-v4-pro (deep reasoning), as reported by /models.",
    baseUrlFixed: true,
    requiresApiKey: true,
    requiresModel: true,
    modelPlaceholder: "deepseek-flash",
    docsUrl: "https://api-docs.deepseek.com",
  },
  {
    id: "openai",
    label: "OpenAI",
    baseUrl: "https://api.openai.com/v1",
    model: "gpt-4o-mini",
    hint: "A project key is required and the endpoint is fixed.",
    baseUrlFixed: true,
    requiresApiKey: true,
    requiresModel: true,
    modelPlaceholder: "gpt-4o-mini",
    docsUrl: "https://platform.openai.com/docs/api-reference",
  },
  {
    id: "openrouter",
    label: "OpenRouter",
    baseUrl: "https://openrouter.ai/api/v1",
    model: "",
    hint: "Model ids are vendor-prefixed, for example anthropic/claude-sonnet-4.",
    baseUrlFixed: true,
    requiresApiKey: true,
    requiresModel: true,
    modelPlaceholder: "anthropic/claude-sonnet-4",
    docsUrl: "https://openrouter.ai/docs",
  },
  {
    id: "ollama",
    label: "Ollama (local)",
    baseUrl: "http://127.0.0.1:11434/v1",
    model: "llama3.1",
    hint: "Ollama ignores the key. Change the host if it runs on another machine.",
    baseUrlFixed: false,
    requiresApiKey: false,
    requiresModel: true,
    modelPlaceholder: "llama3.1",
    docsUrl: "https://github.com/ollama/ollama/blob/main/docs/openai.md",
  },
  {
    id: "llamacpp",
    label: "llama.cpp / vLLM (local)",
    baseUrl: "http://127.0.0.1:8080/v1",
    model: "",
    hint: "The server usually serves one model and ignores the name; no key is needed unless you put one in front.",
    baseUrlFixed: false,
    requiresApiKey: false,
    requiresModel: false,
    modelPlaceholder: "usually ignored",
    docsUrl: "https://github.com/ggml-org/llama.cpp/tree/master/tools/server",
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

/** What the form must show for one preset: which fields it needs and which it locks. */
export interface PresetRequirements {
  apiKey: "required" | "not-needed";
  model: "required" | "optional";
  endpointLocked: boolean;
}

export function presetRequirements(preset: ProviderPreset): PresetRequirements {
  return {
    apiKey: preset.requiresApiKey ? "required" : "not-needed",
    model: preset.requiresModel ? "required" : "optional",
    endpointLocked: preset.baseUrlFixed,
  };
}
