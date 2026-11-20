import { z } from "zod";
import type { BrowserCredentialAudience } from "./browser-credentials-api";
import { isBrowserCredentialId } from "./browser-credential-review";
import type { BrowserCredentialPlan } from "@/types/browser-credentials";
import type {
  BrowserContinuationConfirmation,
  BrowserCredentialContinuation,
} from "@/types/browser-credential-continuation";

export type BrowserContinuationAttempt =
  | { kind: "prepare"; request_id: string }
  | ({ kind: "confirm"; continuation_id: string } & BrowserContinuationConfirmation);
export interface BrowserContinuationSlot {
  attempt: BrowserContinuationAttempt | null;
  unavailable: boolean;
}
const uuid = z.string().refine(isBrowserCredentialId);
const attemptSchema = z.discriminatedUnion("kind", [
  z.object({ kind: z.literal("prepare"), request_id: uuid }).strict(),
  z
    .object({
      kind: z.literal("confirm"),
      continuation_id: uuid,
      document_id: uuid,
      authorization_generation: uuid,
      approve: z.boolean(),
      keep_signed_in: z.boolean(),
    })
    .strict(),
]);

export function browserContinuationAttemptKey(
  audience: BrowserCredentialAudience,
  source: BrowserCredentialPlan,
  observation?: BrowserCredentialContinuation,
) {
  return (
    "t3os:browser-continuation:v1:" +
    JSON.stringify([
      audience.actor,
      audience.organization,
      source.run_id,
      source.id,
      source.parent_plan_id,
      source.call_id,
      source.tab_id,
      source.secret_id,
      source.authorization_generation,
      observation ? ["confirm", observation.id, observation.document_id] : ["prepare"],
    ])
  );
}

/** Corrupt or unavailable storage is uncertainty, never a reason to mint another attempt. */
export function readBrowserContinuationAttempt(
  key: string,
  kind: BrowserContinuationAttempt["kind"],
): BrowserContinuationSlot {
  try {
    const raw = sessionStorage.getItem(key);
    if (raw === null) return { attempt: null, unavailable: false };
    if (raw.length <= 2_048) {
      const parsed = attemptSchema.safeParse(JSON.parse(raw));
      if (parsed.success && parsed.data.kind === kind)
        return { attempt: parsed.data, unavailable: false };
    }
  } catch {
    /* Storage and JSON failures cannot release an earlier uncertain decision. */
  }
  return { attempt: null, unavailable: true };
}

/** Retain the immutable tuple before sending; never replace or renew an unresolved choice. */
export function retainBrowserContinuationAttempt(key: string, attempt: BrowserContinuationAttempt) {
  const parsed = attemptSchema.safeParse(attempt);
  if (!parsed.success) return false;
  const existing = readBrowserContinuationAttempt(key, attempt.kind);
  const exact = JSON.stringify(parsed.data);
  if (existing.unavailable) return false;
  if (existing.attempt) return JSON.stringify(existing.attempt) === exact;
  try {
    sessionStorage.setItem(key, exact);
    const saved = readBrowserContinuationAttempt(key, attempt.kind);
    return !saved.unavailable && JSON.stringify(saved.attempt) === exact;
  } catch {
    return false;
  }
}
