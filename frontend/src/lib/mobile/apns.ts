/**
 * Push to the iPhone app while it is closed (#2097), through Apple's service
 * with the organization's own APNs key: the app asks the person and registers
 * with APNs (`mobile/src-tauri/src/apns.rs`), and the device token it hands
 * over is told to the server, which signs every message with that key.
 */

import { readMobilePushPreferences } from "./notifications";
import { apiClient } from "@/lib/api-client";
import { ApiError } from "@/lib/api-error";
import { invokeShell, ShellError } from "@/lib/desktop/shell";

export type ApnsEnvironment = "production" | "sandbox";

/** The deployment's APNs key, as anybody signed in may read it - never the key itself. */
export interface ApnsSetup {
  configured: boolean;
  key_id: string | null;
  team_id: string | null;
  topic: string | null;
  environment: ApnsEnvironment | null;
}

export type IphonePermission = "granted" | "denied" | "undetermined";

export interface IphonePush {
  /** Whether the organization set its APNs key; without it the iPhone gets nothing. */
  configured: boolean;
  permission: IphonePermission;
  /** The device token, once registered with APNs. */
  token: string | null;
}

const PERMISSIONS: readonly IphonePermission[] = ["granted", "denied", "undetermined"];

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

/** The app's answer to `apns_status` and `apns_register`. */
export function parseApnsStatus(value: unknown): Omit<IphonePush, "configured"> {
  if (isRecord(value)) {
    const permission = PERMISSIONS.find((known) => known === value.permission);
    const token = value.token ?? null;
    if (permission !== undefined && (token === null || typeof token === "string")) {
      return { permission, token };
    }
  }
  throw new ShellError("malformed", "the iPhone's push status");
}

export function apnsSetup(): Promise<ApnsSetup> {
  return apiClient.get<ApnsSetup>("/push/apns");
}

export async function nativeIphonePush(): Promise<Omit<IphonePush, "configured">> {
  return parseApnsStatus(await invokeShell("apns_status"));
}

export async function iphonePush(): Promise<IphonePush> {
  const [setup, status] = await Promise.all([apnsSetup(), nativeIphonePush()]);
  return { configured: setup.configured, ...status };
}

/** Tell the server this iPhone's token - again on every arrival, as a browser's subscription is. */
export async function syncIphonePush(push: IphonePush): Promise<void> {
  if (push.configured && push.permission === "granted" && push.token !== null) {
    await apiClient.post("/push/apns/devices", { token: push.token });
  }
}

/** Ask the person, register with APNs, tell the server. The state it ended in. */
export async function enableIphonePush(): Promise<IphonePush> {
  await readMobilePushPreferences();
  const status = parseApnsStatus(await invokeShell("apns_register"));
  const push = { configured: true, ...status };
  await syncIphonePush(push);
  return push;
}

export async function disableIphonePush(push: IphonePush): Promise<IphonePush> {
  if (push.token !== null) {
    try {
      await apiClient.delete("/push/apns/devices", { params: { token: push.token } });
    } catch (error) {
      if (!(error instanceof ApiError && error.status === 404)) throw error;
    }
  }
  await invokeShell("apns_unregister");
  return { ...push, token: null };
}

export interface ApnsKey {
  key_id: string;
  team_id: string;
  topic: string;
  environment: ApnsEnvironment;
  /** The `.p8` file's contents. */
  private_key: string;
}

export function setApnsKey(key: ApnsKey): Promise<ApnsSetup> {
  return apiClient.put<ApnsSetup>("/push/apns", key);
}

export function clearApnsKey(): Promise<ApnsSetup> {
  return apiClient.delete<ApnsSetup>("/push/apns");
}
