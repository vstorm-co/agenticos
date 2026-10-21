/**
 * Web Push in this browser (#2097): whether it can, whether it is on, and
 * turning it on or off - the service worker (`public/sw.js`), the browser's
 * permission, the push subscription, and the server's record of it.
 */

import { apiClient } from "@/lib/api-client";

export type PushState = "unsupported" | "blocked" | "off" | "on";

const WORKER = "/sw.js";

function supported(): boolean {
  return (
    typeof window !== "undefined" &&
    "serviceWorker" in navigator &&
    "PushManager" in window &&
    "Notification" in window
  );
}

/** The key, as `pushManager.subscribe` wants it: bytes, not base64url. */
function keyBytes(base64url: string): Uint8Array<ArrayBuffer> {
  const padded = base64url
    .replace(/-/g, "+")
    .replace(/_/g, "/")
    .padEnd(Math.ceil(base64url.length / 4) * 4, "=");
  const binary = atob(padded);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
  return bytes;
}

async function subscription(): Promise<PushSubscription | null> {
  const registration = await navigator.serviceWorker.getRegistration(WORKER);
  return registration ? registration.pushManager.getSubscription() : null;
}

export async function pushState(): Promise<PushState> {
  if (!supported()) return "unsupported";
  if (Notification.permission === "denied") return "blocked";
  return (await subscription()) ? "on" : "off";
}

/** Ask for the permission, subscribe, and tell the server. The state it ended in. */
export async function enablePush(): Promise<PushState> {
  if (!supported()) return "unsupported";
  const permission = await Notification.requestPermission();
  if (permission !== "granted") return permission === "denied" ? "blocked" : "off";
  const registration = await navigator.serviceWorker.register(WORKER);
  await navigator.serviceWorker.ready;
  const { public_key } = await apiClient.get<{ public_key: string }>("/push/key");
  const subscribed = await registration.pushManager.subscribe({
    userVisibleOnly: true,
    applicationServerKey: keyBytes(public_key),
  });
  const { endpoint, keys } = subscribed.toJSON();
  await apiClient.post("/push/subscriptions", { endpoint, keys });
  return "on";
}

/** Unsubscribe this browser, here and on the server. */
export async function disablePush(): Promise<PushState> {
  const current = await subscription();
  if (current) {
    await apiClient.delete("/push/subscriptions", { params: { endpoint: current.endpoint } });
    await current.unsubscribe();
  }
  return "off";
}

export interface PushTest {
  sent: number;
  gone: number;
  failed: number;
}

export async function sendTestPush(): Promise<PushTest> {
  return apiClient.post<PushTest>("/push/test");
}
