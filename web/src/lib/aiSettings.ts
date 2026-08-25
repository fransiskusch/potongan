import { createContext, createElement, useContext, useEffect, useState } from "react";
import type React from "react";
import type { ProviderId } from "./providers";
import { DEFAULT_PROVIDER, getProviderConfig } from "./providers";

const STORAGE_PROVIDER = "ac_provider";
const STORAGE_MODEL = "ac_model";
const STORAGE_KEYS = "ac_api_keys";

interface AISettingsValue {
  provider: ProviderId;
  setProvider: (p: ProviderId) => void;
  model: string;
  setModel: (m: string) => void;
  apiKeys: Record<string, string>;
  setApiKey: (provider: string, key: string) => void;
  customBaseUrl: string;
  setCustomBaseUrl: (u: string) => void;
  customModelName: string;
  setCustomModelName: (m: string) => void;
}

const AISettingsContext = createContext<AISettingsValue | null>(null);

function readStorage(key: string): string | null {
  try {
    return typeof window === "undefined" ? null : localStorage.getItem(key);
  } catch {
    return null;
  }
}

function readJson<T>(key: string, fallback: T): T {
  try {
    const raw = readStorage(key);
    if (!raw) return fallback;
    const parsed: unknown = JSON.parse(raw);
    if (
      typeof parsed !== "object" ||
      parsed === null ||
      Array.isArray(parsed) ||
      Object.getPrototypeOf(parsed) !== Object.prototype ||
      Object.values(parsed).some((value) => typeof value !== "string")
    ) return fallback;
    return parsed as T;
  } catch {
    return fallback;
  }
}

function writeStorage(key: string, value: string): void {
  try {
    if (typeof window !== "undefined") localStorage.setItem(key, value);
  } catch {
    // Storage can be unavailable in private or restricted browser contexts.
  }
}

export function AISettingsProvider({ children }: { children: React.ReactNode }) {
  const [provider, setProviderState] = useState<ProviderId>(() => {
    const saved = readStorage(STORAGE_PROVIDER);
    return saved && getProviderConfig(saved as ProviderId) ? (saved as ProviderId) : DEFAULT_PROVIDER;
  });
  const [model, setModelState] = useState(() => readStorage(STORAGE_MODEL) || "");
  const [apiKeys, setApiKeys] = useState<Record<string, string>>(() => readJson(STORAGE_KEYS, {}));
  const [customBaseUrl, setCustomBaseUrlState] = useState(() => apiKeys["custom_base_url"] || "");
  const [customModelName, setCustomModelNameState] = useState(() => apiKeys["custom_model_name"] || "");

  useEffect(() => writeStorage(STORAGE_PROVIDER, provider), [provider]);
  useEffect(() => writeStorage(STORAGE_MODEL, model), [model]);
  useEffect(() => writeStorage(STORAGE_KEYS, JSON.stringify(apiKeys)), [apiKeys]);

  const setProvider = (nextProvider: ProviderId) => {
    setProviderState(nextProvider);
    const config = getProviderConfig(nextProvider);
    if (config?.defaultModel) setModelState(config.defaultModel);
  };

  const setApiKey = (keyProvider: string, key: string) => {
    setApiKeys((previous) => ({ ...previous, [keyProvider]: key }));
  };

  const setCustomBaseUrl = (value: string) => {
    setCustomBaseUrlState(value);
    setApiKeys((previous) => ({ ...previous, custom_base_url: value }));
  };

  const setCustomModelName = (value: string) => {
    setCustomModelNameState(value);
    setApiKeys((previous) => ({ ...previous, custom_model_name: value }));
  };

  return createElement(
    AISettingsContext.Provider,
    { value: { provider, setProvider, model, setModel: setModelState, apiKeys, setApiKey, customBaseUrl, setCustomBaseUrl, customModelName, setCustomModelName } },
    children,
  );
}

export function useAISettings(): AISettingsValue {
  const context = useContext(AISettingsContext);
  if (!context) throw new Error("useAISettings must be used within AISettingsProvider");
  return context;
}
