import { afterEach, describe, expect, it, vi } from "vitest";
import {
  browserCredentialDeadlineLive,
  browserCredentialFields,
  browserCredentialOrigin,
  browserCredentialPlanMatches,
  browserCredentialSubmissionMatches,
  browserSubmissionKey,
  currentBrowserCredential,
  readBrowserSubmissionAttempt,
  retainBrowserSubmissionAttempt,
} from "./browser-credential-review";
import {
  browserPlanFixture,
  browserEligibilityFixture,
  browserSubmissionFixture,
} from "@/test-utils/browser-credential-plan-fixtures";
import { BROWSER_IDS as ids } from "@/test-utils/browser-credential-fixtures";

afterEach(() => {
  vi.restoreAllMocks();
  sessionStorage.clear();
});
describe("credential review boundaries", () => {
  it.each([
    null,
    "",
    "not a URL",
    "http://accounts.example",
    "https://user:password@accounts.example",
    "https://accounts.example/path",
    "https://accounts.example?token=private",
    "https://*.example",
    "https://accounts.example/",
  ])("never makes %s a canonical handoff destination", (value) => {
    expect(browserCredentialOrigin(value)).toBeNull();
  });
  it("keeps the exact canonical HTTPS origin, including a non-default approved port", () => {
    expect(browserCredentialOrigin("https://accounts.example:8443")).toBe(
      "https://accounts.example:8443",
    );
  });
  it.each(
    [
      null,
      "password",
      [],
      ["password", "password"],
      ["unknown"],
      [
        "name",
        "email",
        "phone",
        "address_line1",
        "address_line2",
        "city",
        "region",
        "postal_code",
        "country",
        "password",
      ],
    ].map((fields) => ({ fields })),
  )("refuses unverifiable or repeated selected fields $fields", ({ fields }) => {
    expect(browserCredentialFields(browserPlanFixture({ fields: fields as never }))).toBeNull();
  });
  it("checks the exact addressed run, call, tab and operation before showing a receipt", () => {
    const plan = browserPlanFixture();
    expect(browserCredentialPlanMatches(plan, ids.run, ids.plan, "browser-call", "main")).toBe(
      true,
    );
    expect(browserCredentialPlanMatches(plan, ids.child, ids.plan)).toBe(false);
    expect(browserCredentialPlanMatches(plan, ids.run, ids.child)).toBe(false);
    expect(browserCredentialPlanMatches(plan, ids.run, ids.plan, "other")).toBe(false);
    expect(browserCredentialPlanMatches(plan, ids.run, ids.plan, undefined, "other")).toBe(false);
    expect(
      browserCredentialPlanMatches({ ...plan, operation: "future" as never }, ids.run, ids.plan),
    ).toBe(false);
    expect(
      browserCredentialPlanMatches({ ...plan, parent_plan_id: ids.child }, ids.run, ids.plan),
    ).toBe(false);
  });
  it("requires current eligibility to match both the secret and its generation, selected fields and exact origin", () => {
    const plan = browserPlanFixture(),
      entry = browserEligibilityFixture();
    expect(currentBrowserCredential(plan, [entry])).toBe(entry);
    expect(currentBrowserCredential(plan, [{ ...entry, id: ids.child }])).toBeNull();
    expect(
      currentBrowserCredential(plan, [{ ...entry, authorization_generation: ids.child }]),
    ).toBeNull();
    expect(currentBrowserCredential(plan, [{ ...entry, name: "" }])).toBeNull();
    expect(
      currentBrowserCredential(plan, [
        { ...entry, browser: { ...entry.browser, available_fields: ["username"] } },
      ]),
    ).toBeNull();
    expect(currentBrowserCredential(plan, { items: [entry] } as never)).toBeNull();
    const profile = {
      ...entry,
      kind: "browser_profile" as const,
      browser: { ...entry.browser, available_fields: ["name"] },
    };
    expect(currentBrowserCredential({ ...plan, fields: ["name"] }, [profile])).toBe(profile);
    expect(currentBrowserCredential(plan, [{ ...entry, kind: "api_key" as never }])).toBeNull();
  });
  it("accepts only the submission of this same filled document and generation", () => {
    const parent = browserPlanFixture({ state: "filled" }),
      child = browserSubmissionFixture(parent);
    expect(browserCredentialSubmissionMatches(parent, child)).toBe(true);
    expect(
      browserCredentialSubmissionMatches(parent, { ...child, parent_plan_id: ids.child }),
    ).toBe(false);
    expect(browserCredentialSubmissionMatches(parent, { ...child, document_id: ids.child })).toBe(
      false,
    );
    expect(
      browserCredentialSubmissionMatches(parent, { ...child, authorization_generation: ids.child }),
    ).toBe(false);
    expect(browserCredentialSubmissionMatches(parent, { ...child, secret_id: ids.child })).toBe(
      false,
    );
    expect(
      browserCredentialSubmissionMatches(parent, { ...child, origin: "https://other.example" }),
    ).toBe(false);
  });
  it("uses exact provider deadlines and never treats a missing or invalid time as live", () => {
    const now = Date.now();
    expect(browserCredentialDeadlineLive(new Date(now + 1).toISOString(), now)).toBe(true);
    expect(browserCredentialDeadlineLive(new Date(now).toISOString(), now)).toBe(false);
    expect(browserCredentialDeadlineLive(null, now)).toBe(false);
    expect(browserCredentialDeadlineLive("invalid", now)).toBe(false);
  });
});
describe("recoverable submission identity", () => {
  const audience = { actor: ids.owner, organization: ids.org };
  it("keeps one IDs-only request tuple across reloads and separates accounts, organizations and generations", () => {
    const plan = browserPlanFixture(),
      key = browserSubmissionKey(audience, plan);
    const first = retainBrowserSubmissionAttempt(key, plan);
    expect(retainBrowserSubmissionAttempt(key, plan)).toEqual(first);
    expect(readBrowserSubmissionAttempt(key, plan)).toEqual({ attempt: first, unavailable: false });
    expect(Object.keys(first).sort()).toEqual([
      "authorization_generation",
      "document_id",
      "request_id",
    ]);
    expect(browserSubmissionKey({ ...audience, actor: ids.child }, plan)).not.toBe(key);
    expect(browserSubmissionKey({ ...audience, organization: ids.child }, plan)).not.toBe(key);
    expect(
      browserSubmissionKey(audience, { ...plan, authorization_generation: ids.child }),
    ).not.toBe(key);
  });
  it.each([
    "broken JSON",
    "null",
    "{}",
    JSON.stringify({
      request_id: ids.child,
      document_id: ids.child,
      authorization_generation: ids.generation,
    }),
  ])("does not replace an unresolvable earlier attempt %s", (raw) => {
    const plan = browserPlanFixture(),
      key = browserSubmissionKey(audience, plan);
    sessionStorage.setItem(key, raw);
    expect(readBrowserSubmissionAttempt(key, plan)).toEqual({ attempt: null, unavailable: true });
    expect(() => retainBrowserSubmissionAttempt(key, plan)).toThrow();
    expect(sessionStorage.getItem(key)).toBe(raw);
  });
  it("refuses to send a token which the browser did not retain", () => {
    const plan = browserPlanFixture(),
      key = browserSubmissionKey(audience, plan);
    vi.spyOn(sessionStorage, "setItem").mockImplementation(() => {});
    expect(() => retainBrowserSubmissionAttempt(key, plan)).toThrow();
  });
  it("does not infer an empty slot when storage reads are denied", () => {
    const plan = browserPlanFixture(),
      key = browserSubmissionKey(audience, plan);
    vi.spyOn(sessionStorage, "getItem").mockImplementation(() => {
      throw new Error("denied");
    });
    expect(readBrowserSubmissionAttempt(key, plan).unavailable).toBe(true);
  });
});
