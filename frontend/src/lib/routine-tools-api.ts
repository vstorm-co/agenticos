import { apiClient } from "@/lib/api-client";
import type { PlatformToolGroup } from "@/types/mcp";

export type RoutineToolKey =
  | { capability_id: string; tool_id: string }
  | { connection_id: string; tool_id: string }
  | { kind: "platform"; tool_id: string };
export type RoutineToolSettingValue = "ask" | "off";
export type RoutineToolSetting = RoutineToolKey & { setting: RoutineToolSettingValue };
interface ToolReview {
  name: string;
  effect: boolean;
  agent: "free" | "ask";
  setting: RoutineToolSettingValue | null;
}
export type RoutineToolOption = ToolReview &
  (
    | { capability_id: string; tool_id: string; capability_name: string }
    | {
        connection_id: string;
        tool_id: string;
        account_name: string;
        account_scope: "personal" | "organization";
      }
    | { kind: "platform"; tool_id: string; group: PlatformToolGroup }
  );
export interface RoutineToolOptions {
  items: RoutineToolOption[];
  unavailable_settings: RoutineToolSetting[];
  unavailable_sources: string[];
}
export function routineToolKey(tool: RoutineToolOption | RoutineToolSetting): RoutineToolKey {
  if ("capability_id" in tool) return { capability_id: tool.capability_id, tool_id: tool.tool_id };
  if ("connection_id" in tool) return { connection_id: tool.connection_id, tool_id: tool.tool_id };
  return { kind: "platform", tool_id: tool.tool_id };
}
export function routineToolIdentity(tool: RoutineToolOption | RoutineToolSetting): string {
  return JSON.stringify(routineToolKey(tool));
}
const path = (agentId: string, triggerId: string) =>
  `/agents/${agentId}/triggers/${triggerId}/tools`;
export const routineToolsApi = {
  get: (agentId: string, triggerId: string) =>
    apiClient.get<RoutineToolOptions>(path(agentId, triggerId)),
  replace: (agentId: string, triggerId: string, settings: RoutineToolSetting[]) =>
    apiClient.put<RoutineToolOptions>(path(agentId, triggerId), { settings }),
};
