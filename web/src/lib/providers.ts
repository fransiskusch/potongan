export type ProviderId =
  | "openai"
  | "gemini"
  | "deepseek"
  | "groq"
  | "openrouter"
  | "xai"
  | "mistral"
  | "custom"
  | "manual_ai";

export interface ProviderConfig {
  id: ProviderId;
  label: string;
  defaultModel: string;
  fallbackModels: string[];
  supportsModelFetch: boolean;
}

export const PROVIDERS: ProviderConfig[] = [
  { id: "openai", label: "OpenAI", defaultModel: "gpt-4o-mini", fallbackModels: ["gpt-4o-mini", "gpt-4o", "gpt-4.1-mini", "gpt-4.1-nano"], supportsModelFetch: true },
  { id: "gemini", label: "Google Gemini", defaultModel: "gemini-3.6-flash", fallbackModels: ["gemini-3.6-flash", "gemini-3.5-flash-lite", "gemini-3.1-pro"], supportsModelFetch: true },
  { id: "deepseek", label: "DeepSeek", defaultModel: "deepseek-chat", fallbackModels: ["deepseek-chat"], supportsModelFetch: true },
  { id: "groq", label: "Groq", defaultModel: "llama-3.3-70b-versatile", fallbackModels: ["llama-3.3-70b-versatile"], supportsModelFetch: true },
  { id: "openrouter", label: "OpenRouter", defaultModel: "openai/gpt-4o-mini", fallbackModels: ["openai/gpt-4o-mini"], supportsModelFetch: true },
  { id: "xai", label: "xAI Grok", defaultModel: "grok-2-latest", fallbackModels: ["grok-2-latest"], supportsModelFetch: true },
  { id: "mistral", label: "Mistral", defaultModel: "mistral-large-latest", fallbackModels: ["mistral-large-latest"], supportsModelFetch: true },
  { id: "custom", label: "Custom (OpenAI Compatible)", defaultModel: "", fallbackModels: [], supportsModelFetch: false },
  { id: "manual_ai", label: "Manual (Copy-Paste Prompt)", defaultModel: "", fallbackModels: [], supportsModelFetch: false },
];

export const DEFAULT_PROVIDER: ProviderId = "manual_ai";

export function getProviderConfig(id: ProviderId): ProviderConfig | undefined {
  return PROVIDERS.find((p) => p.id === id);
}
