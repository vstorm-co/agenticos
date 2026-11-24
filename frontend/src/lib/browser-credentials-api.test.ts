import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { apiClient } from "./api-client";
import { useAuthStore } from "@/stores/auth-store";
import { useOrgStore } from "@/stores/org-store";
import {
  browserCredentialRequest,
  isBrowserCredentialAudienceCurrent,
  readBrowserCredentialPolicy,
  readBrowserCredentialEligibility,
  updateBrowserCredentialPolicy,
  readBrowserCredentialPlan,
  confirmBrowserCredentialPlan,
  readBrowserCredentialSubmission,
  submitBrowserCredentialPlan,
} from "./browser-credentials-api";
import { BROWSER_IDS as ids } from "@/test-utils/browser-credential-fixtures";
import type { BrowserCredentialPlan } from "@/types/browser-credentials";

vi.mock("./api-client", () => ({ apiClient: { get: vi.fn(), put: vi.fn(), post: vi.fn() } }));
const audience = { actor: ids.owner, organization: ids.org };
const owner = { id: ids.owner } as NonNullable<ReturnType<typeof useAuthStore.getState>["user"]>;
const plan: BrowserCredentialPlan = {
  id: ids.plan,
  operation: "fill",
  parent_plan_id: null,
  run_id: ids.run,
  call_id: "browse-1",
  tab_id: "main",
  secret_id: ids.secret,
  authorization_generation: ids.generation,
  state: "awaiting_confirmation",
  fields: ["username", "password"],
  origin: "https://accounts.example",
  document_id: ids.document,
  expires_at: "2030-01-01T00:00:00Z",
  submission_expires_at: null,
  reason_code: null,
  output_protected: false,
};
beforeEach(() => {
  vi.clearAllMocks();
  useAuthStore.setState({ user: owner });
  useOrgStore.setState({ activeOrgId: ids.org });
});
afterEach(() => {
  useAuthStore.setState({ user: null });
  useOrgStore.setState({ activeOrgId: null });
});

