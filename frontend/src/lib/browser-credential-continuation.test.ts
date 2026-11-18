import { describe, expect, it } from "vitest";
import { BROWSER_IDS as ids } from "@/test-utils/browser-credential-fixtures";
import {
  browserPlanFixture,
  browserSubmissionFixture,
} from "@/test-utils/browser-credential-plan-fixtures";
import type { BrowserCredentialPlan } from "@/types/browser-credentials";
import {
  BROWSER_CONTINUATION_REASONS,
  BROWSER_CONTINUATION_STATES,
  type BrowserCredentialContinuation,
} from "@/types/browser-credential-continuation";
import {
  browserContinuationHref,
  browserContinuationPending,
  decodeBrowserContinuation,
  isBrowserContinuationSource,
} from "./browser-credential-continuation";

const audience = { actor: ids.owner, organization: ids.org };
const continuationId = "99999999-9999-4999-8999-999999999999";
const newCall = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa";
const newTab = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb";
const savedSignIn = "cccccccc-cccc-4ccc-8ccc-cccccccccccc";
const source = browserSubmissionFixture(browserPlanFixture());
function receipt(
  overrides: Partial<BrowserCredentialContinuation> = {},
): BrowserCredentialContinuation {
  return {
    id: continuationId,
    organization_id: ids.org,
    user_id: ids.owner,
    run_id: ids.run,
    source_submission_id: ids.child,
    source_fill_id: ids.plan,
    source_call_id: source.call_id,
    source_tab_id: source.tab_id,
    secret_id: ids.secret,
    authorization_generation: ids.generation,
    state: "awaiting_confirmation",
    origin: source.origin,
    document_id: ids.document,
    expires_at: "2030-01-01T00:00:00Z",
    keep_signed_in: null,
    saved_sign_in_id: null,
    continuation_call_id: null,
    continuation_tab_id: null,
    reason_code: null,
    output_protected: true,
    ...overrides,
  };
}
function continued(overrides: Partial<BrowserCredentialContinuation> = {}) {
  return receipt({
    state: "continued",
    keep_signed_in: false,
    continuation_call_id: newCall,
    continuation_tab_id: newTab,
    ...overrides,
  });
}

