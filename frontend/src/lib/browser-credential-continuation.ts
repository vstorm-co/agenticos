import { z } from "zod";
import type { BrowserCredentialAudience } from "./browser-credentials-api";
import {
  browserCredentialOrigin,
  browserCredentialPlanMatches,
  isBrowserCredentialId,
} from "./browser-credential-review";
import type { BrowserCredentialPlan } from "@/types/browser-credentials";
import {
  BROWSER_CONTINUATION_REASONS,
  BROWSER_CONTINUATION_STATES,
  type BrowserCredentialContinuation,
} from "@/types/browser-credential-continuation";

const uuid = z.string().refine(isBrowserCredentialId);
const liveId = z.string().min(1).max(200);
const receiptSchema: z.ZodType<BrowserCredentialContinuation> = z
  .object({
    id: uuid,
    organization_id: uuid,
    user_id: uuid,
    run_id: uuid,
    source_submission_id: uuid,
    source_fill_id: uuid,
    source_call_id: liveId,
    source_tab_id: liveId,
    secret_id: uuid,
    authorization_generation: uuid,
    state: z.enum(BROWSER_CONTINUATION_STATES),
    origin: z.string().nullable(),
    document_id: uuid.nullable(),
    expires_at: z.string().refine((value) => Number.isFinite(Date.parse(value))),
    keep_signed_in: z.boolean().nullable(),
    saved_sign_in_id: uuid.nullable(),
    continuation_call_id: liveId.nullable(),
    continuation_tab_id: liveId.nullable(),
    reason_code: z.enum(BROWSER_CONTINUATION_REASONS).nullable(),
    output_protected: z.literal(true),
  })
  .strict();

export function isBrowserContinuationSource(source: BrowserCredentialPlan): boolean {
  return (
    browserCredentialPlanMatches(source, source.run_id, source.id) &&
    source.operation === "submit" &&
    source.state === "submitted" &&
    source.output_protected === true &&
    browserCredentialOrigin(source.origin) !== null &&
    source.call_id.length <= 200 &&
    source.tab_id.length <= 200
  );
}

/** Reject foreign or malformed receipts before they can enter an audience's cache. */
export function decodeBrowserContinuation(
  value: unknown,
  audience: BrowserCredentialAudience,
  source: BrowserCredentialPlan,
): BrowserCredentialContinuation | null {
  const parsed = receiptSchema.safeParse(value);
  if (!parsed.success || !isBrowserContinuationSource(source)) return null;
  const row = parsed.data;
  if (
    row.organization_id !== audience.organization ||
    row.user_id !== audience.actor ||
    row.run_id !== source.run_id ||
    row.source_submission_id !== source.id ||
    row.source_fill_id !== source.parent_plan_id ||
    row.source_call_id !== source.call_id ||
    row.source_tab_id !== source.tab_id ||
    row.secret_id !== source.secret_id ||
    row.authorization_generation !== source.authorization_generation ||
    (row.origin !== null && row.origin !== source.origin)
  )
    return null;
  if (
    ["awaiting_confirmation", "approved", "claimed", "continued"].includes(row.state) &&
    (!row.document_id || !row.origin)
  )
    return null;
  if (
    row.state === "continued" &&
    (!isBrowserCredentialId(row.continuation_call_id) ||
      !isBrowserCredentialId(row.continuation_tab_id) ||
      row.continuation_call_id === source.call_id ||
      row.continuation_tab_id === source.tab_id ||
      row.keep_signed_in === null ||
      (row.saved_sign_in_id !== null) !== row.keep_signed_in)
  )
    return null;
  if (row.saved_sign_in_id !== null && (row.state !== "continued" || row.keep_signed_in !== true))
    return null;
  return row;
}

export function browserContinuationPending(row: BrowserCredentialContinuation | null | undefined) {
  return (
    !!row &&
    ["requested", "preparing", "awaiting_confirmation", "approved", "claimed"].includes(row.state)
  );
}

/** A new address is usable only after the server establishes its protected context. */
export function browserContinuationHref(row: BrowserCredentialContinuation): string | null {
  return row.state === "continued" && row.continuation_call_id
    ? `/browse/${encodeURIComponent(row.run_id)}/${encodeURIComponent(row.continuation_call_id)}`
    : null;
}
