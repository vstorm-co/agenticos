import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { apiClient } from "./api-client";
import { ApiError } from "./api-error";
import { useAuthStore } from "@/stores/auth-store";
import { useOrgStore } from "@/stores/org-store";
import { BROWSER_IDS as ids } from "@/test-utils/browser-credential-fixtures";
import {
  browserPlanFixture,
  browserSubmissionFixture,
} from "@/test-utils/browser-credential-plan-fixtures";
import type { BrowserCredentialPlan } from "@/types/browser-credentials";
import type {
  BrowserContinuationConfirmation,
  BrowserCredentialContinuation,
} from "@/types/browser-credential-continuation";
import {
  confirmBrowserContinuation,
  readBrowserContinuation,
  requestBrowserContinuation,
} from "./browser-credential-continuation-api";

vi.mock("./api-client", () => ({ apiClient: { get: vi.fn(), post: vi.fn() } }));
const audience = { actor: ids.owner, organization: ids.org };
const owner = { id: ids.owner } as NonNullable<ReturnType<typeof useAuthStore.getState>["user"]>;
const continuationId = "99999999-9999-4999-8999-999999999999";
const otherId = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa";
const endpoint = "/runs/" + ids.run + "/browser-credential-plans/" + ids.child + "/continuation";
const decision: BrowserContinuationConfirmation = {
  document_id: ids.document,
  authorization_generation: ids.generation,
  approve: true,
  keep_signed_in: false,
};
let source: BrowserCredentialPlan;
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

beforeEach(() => {
  vi.resetAllMocks();
  source = browserSubmissionFixture(browserPlanFixture());
  useAuthStore.setState({ user: owner });
  useOrgStore.setState({ activeOrgId: ids.org });
});
afterEach(() => {
  vi.restoreAllMocks();
  useAuthStore.setState({ user: null });
  useOrgStore.setState({ activeOrgId: null });
});

