/**
 * Pairing a phone (#2097): a single-use code for the signed-in person, drawn as a
 * QR, and the redemption the phone makes with it.
 */

import { apiClient } from "./api-client";
import type { User } from "@/types";

export interface PairingCode {
  code: string;
  /** Seconds until the code stops working. */
  expires_in: number;
}

export async function createPairingCode(): Promise<PairingCode> {
  return apiClient.post<PairingCode>("/auth/pairing-codes");
}

export type PairingIdentity = Pick<User, "id" | "email" | "full_name">;

export function previewPairingCode(code: string): Promise<PairingIdentity> {
  return apiClient.post<PairingIdentity>("/auth/pair/preview", { code });
}

export interface Paired {
  user: User;
  access_token: string;
}

export async function redeemPairingCode(code: string): Promise<Paired> {
  return apiClient.post<Paired>("/auth/pair", { code, confirmed: true });
}

/**
 * What the QR encodes: the app's own link, carrying this console's address and
 * the code. The app's scanner reads it; so does the phone's camera, which opens
 * the app on it.
 */
export function pairingLink(origin: string, code: string): string {
  const params = new URLSearchParams({ server: origin, code });
  return `agenticos://pair?${params.toString()}`;
}
