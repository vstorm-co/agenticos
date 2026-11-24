import type {
  BrowserCredentialAudience,
  BrowserSubmissionAttempt,
} from "./browser-credentials-api";
import {
  BROWSER_PROFILE_FIELDS,
  type BrowserCredentialEligible,
  type BrowserCredentialPlan,
  type BrowserFillField,
} from "@/types/browser-credentials";

export const BROWSER_CREDENTIAL_POLL_MS = 2_000;
export const BROWSER_CREDENTIAL_POLL_WINDOW_MS = 180_000;
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const FIELDS: readonly string[] = ["username", "password", "totp", ...BROWSER_PROFILE_FIELDS];

export const isBrowserCredentialId = (value: unknown): value is string =>
  typeof value === "string" && UUID.test(value);

/** Only a canonical HTTPS origin from the persisted receipt may be a handoff link. */
export function browserCredentialOrigin(value: string | null): string | null {
  if (!value) return null;
  try {
    const url = new URL(value);
    return url.protocol === "https:" && url.origin === value && !url.hostname.includes("*")
      ? value
      : null;
  } catch {
    return null;
  }
}
export function browserCredentialFields(plan: BrowserCredentialPlan): BrowserFillField[] | null {
  return Array.isArray(plan.fields) &&
    plan.fields.length > 0 &&
    plan.fields.length <= 9 &&
    new Set(plan.fields).size === plan.fields.length &&
    plan.fields.every((field) => FIELDS.includes(field))
    ? plan.fields
    : null;
}
export function browserCredentialPlanMatches(
  plan: BrowserCredentialPlan | null | undefined,
  runId: string,
  planId: string,
  callId?: string,
  tabId?: string,
): plan is BrowserCredentialPlan {
  return (
    !!plan &&
    plan.run_id === runId &&
    plan.id === planId &&
    isBrowserCredentialId(plan.id) &&
    isBrowserCredentialId(plan.run_id) &&
    isBrowserCredentialId(plan.secret_id) &&
    isBrowserCredentialId(plan.authorization_generation) &&
    typeof plan.call_id === "string" &&
    plan.call_id.length > 0 &&
    typeof plan.tab_id === "string" &&
    plan.tab_id.length > 0 &&
    (!callId || plan.call_id === callId) &&
    (!tabId || plan.tab_id === tabId) &&
    (plan.operation === "fill"
      ? plan.parent_plan_id === null
      : plan.operation === "submit" && isBrowserCredentialId(plan.parent_plan_id))
  );
}
export function browserCredentialPending(plan: BrowserCredentialPlan | null | undefined): boolean {
  return (
    !!plan &&
    ["requested", "preparing", "awaiting_confirmation", "approved", "claimed"].includes(plan.state)
  );
}
export function browserCredentialDeadlineLive(value: string | null, now: number): boolean {
  return typeof value === "string" && Number.isFinite(Date.parse(value)) && Date.parse(value) > now;
}
/** Eligibility is live metadata, not authority inferred from a saved name or a plan ID. */
export function currentBrowserCredential(
  plan: BrowserCredentialPlan,
  candidates: BrowserCredentialEligible[] | undefined,
): BrowserCredentialEligible | null {
  const fields = browserCredentialFields(plan);
  const origin = browserCredentialOrigin(plan.origin);
  if (!origin || !fields || !Array.isArray(candidates)) return null;
  return (
    candidates.find(
      (entry) =>
        entry.id === plan.secret_id &&
        entry.authorization_generation === plan.authorization_generation &&
        typeof entry.name === "string" &&
        !!entry.name.trim() &&
        (entry.kind === "browser_login" || entry.kind === "browser_profile") &&
        entry.browser?.allowed_origins.includes(origin) &&
        fields.every((field) => entry.browser.available_fields.includes(field)),
    ) ?? null
  );
}
export function browserCredentialSubmissionMatches(
  parent: BrowserCredentialPlan,
  child: BrowserCredentialPlan,
): boolean {
  return (
    browserCredentialPlanMatches(child, parent.run_id, child.id, parent.call_id, parent.tab_id) &&
    child.operation === "submit" &&
    child.parent_plan_id === parent.id &&
    child.secret_id === parent.secret_id &&
    child.authorization_generation === parent.authorization_generation &&
    child.document_id === parent.document_id &&
    child.origin === parent.origin
  );
}

export function browserSubmissionKey(
  audience: BrowserCredentialAudience,
  plan: BrowserCredentialPlan,
): string {
  return (
    "t3os:browser-submission:v1:" +
    JSON.stringify([
      audience.actor,
      audience.organization,
      plan.run_id,
      plan.id,
      plan.authorization_generation,
      plan.document_id,
    ])
  );
}
export interface BrowserSubmissionSlot {
  attempt: BrowserSubmissionAttempt | null;
  unavailable: boolean;
}
/** A denied/corrupt read is uncertainty; it never grants permission to mint another token. */
export function readBrowserSubmissionAttempt(
  key: string,
  plan: BrowserCredentialPlan,
): BrowserSubmissionSlot {
  try {
    const raw = sessionStorage.getItem(key);
    if (raw === null) return { attempt: null, unavailable: false };
    const value = JSON.parse(raw) as Partial<BrowserSubmissionAttempt> | null;
    if (
      value &&
      isBrowserCredentialId(value.request_id) &&
      value.document_id === plan.document_id &&
      isBrowserCredentialId(value.document_id) &&
      value.authorization_generation === plan.authorization_generation
    ) {
      return {
        attempt: {
          request_id: value.request_id,
          document_id: value.document_id,
          authorization_generation: value.authorization_generation,
        },
        unavailable: false,
      };
    }
  } catch {
    /* Unavailable storage must not turn an uncertain write into a new request. */
  }
  return { attempt: null, unavailable: true };
}
/** Save before sending. Only IDs are retained, and explicit retries reuse this exact tuple. */
export function retainBrowserSubmissionAttempt(
  key: string,
  plan: BrowserCredentialPlan,
): BrowserSubmissionAttempt {
  const before = readBrowserSubmissionAttempt(key, plan);
  if (before.unavailable || !isBrowserCredentialId(plan.document_id)) {
    // i18n-exempt: internal refusal; the UI displays fixed translated recovery copy.
    throw new Error("Browser submission recovery unavailable");
  }
  if (before.attempt) return before.attempt;
  const attempt: BrowserSubmissionAttempt = {
    request_id: crypto.randomUUID(),
    document_id: plan.document_id,
    authorization_generation: plan.authorization_generation,
  };
  sessionStorage.setItem(key, JSON.stringify(attempt));
  const saved = readBrowserSubmissionAttempt(key, plan);
  if (saved.unavailable || saved.attempt?.request_id !== attempt.request_id) {
    // i18n-exempt: never send a submission without a recoverable request identity.
    throw new Error("Browser submission recovery unavailable");
  }
  return attempt;
}