describe("browser credential API boundaries", () => {
  it("reads a bare eligible list for the addressed live call without caching or issuing consent", async () => {
    const eligible = [{ id: ids.secret, authorization_generation: ids.generation }];
    vi.mocked(apiClient.get).mockResolvedValue(eligible);
    expect(await readBrowserCredentialEligibility(audience, ids.run, "call:one/two", "main")).toBe(
      eligible,
    );
    expect(apiClient.get).toHaveBeenCalledExactlyOnceWith(
      `/runs/${ids.run}/browser-credentials`,
      expect.objectContaining({
        cache: "no-store",
        headers: { "X-Organization-Id": ids.org },
        params: { call_id: "call:one/two", tab_id: "main" },
        signal: expect.any(AbortSignal),
      }),
    );
    expect(apiClient.post).not.toHaveBeenCalled();
  });
  it("reads policy and plans with no-store and the exact audience", async () => {
    vi.mocked(apiClient.get).mockResolvedValue(plan);
    await readBrowserCredentialPolicy(audience, ids.secret);
    await readBrowserCredentialPlan(audience, ids.run, ids.plan);
    expect(apiClient.get).toHaveBeenNthCalledWith(
      1,
      `/secrets/${ids.secret}/browser-policy`,
      expect.objectContaining({
        cache: "no-store",
        headers: { "X-Organization-Id": ids.org },
        signal: expect.any(AbortSignal),
      }),
    );
    expect(apiClient.get).toHaveBeenNthCalledWith(
      2,
      `/runs/${ids.run}/browser-credential-plans/${ids.plan}`,
      expect.any(Object),
    );
  });

  it("sends an exact policy generation and does not automatically retry writes", async () => {
    const body = {
      generation: ids.generation,
      mode: "personal" as const,
      agent_ids: [],
      member_ids: [],
    };
    await updateBrowserCredentialPolicy(audience, ids.secret, body);
    expect(apiClient.put).toHaveBeenCalledWith(
      `/secrets/${ids.secret}/browser-policy`,
      body,
      expect.objectContaining({ retryAfterRefresh: false }),
    );
  });

  it.each([true, false])(
    "confirms or declines only the reviewed document and generation (%s)",
    async (approve) => {
      await confirmBrowserCredentialPlan(audience, plan, approve);
      expect(apiClient.post).toHaveBeenCalledWith(
        `/runs/${ids.run}/browser-credential-plans/${ids.plan}/confirmation`,
        { document_id: ids.document, authorization_generation: ids.generation, approve },
        expect.objectContaining({ retryAfterRefresh: false }),
      );
    },
  );

  it("recovers a missing or existing child by GET without issuing consent", async () => {
    vi.mocked(apiClient.get)
      .mockResolvedValueOnce(null)
      .mockResolvedValueOnce({
        ...plan,
        id: ids.child,
        operation: "submit",
        parent_plan_id: ids.plan,
      });
    expect(await readBrowserCredentialSubmission(audience, ids.run, ids.plan)).toBeNull();
    expect(await readBrowserCredentialSubmission(audience, ids.run, ids.plan)).toMatchObject({
      id: ids.child,
    });
    expect(apiClient.get).toHaveBeenCalledWith(
      `/runs/${ids.run}/browser-credential-plans/${ids.plan}/submission`,
      expect.any(Object),
    );
    expect(apiClient.post).not.toHaveBeenCalled();
  });

  it("submits the caller's frozen request tuple without a second confirmation", async () => {
    const attempt = {
      request_id: ids.child,
      document_id: ids.document,
      authorization_generation: ids.generation,
    };
    await submitBrowserCredentialPlan(audience, ids.run, ids.plan, attempt);
    expect(apiClient.post).toHaveBeenCalledOnce();
    expect(apiClient.post).toHaveBeenCalledWith(
      `/runs/${ids.run}/browser-credential-plans/${ids.plan}/submission`,
      attempt,
      expect.objectContaining({ retryAfterRefresh: false }),
    );
  });

  it.each(["account", "organization"] as const)(
    "aborts an old %s read and refuses its delayed result",
    async (boundary) => {
      let finish!: (value: unknown) => void;
      vi.mocked(apiClient.get).mockImplementation(
        () =>
          new Promise((resolve) => {
            finish = resolve;
          }),
      );
      const pending = readBrowserCredentialPlan(audience, ids.run, ids.plan);
      const rejection = expect(pending).rejects.toMatchObject({ name: "AbortError" });
      const options = vi.mocked(apiClient.get).mock.calls[0]![1]!;
      if (boundary === "account") useAuthStore.setState({ user: { ...owner, id: "someone-else" } });
      else useOrgStore.setState({ activeOrgId: "another-org" });
      expect(options.signal?.aborted).toBe(true);
      finish(plan);
      await rejection;
    },
  );

  it("honors caller cancellation before and during a read", async () => {
    const cancelled = new AbortController();
    cancelled.abort();
    await expect(
      readBrowserCredentialPolicy(audience, ids.secret, cancelled.signal),
    ).rejects.toMatchObject({ name: "AbortError" });
    expect(apiClient.get).not.toHaveBeenCalled();
    const controller = new AbortController();
    let finish!: () => void;
    const send = vi.fn(
      () =>
        new Promise<void>((resolve) => {
          finish = resolve;
        }),
    );
    const pending = browserCredentialRequest(audience, send, controller.signal);
    const rejection = expect(pending).rejects.toMatchObject({ name: "AbortError" });
    controller.abort();
    finish();
    await rejection;
  });

  it("refuses an absent or stale audience before any request", async () => {
    expect(isBrowserCredentialAudienceCurrent(undefined)).toBe(false);
    expect(isBrowserCredentialAudienceCurrent({ actor: undefined, organization: ids.org })).toBe(
      false,
    );
    expect(isBrowserCredentialAudienceCurrent({ actor: ids.owner, organization: null })).toBe(
      false,
    );
    useAuthStore.setState({ user: null });
    await expect(readBrowserCredentialPolicy(audience, ids.secret)).rejects.toMatchObject({
      name: "AbortError",
    });
    expect(apiClient.get).not.toHaveBeenCalled();
  });

  it("preserves API refusals without retrying a request", async () => {
    const failure = new Error("unavailable");
    vi.mocked(apiClient.post).mockRejectedValue(failure);
    await expect(confirmBrowserCredentialPlan(audience, plan, true)).rejects.toBe(failure);
    expect(apiClient.post).toHaveBeenCalledOnce();
  });
});