describe("protected continuation API consent and recovery", () => {
  it("recovers an absent or existing receipt using only no-store GET reads", async () => {
    const row = receipt();
    vi.mocked(apiClient.get).mockResolvedValueOnce(null).mockResolvedValueOnce(row);
    expect(await readBrowserContinuation(audience, source)).toBeNull();
    expect(await readBrowserContinuation(audience, source)).toEqual(row);
    expect(apiClient.get).toHaveBeenCalledTimes(2);
    expect(apiClient.get).toHaveBeenLastCalledWith(
      endpoint,
      expect.objectContaining({
        cache: "no-store",
        headers: { "X-Organization-Id": ids.org },
        signal: expect.any(AbortSignal),
      }),
    );
    expect(apiClient.post).not.toHaveBeenCalled();
  });

  it("requests only preparation with the caller's retained request ID and no automatic consent", async () => {
    vi.mocked(apiClient.post).mockResolvedValue(
      receipt({ state: "requested", origin: null, document_id: null }),
    );
    const body = {
      request_id: continuationId,
      approve: true,
      keep_signed_in: true,
      url: "https://untrusted.example",
    };
    expect(await requestBrowserContinuation(audience, source, body)).toMatchObject({
      id: continuationId,
      state: "requested",
    });
    expect(apiClient.post).toHaveBeenCalledExactlyOnceWith(
      endpoint,
      { request_id: continuationId },
      expect.objectContaining({
        cache: "no-store",
        retryAfterRefresh: false,
        headers: { "X-Organization-Id": ids.org },
        signal: expect.any(AbortSignal),
      }),
    );
    expect(apiClient.get).not.toHaveBeenCalled();
  });

  it.each([true, false])(
    "keeps approval=%s separate from the exact remember choice",
    async (approve) => {
      for (const keep_signed_in of [true, false]) {
        vi.mocked(apiClient.post)
          .mockClear()
          .mockResolvedValue(
            receipt({
              state: approve ? "approved" : "declined",
              keep_signed_in,
            }),
          );
        const body = { ...decision, approve, keep_signed_in, unexpected: "PRIVATE_VALUE" };
        const result = await confirmBrowserContinuation(audience, source, receipt(), body);
        expect(result.state).toBe(approve ? "approved" : "declined");
        expect(result.keep_signed_in).toBe(keep_signed_in);
        expect(apiClient.post).toHaveBeenCalledExactlyOnceWith(
          endpoint + "/" + continuationId + "/confirmation",
          {
            document_id: ids.document,
            authorization_generation: ids.generation,
            approve,
            keep_signed_in,
          },
          expect.objectContaining({
            retryAfterRefresh: false,
            cache: "no-store",
            headers: { "X-Organization-Id": ids.org },
            signal: expect.any(AbortSignal),
          }),
        );
      }
    },
  );

  it.each(["read", "prepare", "confirm"] as const)(
    "%s refuses an unsubmitted source before any transport request",
    async (operation) => {
      const bad = { ...source, state: "unknown" as const };
      const request =
        operation === "read"
          ? readBrowserContinuation(audience, bad)
          : operation === "prepare"
            ? requestBrowserContinuation(audience, bad, { request_id: continuationId })
            : confirmBrowserContinuation(audience, bad, receipt(), decision);
      await expect(request).rejects.toThrow("Browser continuation source unavailable");
      expect(apiClient.get).not.toHaveBeenCalled();
      expect(apiClient.post).not.toHaveBeenCalled();
    },
  );

  it("refuses an invalid preparation request ID before sending", async () => {
    await expect(
      requestBrowserContinuation(audience, source, { request_id: "invalid" }),
    ).rejects.toThrow("request identity unavailable");
    expect(apiClient.post).not.toHaveBeenCalled();
  });

  it("does not settle a preparation with a different returned request ID", async () => {
    vi.mocked(apiClient.post).mockResolvedValue(receipt({ id: otherId }));
    await expect(
      requestBrowserContinuation(audience, source, { request_id: continuationId }),
    ).rejects.toThrow("request identity mismatch");
    expect(apiClient.post).toHaveBeenCalledOnce();
  });

  it.each([
    "requested",
    "preparing",
    "approved",
    "claimed",
    "continued",
    "refused",
    "expired",
    "declined",
    "unknown",
  ] as const)("never re-confirms a %s receipt", async (state) => {
    await expect(
      confirmBrowserContinuation(audience, source, receipt({ state }), decision),
    ).rejects.toThrow("decision unavailable");
    expect(apiClient.post).not.toHaveBeenCalled();
  });

  it.each([
    { document_id: otherId },
    { authorization_generation: otherId },
    { approve: "true" },
    { keep_signed_in: null },
  ])("refuses changed or malformed decision data before transport %#", async (change) => {
    await expect(
      confirmBrowserContinuation(audience, source, receipt(), {
        ...decision,
        ...change,
      } as unknown as BrowserContinuationConfirmation),
    ).rejects.toThrow("decision unavailable");
    expect(apiClient.post).not.toHaveBeenCalled();
  });

  it("refuses a foreign current receipt before sending its confirmation", async () => {
    await expect(
      confirmBrowserContinuation(audience, source, receipt({ user_id: otherId }), decision),
    ).rejects.toThrow("decision unavailable");
    expect(apiClient.post).not.toHaveBeenCalled();
  });

  it.each([{ id: otherId }, { document_id: otherId }, { keep_signed_in: true }])(
    "does not settle a confirmation whose returned identity or persistence choice differs %#",
    async (change) => {
      vi.mocked(apiClient.post).mockResolvedValue(
        receipt({ state: "approved", keep_signed_in: false, ...change }),
      );
      await expect(
        confirmBrowserContinuation(audience, source, receipt(), decision),
      ).rejects.toThrow("decision identity mismatch");
      expect(apiClient.post).toHaveBeenCalledOnce();
    },
  );

  it("keeps a terminal uncertain receipt without converting it to a second decision", async () => {
    const unknown = receipt({ state: "unknown", reason_code: "uncertain_continuation" });
    vi.mocked(apiClient.post).mockResolvedValue(unknown);
    expect(await confirmBrowserContinuation(audience, source, receipt(), decision)).toEqual(
      unknown,
    );
    expect(apiClient.post).toHaveBeenCalledOnce();
    expect(apiClient.get).not.toHaveBeenCalled();
  });

  it.each([undefined, {}, []])(
    "rejects malformed transport data %# using only the fixed refusal",
    async (value) => {
      vi.mocked(apiClient.get).mockResolvedValue(value);
      await expect(readBrowserContinuation(audience, source)).rejects.toThrow(
        "Browser continuation response unavailable",
      );
      expect(apiClient.post).not.toHaveBeenCalled();
    },
  );

  it("rejects a foreign or unprotected receipt and unexpected browser content before returning it", async () => {
    for (const row of [
      receipt({ organization_id: otherId }),
      { ...receipt(), cookies: "PRIVATE_COOKIE" },
      { ...receipt(), output_protected: false },
    ]) {
      vi.mocked(apiClient.get).mockResolvedValue(row);
      await expect(readBrowserContinuation(audience, source)).rejects.toThrow(
        "Browser continuation response unavailable",
      );
    }
    expect(apiClient.post).not.toHaveBeenCalled();
  });

  it.each(["account", "organization"] as const)(
    "rejects a stale %s before any read or write",
    async (boundary) => {
      if (boundary === "account") useAuthStore.setState({ user: null });
      else useOrgStore.setState({ activeOrgId: otherId });
      await expect(readBrowserContinuation(audience, source)).rejects.toMatchObject({
        name: "AbortError",
      });
      await expect(
        requestBrowserContinuation(audience, source, { request_id: continuationId }),
      ).rejects.toMatchObject({ name: "AbortError" });
      await expect(
        confirmBrowserContinuation(audience, source, receipt(), decision),
      ).rejects.toMatchObject({ name: "AbortError" });
      expect(apiClient.get).not.toHaveBeenCalled();
      expect(apiClient.post).not.toHaveBeenCalled();
    },
  );

  it.each([
    ["read", "account"],
    ["prepare", "account"],
    ["confirm", "account"],
    ["read", "organization"],
    ["prepare", "organization"],
    ["confirm", "organization"],
  ] as const)(
    "refuses a late %s result even if the %s switches away and back",
    async (operation, boundary) => {
      let finish!: (value: unknown) => void;
      if (operation === "read")
        vi.mocked(apiClient.get).mockImplementation(
          () =>
            new Promise((resolve) => {
              finish = resolve;
            }),
        );
      else
        vi.mocked(apiClient.post).mockImplementation(
          () =>
            new Promise((resolve) => {
              finish = resolve;
            }),
        );
      const pending =
        operation === "read"
          ? readBrowserContinuation(audience, source)
          : operation === "prepare"
            ? requestBrowserContinuation(audience, source, { request_id: continuationId })
            : confirmBrowserContinuation(audience, source, receipt(), decision);
      const rejected = expect(pending).rejects.toMatchObject({ name: "AbortError" });
      const options =
        operation === "read"
          ? vi.mocked(apiClient.get).mock.calls[0]![1]!
          : vi.mocked(apiClient.post).mock.calls[0]![2]!;
      if (boundary === "account") {
        useAuthStore.setState({ user: { ...owner, id: otherId } });
        useAuthStore.setState({ user: owner });
      } else {
        useOrgStore.setState({ activeOrgId: otherId });
        useOrgStore.setState({ activeOrgId: ids.org });
      }
      expect(options.signal?.aborted).toBe(true);
      finish(receipt());
      await rejected;
      expect(operation === "read" ? apiClient.get : apiClient.post).toHaveBeenCalledOnce();
    },
  );

  it("honors caller cancellation before and during read recovery", async () => {
    const controller = new AbortController();
    controller.abort();
    await expect(
      readBrowserContinuation(audience, source, controller.signal),
    ).rejects.toMatchObject({ name: "AbortError" });
    expect(apiClient.get).not.toHaveBeenCalled();
    const next = new AbortController();
    let finish!: (value: unknown) => void;
    vi.mocked(apiClient.get).mockImplementation(
      () =>
        new Promise((resolve) => {
          finish = resolve;
        }),
    );
    const pending = readBrowserContinuation(audience, source, next.signal);
    const rejected = expect(pending).rejects.toMatchObject({ name: "AbortError" });
    next.abort();
    finish(receipt());
    await rejected;
    expect(apiClient.post).not.toHaveBeenCalled();
  });

  it.each([400, 401, 403, 404, 409, 500])(
    "retains transport refusal %s without replaying a consent write",
    async (status) => {
      const refusal = new ApiError(status, "PRIVATE_TRANSPORT_REFUSAL");
      vi.mocked(apiClient.post).mockRejectedValue(refusal);
      await expect(confirmBrowserContinuation(audience, source, receipt(), decision)).rejects.toBe(
        refusal,
      );
      expect(apiClient.post).toHaveBeenCalledOnce();
      expect(apiClient.get).not.toHaveBeenCalled();
    },
  );
});
