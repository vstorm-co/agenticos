import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { BROWSER_IDS as ids } from "@/test-utils/browser-credential-fixtures";
import {
  browserPlanFixture,
  browserSubmissionFixture,
} from "@/test-utils/browser-credential-plan-fixtures";
import type { BrowserCredentialContinuation } from "@/types/browser-credential-continuation";
import {
  browserContinuationAttemptKey,
  readBrowserContinuationAttempt,
  retainBrowserContinuationAttempt,
  type BrowserContinuationAttempt,
} from "./browser-credential-continuation-attempts";

const audience = { actor: ids.owner, organization: ids.org };
const source = browserSubmissionFixture(browserPlanFixture());
const continuationId = "99999999-9999-4999-8999-999999999999";
const otherId = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa";
const observation = {
  id: continuationId,
  document_id: ids.document,
} as BrowserCredentialContinuation;
const prepareKey = browserContinuationAttemptKey(audience, source);
const confirmKey = browserContinuationAttemptKey(audience, source, observation);
const prepare: BrowserContinuationAttempt = { kind: "prepare", request_id: continuationId };
const confirm: BrowserContinuationAttempt = {
  kind: "confirm",
  continuation_id: continuationId,
  document_id: ids.document,
  authorization_generation: ids.generation,
  approve: true,
  keep_signed_in: false,
};

beforeEach(() => sessionStorage.clear());
afterEach(() => {
  vi.restoreAllMocks();
  sessionStorage.clear();
});

