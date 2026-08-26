import type React from "react";
import { useEffect, useRef, useState } from "react";
import { X, KeyRound, Cpu, CheckCircle2, AlertCircle, RefreshCw } from "lucide-react";
import { PROVIDERS, getProviderConfig } from "../lib/providers";
import { useAISettings } from "../lib/aiSettings";
import { apiTestAi, apiFetchModels, type ProviderModel } from "../api";

export const AISettingsModal: React.FC<{ open: boolean; onClose: () => void }> = ({ open, onClose }) => {
  const { provider, setProvider, model, setModel, apiKeys, setApiKey, customBaseUrl, setCustomBaseUrl, customModelName, setCustomModelName } = useAISettings();
  const [models, setModels] = useState<ProviderModel[]>([]);
  const [showKey, setShowKey] = useState(false);
  const [feedback, setFeedback] = useState<{ ok: boolean; msg: string } | null>(null);
  const [loading, setLoading] = useState(false);
  const providerRef = useRef<HTMLSelectElement>(null);
  const dialogRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    setFeedback(null);
    setModels([]);
  }, [provider]);

  useEffect(() => {
    if (!open) return;
    const previouslyFocused = document.activeElement as HTMLElement | null;
    providerRef.current?.focus();
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
      if (event.key !== "Tab") return;
      const focusable = Array.from(dialogRef.current?.querySelectorAll<HTMLElement>(
        'button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])',
      ) || []);
      if (focusable.length === 0) return;
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };
    document.addEventListener("keydown", handleKeyDown);
    return () => {
      document.removeEventListener("keydown", handleKeyDown);
      previouslyFocused?.focus();
    };
  }, [open, onClose]);

  if (!open) return null;

  const config = getProviderConfig(provider);
  const keyValue = apiKeys[provider] || "";
  const isCustom = provider === "custom";

  const handleTest = async () => {
    setLoading(true);
    setFeedback(null);
    try {
      const result = await apiTestAi({ provider, api_key: keyValue, custom_base_url: customBaseUrl, custom_model_name: customModelName, model });
      setFeedback({ ok: true, msg: result.message || "API Key is valid!" });
    } catch (error) {
      setFeedback({ ok: false, msg: error instanceof Error ? error.message : "Test failed" });
    } finally {
      setLoading(false);
    }
  };

  const handleFetch = async () => {
    setLoading(true);
    setFeedback(null);
    try {
      const result = await apiFetchModels({ provider, api_key: keyValue, custom_base_url: customBaseUrl, custom_model_name: customModelName });
      const fetchedModels = result.models || [];
      setModels(fetchedModels);
      if (fetchedModels.length > 0 && (!model || !fetchedModels.some((item) => item.id === model))) {
        setModel(fetchedModels[0].id);
      }
      setFeedback({ ok: true, msg: `Loaded ${fetchedModels.length} models` });
    } catch (error) {
      setFeedback({ ok: false, msg: error instanceof Error ? error.message : "Failed to fetch models" });
    } finally {
      setLoading(false);
    }
  };

  const allModels = Array.from(new Set([...(config?.fallbackModels || []), ...models.map((item) => item.id)]));

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm p-4" role="dialog" aria-modal="true" aria-labelledby="ai-settings-title" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose(); }}>
      <div ref={dialogRef} className="w-full max-w-lg bg-neutral-900 border border-neutral-800 rounded-2xl shadow-2xl overflow-hidden flex flex-col max-h-[85vh]">
        <div className="flex items-center justify-between p-4 border-b border-neutral-800">
          <div className="flex items-center gap-2"><Cpu className="w-5 h-5 text-amber-400" /><h3 id="ai-settings-title" className="font-semibold text-neutral-100">AI Engine Settings</h3></div>
          <button type="button" onClick={onClose} aria-label="Close AI Engine Settings" className="p-1 text-neutral-400 hover:text-neutral-100 rounded-lg hover:bg-neutral-800"><X className="w-5 h-5" /></button>
        </div>
        <div className="flex-1 overflow-y-auto p-4 space-y-4">
           <label className="block space-y-1.5"><span className="text-sm font-medium text-neutral-300">Provider</span><select ref={providerRef} value={provider} onChange={(event) => setProvider(event.target.value as typeof provider)} className="w-full px-3 py-2 bg-neutral-950 border border-neutral-800 rounded-lg text-neutral-200 text-sm">{PROVIDERS.map((item) => <option key={item.id} value={item.id}>{item.label}</option>)}</select></label>
          {provider !== "manual_ai" && <label className="block space-y-1.5"><span className="text-sm font-medium text-neutral-300 flex items-center gap-1.5"><KeyRound className="w-4 h-4 text-neutral-400" /> API Key</span><span className="relative block"><input type={showKey ? "text" : "password"} value={keyValue} onChange={(event) => setApiKey(provider, event.target.value)} className="w-full px-3 py-2 pr-16 bg-neutral-950 border border-neutral-800 rounded-lg text-neutral-200 text-sm" placeholder={`${config?.label} API key`} /><button type="button" onClick={() => setShowKey((shown) => !shown)} className="absolute right-2 top-1/2 -translate-y-1/2 text-xs text-neutral-400 hover:text-neutral-200">{showKey ? "Hide" : "Show"}</button></span></label>}
          {isCustom && <><label className="block space-y-1.5"><span className="text-sm font-medium text-neutral-300">Base URL (9router)</span><input value={customBaseUrl} onChange={(event) => setCustomBaseUrl(event.target.value)} className="w-full px-3 py-2 bg-neutral-950 border border-neutral-800 rounded-lg text-neutral-200 text-sm font-mono" placeholder="https://your-gateway.example/v1" /></label><label className="block space-y-1.5"><span className="text-sm font-medium text-neutral-300">Model Name</span><input value={customModelName} onChange={(event) => setCustomModelName(event.target.value)} className="w-full px-3 py-2 bg-neutral-950 border border-neutral-800 rounded-lg text-neutral-200 text-sm font-mono" placeholder="e.g. gpt-4o-mini" /></label></>}
          {provider !== "manual_ai" && <label className="block space-y-1.5"><span className="text-sm font-medium text-neutral-300">Model</span>{allModels.length > 0 ? <select value={model} onChange={(event) => setModel(event.target.value)} className="w-full px-3 py-2 bg-neutral-950 border border-neutral-800 rounded-lg text-neutral-200 text-sm">{allModels.map((item) => <option key={item} value={item}>{item}</option>)}</select> : <input value={model} onChange={(event) => setModel(event.target.value)} className="w-full px-3 py-2 bg-neutral-950 border border-neutral-800 rounded-lg text-neutral-200 text-sm font-mono" placeholder="model id" />}</label>}
          {feedback && <div className={`p-3 rounded-xl flex items-start gap-2 text-xs ${feedback.ok ? "bg-emerald-950/40 border border-emerald-800/60 text-emerald-300" : "bg-red-950/40 border border-red-800/60 text-red-300"}`}>{feedback.ok ? <CheckCircle2 className="w-4 h-4 mt-0.5" /> : <AlertCircle className="w-4 h-4 mt-0.5" />}<span>{feedback.msg}</span></div>}
        </div>
        <div className="p-4 border-t border-neutral-800 flex items-center justify-end gap-2">
           {config?.supportsModelFetch && <button type="button" onClick={handleFetch} disabled={loading || (isCustom && !customBaseUrl)} className="px-3.5 py-2 bg-neutral-800 hover:bg-neutral-700 disabled:opacity-40 text-neutral-200 text-xs font-medium rounded-xl flex items-center gap-1.5"><RefreshCw className="w-4 h-4" /> Fetch Models</button>}
          <button type="button" onClick={handleTest} disabled={loading || provider === "manual_ai"} className="px-3.5 py-2 bg-amber-400 hover:bg-amber-300 disabled:opacity-40 text-neutral-950 text-xs font-bold rounded-xl">{loading ? "Working..." : "Test Key"}</button>
          <button type="button" onClick={onClose} className="px-3.5 py-2 bg-neutral-800 hover:bg-neutral-700 text-neutral-200 text-xs font-medium rounded-xl">Close</button>
        </div>
      </div>
    </div>
  );
};

export default AISettingsModal;
