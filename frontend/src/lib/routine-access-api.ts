import { apiClient } from "@/lib/api-client";
import type { PlatformToolGroup } from "@/types/mcp";

export type RoutineSourceKind =
  | "capability"
  | "skill"
  | "context"
  | "knowledge"
  | "table"
  | "delegate"
  | "remote_agent"
  | "platform"
  | "mcp_account"
  | "chat_connection"
  | "phone"
  | "terminal_account"
  | "terminal_credential"
  | "event_source";

/** One reviewed source, named; `name` is null for one that is gone or not visible. */
export interface RoutineSourceItem {
  kind: RoutineSourceKind;
  id?: string | null;
  name?: string | null;
  detail?: string | null;
}

/** `reviewed` stops for a new review when access grows; `trust_agent` follows the agent. */
export type RoutineAccessMode = "reviewed" | "trust_agent";

/** `allow` runs where the agent lets it, `ask` waits for approval, `off` hides and refuses it. */
export type RoutineToolSettingValue = "allow" | "ask" | "off";

/** What one call does now: runs, asks, runs on the creator's standing consent, or is refused. */
export type RoutineToolEffect = "run" | "ask" | "consent" | "off";

export type RoutineDelegateSetting = "allow" | "ask";

export interface RoutineCapabilityToolKey {
  capability_id: string;
  tool_id: string;
}
/** Keyed by the connection alone: reconnecting the same account keeps the setting. */
export interface RoutineMcpToolKey {
  connection_id: string;
  tool_id: string;
}
/** One of this platform's own MCP tools, which a routine calls as its creator. */
export interface RoutinePlatformToolKey {
  kind: "platform";
  tool_id: string;
}
export type RoutineToolKey = RoutineCapabilityToolKey | RoutineMcpToolKey | RoutinePlatformToolKey;

interface ToolOption {
  name: string;
  /** The tool changes something; false for a read. */
  effect: boolean;
  /** The agent's own setting for the tool. */
  agent: "free" | "ask";
  /**
   * The routine's own setting; null where it has none and the mode's default
   * applies. For a routine not reviewed yet, or migrated, what saving proposes.
   */
  setting: RoutineToolSettingValue | null;
  /** What a call does now, the agent's own approvals included; null before the first review. */
  effective: RoutineToolEffect | null;
}
export type RoutineToolOption =
  | (RoutineCapabilityToolKey & ToolOption & { capability_name: string })
  | (RoutineMcpToolKey &
      ToolOption & { account_name: string; account_scope: "personal" | "organization" })
  | (RoutinePlatformToolKey & ToolOption & { group: PlatformToolGroup });

export type RoutineReviewReason =
  | "setup"
  | "sources"
  | "routine_changed"
  | "platform_identity"
  | "unavailable"
  | "trust_not_allowed";

export interface RoutineAccessReview {
  mode: RoutineAccessMode;
  /** Migrated and not saved since: its tools run as the agent allows until it is. */
  grandfathered: boolean;
  /** The stored review admits the next run as it stands. */
  current: boolean;
  review_reason: RoutineReviewReason | null;
  review_token: string;
  version_id: string;
  sources: RoutineSourceItem[];
  unavailable_sources: string[];
  /** Unavailable sources that block every run, and saving. */
  required_unavailable_sources: string[];
  tools: RoutineToolOption[];
  /** Accounts whose tool list needs a connection check before it can be shown. */
  unlisted_accounts: string[];
  has_delegates: boolean;
  delegates: RoutineDelegateSetting;
  /** The caller may let an effectful tool run without asking. */
  can_allow: boolean;
  allow_blocked_reason: "permission" | "organization" | "console" | null;
  can_trust: boolean;
  trust_blocked_reason: "permission" | "organization" | "event" | "console" | null;
}

export type RoutineToolSetting = RoutineToolKey & { setting: RoutineToolSettingValue };

/**
 * The whole review, replacing the previous one. A tool left out has no setting of
 * its own, so the mode's default applies to it (see `modeDefault`).
 */
export interface RoutineAccessUpdate {
  review_token: string;
  mode: RoutineAccessMode;
  tools: RoutineToolSetting[];
  delegates: RoutineDelegateSetting;
}

export function routineToolKey(tool: RoutineToolOption): RoutineToolKey {
  if ("capability_id" in tool) return { capability_id: tool.capability_id, tool_id: tool.tool_id };
  if ("kind" in tool) return { kind: tool.kind, tool_id: tool.tool_id };
  return { connection_id: tool.connection_id, tool_id: tool.tool_id };
}

/** A stable string for one tool, for maps and React keys. */
export function routineToolIdentity(tool: RoutineToolOption): string {
  return JSON.stringify(routineToolKey(tool));
}

/**
 * Whether the caller may choose Run freely for this tool. In `trust_agent` that
 * choice is the agent's own decision, which needs no standing consent.
 */
export function mayRunFreely(
  tool: RoutineToolOption,
  canAllow: boolean,
  mode: RoutineAccessMode,
): boolean {
  return tool.agent === "free" && (mode === "trust_agent" || canAllow || !tool.effect);
}

/**
 * What a tool without a setting of its own does in this mode, as the choice it
 * amounts to: in `reviewed` a read runs and a tool that changes something asks;
 * in `trust_agent` the agent decides. Choosing it stores nothing.
 */
export function modeDefault(
  tool: RoutineToolOption,
  mode: RoutineAccessMode,
): RoutineToolSettingValue {
  if (tool.agent === "ask") return "ask";
  return mode === "trust_agent" || !tool.effect ? "allow" : "ask";
}

const path = (agentId: string, triggerId: string) =>
  `/agents/${agentId}/triggers/${triggerId}/access`;

export const routineAccessApi = {
  get: (agentId: string, triggerId: string) =>
    apiClient.get<RoutineAccessReview>(path(agentId, triggerId)),
  replace: (agentId: string, triggerId: string, update: RoutineAccessUpdate) =>
    apiClient.put<RoutineAccessReview>(path(agentId, triggerId), update),
};
