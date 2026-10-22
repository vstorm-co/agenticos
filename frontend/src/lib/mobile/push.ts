/**
 * Push to the phone app while it is closed (#2097), through a UnifiedPush
 * distributor (ntfy). The distributor hands the app a Web Push endpoint and
 * keys; this tells the server about them exactly as a browser's
 * subscription is told, so one sender serves both.
 */

import { apiClient } from "@/lib/api-client";
import { invokeShell, ShellError } from "@/lib/desktop/shell";

export interface PhonePushStatus {
  /** Distributor apps on the phone; none means push needs one installed. */
  distributors: string[];
  distributor: string | null;
  failed: string | null;
  subscription: { endpoint: string; keys: { p256dh: string; auth: string } } | null;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

const text = (value: unknown): string | null => (typeof value === "string" ? value : null);

export function parsePhonePushStatus(value: unknown): PhonePushStatus {
  if (
    !isRecord(value) ||
    !Array.isArray(value.distributors) ||
    !value.distributors.every((name) => typeof name === "string")
  ) {
    throw new ShellError("malformed", "the phone's push status");
  }
  const endpoint = text(value.endpoint);
  const p256dh = text(value.p256dh);
  const auth = text(value.auth);
  return {
    distributors: value.distributors,
    distributor: text(value.distributor),
    failed: text(value.failed),
    subscription: endpoint && p256dh && auth ? { endpoint, keys: { p256dh, auth } } : null,
  };
}

export async function phonePushStatus(): Promise<PhonePushStatus> {
  return parsePhonePushStatus(await invokeShell("push_status"));
}

/** Tell the server where to push - the same request a browser's subscription makes. */
export async function syncPhonePush(status: PhonePushStatus): Promise<void> {
  if (status.subscription) await apiClient.post("/push/subscriptions", status.subscription);
}

/**
 * Register with the phone's distributor for this deployment's key, then wait
 * for the endpoint it hands over and tell the server. The state it ended in.
 */
export async function enablePhonePush(
  wait: (ms: number) => Promise<void> = (ms) => new Promise((done) => setTimeout(done, ms)),
): Promise<PhonePushStatus> {
  const { public_key } = await apiClient.get<{ public_key: string }>("/push/key");
  const registered = await invokeShell("push_register", { vapid: public_key });
  let status = await phonePushStatus();
  // The endpoint comes from the distributor, a moment after the registration.
  for (
    let tries = 0;
    registered === true && !status.subscription && !status.failed && tries < 10;
    tries++
  ) {
    await wait(500);
    status = await phonePushStatus();
  }
  await syncPhonePush(status);
  return status;
}

export async function disablePhonePush(status: PhonePushStatus): Promise<PhonePushStatus> {
  if (status.subscription) {
    await apiClient.delete("/push/subscriptions", {
      params: { endpoint: status.subscription.endpoint },
    });
  }
  await invokeShell("push_unregister");
  return phonePushStatus();
}
