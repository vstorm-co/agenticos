import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { apiClient } from "./api-client";
import { ApiError } from "./api-error";
import {
  changeBrowserTeaching,
  discardBrowserTeaching,
  isTeachingAudienceCurrent,
  listBrowserTeachings,
  proposeBrowserTeaching,
  readBrowserTeaching,
  readTeachingPolicy,
  readTeachingPreference,
  readTeachingRun,
  readTeachingSkills,
  startBrowserTeaching,
  stopBrowserTeaching,
  updateTeachingPolicy,
  updateTeachingPreference,
} from "./browser-teaching-api";
import { useAuthStore } from "@/stores/auth-store";
import { useOrgStore } from "@/stores/org-store";
import {
  TEACHING_IDS as ids,
  teachingFixture,
  teachingReviewFixture,
  teachingSummaryFixture,
} from "@/test-utils/browser-teaching";
import type { BrowserTeaching, TeachingStart } from "@/types/browser-teaching";

vi.mock("./api-client", () => ({
  apiClient: { get: vi.fn(), post: vi.fn(), put: vi.fn(), patch: vi.fn(), delete: vi.fn() },
}));
const audience = { actor: ids.owner, organization: ids.org };
const owner = { id: ids.owner } as NonNullable<ReturnType<typeof useAuthStore.getState>["user"]>;
const start: TeachingStart = {
  request_id: ids.session,
  run_id: ids.run,
  call_id: "teaching-call",
  tab_id: "main",
  takeover_id: ids.takeover,
  title: "Monthly report demonstration",
  allowed_origins: ["https://reports.example"],
};
const addressedId = ids.session + "/?other#private";
const encodedId = encodeURIComponent(addressedId);
const readOptions = expect.objectContaining({
  signal: expect.any(AbortSignal),
  cache: "no-store",
  headers: { "X-Organization-Id": ids.org },
});
const writeOptions = expect.objectContaining({
  signal: expect.any(AbortSignal),
  cache: "no-store",
  retryAfterRefresh: false,
  headers: { "X-Organization-Id": ids.org },
});
beforeEach(() => {
  vi.resetAllMocks();
  useAuthStore.setState({ user: owner });
  useOrgStore.setState({ activeOrgId: ids.org });
  vi.mocked(apiClient.get).mockResolvedValue(teachingFixture());
  vi.mocked(apiClient.post).mockResolvedValue(teachingFixture());
  vi.mocked(apiClient.put).mockResolvedValue(teachingFixture());
  vi.mocked(apiClient.patch).mockResolvedValue(teachingFixture());
  vi.mocked(apiClient.delete).mockResolvedValue(teachingFixture());
});
afterEach(() => {
  vi.restoreAllMocks();
  useAuthStore.setState({ user: null });
  useOrgStore.setState({ activeOrgId: null });
});

describe("owner-scoped teaching reads", () => {
  it("lists only the owner collection and preserves the exact opaque cursor, including empty", async () => {
    const response = { items: [teachingSummaryFixture()], next_cursor: "next/+=opaque" };
    vi.mocked(apiClient.get).mockResolvedValue(response);
    expect(await listBrowserTeachings(audience, null)).toBe(response);
    expect(apiClient.get).toHaveBeenLastCalledWith(
      "/browser-teachings",
      expect.objectContaining({
        signal: expect.any(AbortSignal),
        cache: "no-store",
        headers: { "X-Organization-Id": ids.org },
        params: { limit: "20" },
      }),
    );
    for (const cursor of ["next/+=opaque", ""]) {
      await listBrowserTeachings(audience, cursor);
      expect(apiClient.get).toHaveBeenLastCalledWith(
        "/browser-teachings",
        expect.objectContaining({
          signal: expect.any(AbortSignal),
          cache: "no-store",
          headers: { "X-Organization-Id": ids.org },
          params: { limit: "20", cursor },
        }),
      );
    }
  });

  it("reads an encoded teaching ID and forwards caller cancellation", async () => {
    const controller = new AbortController();
    const response = teachingFixture();
    vi.mocked(apiClient.get).mockResolvedValue(response);
    expect(await readBrowserTeaching(audience, addressedId, controller.signal)).toBe(response);
    expect(apiClient.get).toHaveBeenCalledWith("/browser-teachings/" + encodedId, readOptions);
  });

  it("reads current policy, addressed agent preference, run agent and paginated skills", async () => {
    await readTeachingPolicy(audience);
    expect(apiClient.get).toHaveBeenLastCalledWith("/browser-teaching-policy", readOptions);
    await readTeachingPreference(audience, addressedId);
    expect(apiClient.get).toHaveBeenLastCalledWith(
      "/agents/" + encodedId + "/browser-teaching-preference",
      readOptions,
    );
    await readTeachingRun(audience, addressedId);
    expect(apiClient.get).toHaveBeenLastCalledWith("/runs/" + encodedId, readOptions);
    await readTeachingSkills(audience, 50);
    expect(apiClient.get).toHaveBeenLastCalledWith(
      "/skills",
      expect.objectContaining({
        signal: expect.any(AbortSignal),
        cache: "no-store",
        headers: { "X-Organization-Id": ids.org },
        params: { skip: "50", limit: "50", sort: "name" },
      }),
    );
  });
});