describe("protected continuation receipt boundaries", () => {
  it("requires a known submitted protected child of a valid fill", () => {
    expect(isBrowserContinuationSource(source)).toBe(true);
    expect(decodeBrowserContinuation(receipt(), audience, source)).toEqual(receipt());
  });

  it.each([
    ["fill", { operation: "fill", parent_plan_id: null }],
    ["unknown effect", { state: "unknown" }],
    ["claimed effect", { state: "claimed" }],
    ["refused effect", { state: "refused" }],
    ["missing parent", { parent_plan_id: null }],
    ["invalid parent", { parent_plan_id: "not-a-uuid" }],
    ["invalid run", { run_id: "not-a-uuid" }],
    ["invalid source", { id: "not-a-uuid" }],
    ["invalid secret", { secret_id: "not-a-uuid" }],
    ["invalid generation", { authorization_generation: "not-a-uuid" }],
    ["unprotected output", { output_protected: false }],
    ["missing origin", { origin: null }],
    ["HTTP origin", { origin: "http://accounts.example" }],
    ["private path", { origin: "https://accounts.example/private" }],
    ["empty call", { call_id: "" }],
    ["empty tab", { tab_id: "" }],
    ["overlong call", { call_id: "a".repeat(201) }],
    ["overlong tab", { tab_id: "a".repeat(201) }],
  ] satisfies Array<[string, Partial<BrowserCredentialPlan>]>)(
    "refuses a source with %s",
    (_name, change) => {
      const wrong = { ...source, ...change };
      expect(isBrowserContinuationSource(wrong)).toBe(false);
      expect(decodeBrowserContinuation(receipt(), audience, wrong)).toBeNull();
    },
  );

  it("accepts bounded opaque source call/tab identifiers without reconstructing a URL", () => {
    const addressed = { ...source, call_id: "a".repeat(200), tab_id: "tab:one/two" };
    expect(isBrowserContinuationSource(addressed)).toBe(true);
    expect(
      decodeBrowserContinuation(
        receipt({ source_call_id: addressed.call_id, source_tab_id: addressed.tab_id }),
        audience,
        addressed,
      ),
    ).not.toBeNull();
  });

  it.each(BROWSER_CONTINUATION_STATES)("decodes the closed %s state", (state) => {
    const value = state === "continued" ? continued() : receipt({ state });
    expect(decodeBrowserContinuation(value, audience, source)).toEqual(value);
  });

  it.each(BROWSER_CONTINUATION_REASONS)("retains the closed reason %s", (reason_code) => {
    const value = receipt({ state: "refused", reason_code });
    expect(decodeBrowserContinuation(value, audience, source)).toEqual(value);
  });

  it.each([
    null,
    undefined,
    [],
    "receipt",
    1,
    {},
    { ...receipt(), state: "signed_in" },
    { ...receipt(), reason_code: "raw_native_error" },
    { ...receipt(), output_protected: false },
    { ...receipt(), expires_at: "not-a-date" },
  ])("refuses malformed or unprotected receipt %#", (value) => {
    expect(decodeBrowserContinuation(value, audience, source)).toBeNull();
  });

  it.each(["cookies", "html", "url", "screenshot", "raw_error"])(
    "refuses an extra %s field instead of putting browser data in the cache",
    (field) => {
      expect(
        decodeBrowserContinuation(
          { ...receipt(), [field]: "PRIVATE_BROWSER_DATA" },
          audience,
          source,
        ),
      ).toBeNull();
    },
  );

  it.each([
    "id",
    "organization_id",
    "user_id",
    "run_id",
    "source_submission_id",
    "source_fill_id",
    "secret_id",
    "authorization_generation",
    "document_id",
  ] as const)("refuses a malformed %s identity", (field) =>
    expect(
      decodeBrowserContinuation({ ...receipt(), [field]: "invalid-id" }, audience, source),
    ).toBeNull(),
  );

  it.each([
    "organization_id",
    "user_id",
    "run_id",
    "source_submission_id",
    "source_fill_id",
    "secret_id",
    "authorization_generation",
  ] as const)("refuses a valid but foreign %s identity", (field) =>
    expect(
      decodeBrowserContinuation({ ...receipt(), [field]: continuationId }, audience, source),
    ).toBeNull(),
  );

  it.each([
    { source_call_id: "another-call" },
    { source_tab_id: "another-tab" },
    { origin: "https://different.example" },
    { source_call_id: "" },
    { source_tab_id: "x".repeat(201) },
  ])("refuses a changed source address %#", (change) => {
    expect(decodeBrowserContinuation({ ...receipt(), ...change }, audience, source)).toBeNull();
  });

  it("does not admit a receipt to an absent account or organization", () => {
    expect(
      decodeBrowserContinuation(receipt(), { ...audience, actor: undefined }, source),
    ).toBeNull();
    expect(
      decodeBrowserContinuation(receipt(), { ...audience, organization: null }, source),
    ).toBeNull();
  });

  it.each(["requested", "preparing", "refused", "expired", "declined", "unknown"] as const)(
    "allows a value-free %s receipt before or without a confirmed document",
    (state) => {
      const value = receipt({ state, origin: null, document_id: null });
      expect(decodeBrowserContinuation(value, audience, source)).toEqual(value);
    },
  );

  it.each(["awaiting_confirmation", "approved", "claimed", "continued"] as const)(
    "%s requires the reviewed origin and document",
    (state) => {
      const value = state === "continued" ? continued() : receipt({ state });
      expect(decodeBrowserContinuation({ ...value, origin: null }, audience, source)).toBeNull();
      expect(
        decodeBrowserContinuation({ ...value, document_id: null }, audience, source),
      ).toBeNull();
    },
  );

  it.each([
    { continuation_call_id: null },
    { continuation_call_id: "not-a-uuid" },
    { continuation_tab_id: null },
    { continuation_tab_id: "not-a-uuid" },
    { keep_signed_in: null },
    { keep_signed_in: true, saved_sign_in_id: null },
    { keep_signed_in: false, saved_sign_in_id: savedSignIn },
  ])(
    "does not expose a continued context with incomplete or contradictory evidence %#",
    (change) => {
      expect(decodeBrowserContinuation(continued(change), audience, source)).toBeNull();
    },
  );

  it.each(["call", "tab"] as const)("requires a fresh continuation %s identity", (same) => {
    const previous = { ...source, call_id: ids.plan, tab_id: ids.child };
    const value = continued({
      source_call_id: previous.call_id,
      source_tab_id: previous.tab_id,
      ...(same === "call"
        ? { continuation_call_id: previous.call_id }
        : { continuation_tab_id: previous.tab_id }),
    });
    expect(decodeBrowserContinuation(value, audience, previous)).toBeNull();
  });

  it("reports remembered sign-in only for the completed explicitly persistent choice", () => {
    const value = continued({ keep_signed_in: true, saved_sign_in_id: savedSignIn });
    expect(decodeBrowserContinuation(value, audience, source)).toEqual(value);
    expect(
      decodeBrowserContinuation(
        receipt({ keep_signed_in: true, saved_sign_in_id: savedSignIn }),
        audience,
        source,
      ),
    ).toBeNull();
  });

  it.each(BROWSER_CONTINUATION_STATES)("bounds polling and link availability for %s", (state) => {
    const value = state === "continued" ? continued() : receipt({ state });
    expect(browserContinuationPending(value)).toBe(
      ["requested", "preparing", "awaiting_confirmation", "approved", "claimed"].includes(state),
    );
    expect(browserContinuationHref(value)).toBe(
      state === "continued" ? "/browse/" + ids.run + "/" + newCall : null,
    );
  });

  it("does not poll an absent receipt or invent an address for an incomplete result", () => {
    expect(browserContinuationPending(null)).toBe(false);
    expect(browserContinuationPending(undefined)).toBe(false);
    expect(browserContinuationHref(continued({ continuation_call_id: null }))).toBeNull();
  });
});
