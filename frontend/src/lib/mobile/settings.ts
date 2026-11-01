import { invokeShell, ShellError } from "@/lib/desktop/shell";
import { disableIphonePush, nativeIphonePush } from "./apns";
import { disablePhonePush, phonePushStatus } from "./push";

export interface MobileSettings {
  servers: { name: string; url: string }[];
  active: string | null;
  locked_server: boolean;
  biometric_lock: boolean;
  biometric_managed: boolean;
  biometric_available: boolean;
}
function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
export function parseMobileSettings(value: unknown): MobileSettings {
  if (!isRecord(value)) throw new ShellError("malformed", "mobile settings");
  const raw = value;
  if (
    !Array.isArray(raw.servers) ||
    !raw.servers.every(
      (s: unknown) =>
        typeof s === "object" &&
        s !== null &&
        "name" in s &&
        typeof s.name === "string" &&
        "url" in s &&
        typeof s.url === "string",
    ) ||
    !(raw.active === null || typeof raw.active === "string") ||
    typeof raw.locked_server !== "boolean" ||
    typeof raw.biometric_lock !== "boolean" ||
    typeof raw.biometric_managed !== "boolean" ||
    typeof raw.biometric_available !== "boolean"
  )
    throw new ShellError("malformed", "mobile settings");
  return {
    servers: raw.servers,
    active: raw.active,
    locked_server: raw.locked_server,
    biometric_lock: raw.biometric_lock,
    biometric_managed: raw.biometric_managed,
    biometric_available: raw.biometric_available,
  };
}
export async function mobileSettings(): Promise<MobileSettings> {
  return parseMobileSettings(await invokeShell("mobile_settings"));
}
export async function setMobileLock(enabled: boolean): Promise<void> {
  await invokeShell("set_mobile_lock", { enabled });
}
/** Stop old-server delivery before the global phone token can belong to another server. */
export async function chooseMobileServer(platform: string): Promise<void> {
  if (platform === "ios") {
    const push = await nativeIphonePush();
    if (push.token) await disableIphonePush({ configured: true, ...push });
  } else {
    const push = await phonePushStatus();
    if (push.subscription) await disablePhonePush(push);
  }
  await invokeShell("choose_server");
}