describe("explicit teaching consent writes", () => {
  it("starts a new capture or refinement with the exact saved body and no retry", async () => {
    await startBrowserTeaching(audience, start, null);
    expect(apiClient.post).toHaveBeenLastCalledWith("/browser-teachings", start, writeOptions);
    await startBrowserTeaching(audience, start, addressedId);
    expect(apiClient.post).toHaveBeenLastCalledWith(
      "/skills/" + encodedId + "/browser-teachings",
      start,
      writeOptions,
    );
  });

  it("uses the exact revision for pause, resume and complete review", async () => {
    for (const body of [
      { action: "pause" } as const,
      { action: "resume", takeover_id: ids.takeover } as const,
      { action: "review", review: teachingReviewFixture() } as const,
    ]) {
      await changeBrowserTeaching(audience, addressedId, 12, body);
      expect(apiClient.patch).toHaveBeenLastCalledWith(
        "/browser-teachings/" + encodedId,
        body,
        expect.objectContaining({
          signal: expect.any(AbortSignal),
          cache: "no-store",
          retryAfterRefresh: false,
          headers: { "X-Organization-Id": ids.org, "If-Match": '"12"' },
        }),
      );
    }
  });

  it("stops or discards only the addressed capture without hidden consent fields", async () => {
    await stopBrowserTeaching(audience, addressedId);
    expect(apiClient.post).toHaveBeenLastCalledWith(
      "/browser-teachings/" + encodedId + "/stop",
      {},
      writeOptions,
    );
    await discardBrowserTeaching(audience, addressedId);
    expect(apiClient.delete).toHaveBeenLastCalledWith(
      "/browser-teachings/" + encodedId,
      writeOptions,
    );
  });

  it("proposes only the explicitly chosen reviewed or budgeted assistant mode", async () => {
    for (const body of [
      { mode: "reviewed" } as const,
      { mode: "assistant", max_cost_usd: "1.234567" } as const,
    ]) {
      await proposeBrowserTeaching(audience, addressedId, 3, body);
      expect(apiClient.post).toHaveBeenLastCalledWith(
        "/browser-teachings/" + encodedId + "/propose",
        body,
        expect.objectContaining({
          signal: expect.any(AbortSignal),
          cache: "no-store",
          retryAfterRefresh: false,
          headers: { "X-Organization-Id": ids.org, "If-Match": '"3"' },
        }),
      );
    }
  });

  it("keeps policy and personal preference generation checks in their exact write bodies", async () => {
    const initial = { generation: null, enabled: true };
    const update = { generation: ids.other, enabled: false };
    await updateTeachingPolicy(audience, initial);
    expect(apiClient.put).toHaveBeenLastCalledWith(
      "/browser-teaching-policy",
      initial,
      writeOptions,
    );
    await updateTeachingPreference(audience, addressedId, update);
    expect(apiClient.put).toHaveBeenLastCalledWith(
      "/agents/" + encodedId + "/browser-teaching-preference",
      update,
      writeOptions,
    );
  });
});

