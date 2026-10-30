import { invokeShell, ShellError } from "./shell";

export const SYSTEM_PERMISSIONS = [
  "screen_capture",
  "accessibility",
  "microphone",
  "notifications",
] as const;
export type SystemPermission = (typeof SYSTEM_PERMISSIONS)[number];
export type PermissionStatus = "granted" | "denied" | "not_determined" | "unsupported";
export interface NativeReadiness extends Record<SystemPermission, PermissionStatus> {
  connection_revision: string;
}

export function parseReadiness(value: unknown): NativeReadiness {
  if (
    !value ||
    typeof value !== "object" ||
    !("connection_revision" in value) ||
    typeof value.connection_revision !== "string"
  )
    throw new ShellError("malformed", "desktop readiness");
  const permission = (key: SystemPermission): PermissionStatus => {
    const result = Reflect.get(value, key);
    if (
      result === "granted" ||
      result === "denied" ||
      result === "not_determined" ||
      result === "unsupported"
    )
      return result;
    throw new ShellError("malformed", key);
  };
  return {
    connection_revision: value.connection_revision,
    screen_capture: permission("screen_capture"),
    accessibility: permission("accessibility"),
    microphone: permission("microphone"),
    notifications: permission("notifications"),
  };
}
export async function readDesktopReadiness(): Promise<NativeReadiness> {
  return parseReadiness(await invokeShell("desktop_readiness"));
}
export async function requestDesktopPermission(permission: SystemPermission): Promise<void> {
  await invokeShell("desktop_request_permission", { permission });
}
export async function readDesktopFocus(): Promise<{
  focused: boolean;
  conversation_id: string | null;
}> {
  const result: unknown = await invokeShell("desktop_is_focused");
  if (
    !result ||
    typeof result !== "object" ||
    !("focused" in result) ||
    typeof result.focused !== "boolean" ||
    !("conversation_id" in result) ||
    (result.conversation_id !== null && typeof result.conversation_id !== "string")
  )
    throw new ShellError("malformed", "desktop focus");
  return { focused: result.focused, conversation_id: result.conversation_id };
}
export interface DesktopActivityEntry {
  id: string;
  title: string;
  path: string;
  stop_conversation: string | null;
  question?: boolean;
}
export async function publishDesktopActivity(
  entries: DesktopActivityEntry[],
  conversationId: string | null,
  context?: { user: string | null | undefined; organization: string | null },
): Promise<void> {
  await invokeShell("desktop_activity", {
    entries,
    conversationId,
    origin: window.location.origin,
    accountId: context?.user ?? null,
    organizationId: context?.organization ?? null,
  });
}

export async function retryDesktopScreenshot(): Promise<void> {
  await invokeShell("desktop_retry_screenshot");
}
