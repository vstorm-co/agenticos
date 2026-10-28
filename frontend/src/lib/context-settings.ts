import type { ContextMode } from "@/types/providers";

export interface ContextFileSettings {
  mode: ContextMode;
  enabled: boolean;
}
export type ContextSettings = Record<string, ContextFileSettings>;

function record(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

/** Read the optional per-agent policy from the extensible capability config. */
export function contextSettings(value: unknown): ContextSettings {
  if (!record(value)) return {};
  const result: [string, ContextFileSettings][] = [];
  for (const [id, raw] of Object.entries(value)) {
    if (!record(raw)) continue;
    const mode: unknown = "mode" in raw ? raw.mode : "inject";
    const enabled: unknown = "enabled" in raw ? raw.enabled : true;
    if ((mode === "inject" || mode === "link") && typeof enabled === "boolean")
      result.push([id, { mode, enabled }]);
  }
  return Object.fromEntries(result);
}