describe("audience refusal, uncertainty and late completions", () => {
  it("refuses reads and writes with missing or stale owner/organization before sending", async () => {
    expect(isTeachingAudienceCurrent(audience)).toBe(true);
    expect(isTeachingAudienceCurrent(undefined)).toBe(false);
    for (const invalid of [
      { ...audience, actor: undefined },
      { ...audience, organization: null },
      { ...audience, actor: ids.other },
      { ...audience, organization: ids.other },
    ]) {
      expect(isTeachingAudienceCurrent(invalid)).toBe(false);
      await expect(readBrowserTeaching(invalid, ids.session)).rejects.toMatchObject({
        name: "AbortError",
      });
      await expect(startBrowserTeaching(invalid, start, null)).rejects.toMatchObject({
        name: "AbortError",
      });
    }
    expect(apiClient.get).not.toHaveBeenCalled();
    expect(apiClient.post).not.toHaveBeenCalled();
  });

  it.each([400, 401, 403, 404, 409, 422, 500])(
    "preserves HTTP %s refusal without retrying a consent write",
    async (status) => {
      const refusal = new ApiError(status, "Refused", {
        error: {
          code: "BAD_REQUEST",
          message: "Refused",
          details: { reason_code: "authority_changed" },
        },
      });
      vi.mocked(apiClient.post).mockRejectedValue(refusal);
      await expect(startBrowserTeaching(audience, start, null)).rejects.toBe(refusal);
      expect(apiClient.post).toHaveBeenCalledExactlyOnceWith(
        "/browser-teachings",
        start,
        writeOptions,
      );
    },
  );

  it("preserves list cursor refusal for the UI without silently restarting discovery", async () => {
    const refusal = new ApiError(400, "Refused", {
      error: {
        code: "BAD_REQUEST",
        message: "Refused",
        details: {
          reason_code: "invalid_cursor",
          fields: [{ field: "cursor", message: "Refused" }],
        },
      },
    });
    vi.mocked(apiClient.get).mockRejectedValue(refusal);
    await expect(listBrowserTeachings(audience, "")).rejects.toBe(refusal);
    expect(apiClient.get).toHaveBeenCalledTimes(1);
  });

  it.each(["read", "write"] as const)(
    "latches an A-to-B-to-A switch for an in-flight %s",
    async (kind) => {
      let resolve!: (value: BrowserTeaching) => void;
      const deferred = new Promise<BrowserTeaching>((done) => {
        resolve = done;
      });
      if (kind === "read") vi.mocked(apiClient.get).mockReturnValue(deferred);
      else vi.mocked(apiClient.post).mockReturnValue(deferred);
      const pending =
        kind === "read"
          ? readBrowserTeaching(audience, ids.session)
          : startBrowserTeaching(audience, start, null);
      const result = expect(pending).rejects.toMatchObject({ name: "AbortError" });
      useOrgStore.setState({ activeOrgId: ids.other });
      useOrgStore.setState({ activeOrgId: ids.org });
      expect(isTeachingAudienceCurrent(audience)).toBe(true);
      const options =
        kind === "read"
          ? vi.mocked(apiClient.get).mock.calls[0]![1]
          : vi.mocked(apiClient.post).mock.calls[0]![2];
      expect(options?.signal?.aborted).toBe(true);
      resolve(teachingFixture());
      await result;
    },
  );

  it("discards an owner-changed late response even when the transport ignores cancellation", async () => {
    let resolve!: (value: BrowserTeaching) => void;
    vi.mocked(apiClient.get).mockReturnValue(
      new Promise<BrowserTeaching>((done) => {
        resolve = done;
      }),
    );
    const result = expect(readBrowserTeaching(audience, ids.session)).rejects.toMatchObject({
      name: "AbortError",
    });
    useAuthStore.setState({ user: { ...owner, id: ids.other } });
    resolve(teachingFixture());
    await result;
  });

  it("honors cancellation before and during a read without replay", async () => {
    const before = new AbortController();
    before.abort();
    await expect(readTeachingPolicy(audience, before.signal)).rejects.toMatchObject({
      name: "AbortError",
    });
    expect(apiClient.get).not.toHaveBeenCalled();
    let resolve!: (value: BrowserTeaching) => void;
    vi.mocked(apiClient.get).mockReturnValue(
      new Promise<BrowserTeaching>((done) => {
        resolve = done;
      }),
    );
    const during = new AbortController();
    const result = expect(
      listBrowserTeachings(audience, null, during.signal),
    ).rejects.toMatchObject({ name: "AbortError" });
    during.abort();
    resolve(teachingFixture());
    await result;
    expect(apiClient.get).toHaveBeenCalledTimes(1);
  });
});