describe("immutable protected-continuation attempts", () => {
  it("separates account, tenant, source identity, generation and exact confirmation observation", () => {
    const keys = [
      prepareKey,
      confirmKey,
      browserContinuationAttemptKey({ ...audience, actor: otherId }, source),
      browserContinuationAttemptKey({ ...audience, organization: otherId }, source),
      ...(
        [
          "run_id",
          "id",
          "parent_plan_id",
          "call_id",
          "tab_id",
          "secret_id",
          "authorization_generation",
        ] as const
      ).map((field) => browserContinuationAttemptKey(audience, { ...source, [field]: otherId })),
      browserContinuationAttemptKey(audience, source, { ...observation, id: otherId }),
      browserContinuationAttemptKey(audience, source, { ...observation, document_id: otherId }),
    ];
    expect(new Set(keys).size).toBe(keys.length);
    expect(prepareKey).toContain("t3os:browser-continuation:v1:");
    expect(
      browserContinuationAttemptKey(audience, {
        ...source,
        state: "unknown",
        expires_at: "2040-01-01",
      }),
    ).toBe(prepareKey);
  });

  it.each([
    ["prepare", prepareKey, prepare],
    ["confirm", confirmKey, confirm],
  ] as const)(
    "retains and reads the exact %s tuple without adding values or clearing it",
    (kind, key, attempt) => {
      const remove = vi.spyOn(sessionStorage, "removeItem");
      expect(readBrowserContinuationAttempt(key, kind)).toEqual({
        attempt: null,
        unavailable: false,
      });
      expect(retainBrowserContinuationAttempt(key, attempt)).toBe(true);
      expect(readBrowserContinuationAttempt(key, kind)).toEqual({ attempt, unavailable: false });
      expect(JSON.parse(sessionStorage.getItem(key)!)).toEqual(attempt);
      expect(remove).not.toHaveBeenCalled();
    },
  );

  it("does not expose a retained preparation to another audience's key", () => {
    expect(retainBrowserContinuationAttempt(prepareKey, prepare)).toBe(true);
    expect(
      readBrowserContinuationAttempt(
        browserContinuationAttemptKey({ ...audience, organization: otherId }, source),
        "prepare",
      ),
    ).toEqual({ attempt: null, unavailable: false });
    expect(readBrowserContinuationAttempt(prepareKey, "prepare").attempt).toEqual(prepare);
  });

  it.each([
    "{",
    "null",
    "[]",
    "1",
    '"text"',
    JSON.stringify({ kind: "unexpected", request_id: continuationId }),
    JSON.stringify({ ...prepare, request_id: "invalid" }),
    JSON.stringify({ ...prepare, cookies: "PRIVATE_COOKIE" }),
    JSON.stringify({ ...confirm, continuation_id: "invalid" }),
    JSON.stringify({ ...confirm, document_id: "invalid" }),
    JSON.stringify({ ...confirm, authorization_generation: "invalid" }),
    JSON.stringify({ ...confirm, approve: "true" }),
    JSON.stringify({ ...confirm, keep_signed_in: 1 }),
    JSON.stringify({ ...confirm, raw_value: "PRIVATE_VALUE" }),
    " ".repeat(2049),
  ])("treats corrupt, extra-field or oversized storage as uncertainty %#", (raw) => {
    sessionStorage.setItem(prepareKey, raw);
    const set = vi.spyOn(sessionStorage, "setItem");
    const remove = vi.spyOn(sessionStorage, "removeItem");
    expect(readBrowserContinuationAttempt(prepareKey, "prepare")).toEqual({
      attempt: null,
      unavailable: true,
    });
    expect(retainBrowserContinuationAttempt(prepareKey, prepare)).toBe(false);
    expect(sessionStorage.getItem(prepareKey)).toBe(raw);
    expect(set).not.toHaveBeenCalled();
    expect(remove).not.toHaveBeenCalled();
  });

  it("accepts a bounded stored tuple and refuses another operation kind without releasing it", () => {
    const raw = JSON.stringify(confirm).padEnd(2048, " ");
    sessionStorage.setItem(confirmKey, raw);
    expect(readBrowserContinuationAttempt(confirmKey, "confirm")).toEqual({
      attempt: confirm,
      unavailable: false,
    });
    expect(readBrowserContinuationAttempt(confirmKey, "prepare")).toEqual({
      attempt: null,
      unavailable: true,
    });
    expect(sessionStorage.getItem(confirmKey)).toBe(raw);
  });

  it.each([
    { kind: "prepare", request_id: "invalid" },
    { ...prepare, unexpected: true },
    { ...confirm, document_id: null },
    { ...confirm, authorization_generation: null },
    { ...confirm, approve: null },
    { ...confirm, keep_signed_in: null },
  ])("refuses an invalid new tuple before touching storage %#", (attempt) => {
    const get = vi.spyOn(sessionStorage, "getItem");
    const set = vi.spyOn(sessionStorage, "setItem");
    expect(
      retainBrowserContinuationAttempt(
        prepareKey,
        attempt as unknown as BrowserContinuationAttempt,
      ),
    ).toBe(false);
    expect(get).not.toHaveBeenCalled();
    expect(set).not.toHaveBeenCalled();
  });

  it("reuses an identical attempt without rewriting or renewing it", () => {
    sessionStorage.setItem(
      confirmKey,
      JSON.stringify({
        keep_signed_in: false,
        approve: true,
        authorization_generation: ids.generation,
        document_id: ids.document,
        continuation_id: continuationId,
        kind: "confirm",
      }),
    );
    const raw = sessionStorage.getItem(confirmKey);
    const set = vi.spyOn(sessionStorage, "setItem");
    expect(retainBrowserContinuationAttempt(confirmKey, confirm)).toBe(true);
    expect(sessionStorage.getItem(confirmKey)).toBe(raw);
    expect(set).not.toHaveBeenCalled();
  });

  it.each([
    { ...confirm, continuation_id: otherId },
    { ...confirm, document_id: otherId },
    { ...confirm, authorization_generation: otherId },
    { ...confirm, approve: false },
    { ...confirm, keep_signed_in: true },
    prepare,
  ] satisfies BrowserContinuationAttempt[])(
    "never replaces an unresolved consent tuple %#",
    (other) => {
      expect(retainBrowserContinuationAttempt(confirmKey, confirm)).toBe(true);
      const raw = sessionStorage.getItem(confirmKey);
      const set = vi.spyOn(sessionStorage, "setItem");
      expect(retainBrowserContinuationAttempt(confirmKey, other)).toBe(false);
      expect(sessionStorage.getItem(confirmKey)).toBe(raw);
      expect(set).not.toHaveBeenCalled();
    },
  );

  it("never replaces an uncertain preparation with a new request ID", () => {
    expect(retainBrowserContinuationAttempt(prepareKey, prepare)).toBe(true);
    expect(
      retainBrowserContinuationAttempt(prepareKey, { kind: "prepare", request_id: otherId }),
    ).toBe(false);
    expect(readBrowserContinuationAttempt(prepareKey, "prepare").attempt).toEqual(prepare);
  });

  it("refuses unavailable storage without releasing or rewriting an attempt", () => {
    const set = vi.spyOn(sessionStorage, "setItem");
    vi.spyOn(sessionStorage, "getItem").mockImplementation(() => {
      throw new Error("Unavailable storage");
    });
    expect(readBrowserContinuationAttempt(prepareKey, "prepare")).toEqual({
      attempt: null,
      unavailable: true,
    });
    expect(retainBrowserContinuationAttempt(prepareKey, prepare)).toBe(false);
    expect(set).not.toHaveBeenCalled();
  });

  it("refuses a failed persistence write", () => {
    vi.spyOn(sessionStorage, "setItem").mockImplementation(() => {
      throw new Error("Storage full");
    });
    expect(retainBrowserContinuationAttempt(prepareKey, prepare)).toBe(false);
  });

  it.each([null, "{", JSON.stringify({ kind: "prepare", request_id: otherId })])(
    "refuses a missing, malformed or changed readback after writing %#",
    (raw) => {
      vi.spyOn(sessionStorage, "getItem").mockReturnValueOnce(null).mockReturnValueOnce(raw);
      expect(retainBrowserContinuationAttempt(prepareKey, prepare)).toBe(false);
    },
  );

  it("refuses a readback failure after the write without claiming a recoverable attempt", () => {
    vi.spyOn(sessionStorage, "getItem")
      .mockReturnValueOnce(null)
      .mockImplementationOnce(() => {
        throw new Error("Readback unavailable");
      });
    expect(retainBrowserContinuationAttempt(prepareKey, prepare)).toBe(false);
  });
});
