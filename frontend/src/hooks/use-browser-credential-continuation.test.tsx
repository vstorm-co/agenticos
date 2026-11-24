import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useBrowserCredentialContinuation } from "./use-browser-credential-continuation";
import { apiClient } from "@/lib/api-client";
import { ApiError } from "@/lib/api-error";
import { qk } from "@/lib/query-keys";
import { useAuthStore } from "@/stores/auth-store";
import { useOrgStore } from "@/stores/org-store";
import {
  CONTINUATION_IDS as ids,
  browserContinuationFixture,
  continuationSourceFixture,
} from "@/test-utils/browser-credential-continuation-fixtures";
import type { BrowserCredentialContinuation } from "@/types/browser-credential-continuation";

vi.mock("@/lib/api-client", () => ({ apiClient: { get: vi.fn(), post: vi.fn() } }));
const source = continuationSourceFixture();
const key = qk.browserContinuations.receipt(ids.owner, ids.org, source);
const clients: QueryClient[] = [];
function setup(enabled = true) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  clients.push(client);
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
  return {
    client,
    wrapper,
    ...renderHook(() => useBrowserCredentialContinuation(source, enabled), { wrapper }),
  };
}
function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason: unknown) => void;
  const promise = new Promise<T>((yes, no) => {
    resolve = yes;
    reject = no;
  });
  return { promise, resolve, reject };
}
beforeEach(() => {
  vi.clearAllMocks();
  useAuthStore.setState({ user: { id: ids.owner } as never, accessToken: "test-token" });
  useOrgStore.setState({ activeOrgId: ids.org });
  vi.mocked(apiClient.get).mockResolvedValue(null as never);
});
afterEach(() => {
  cleanup();
  for (const client of clients.splice(0)) client.clear();
  vi.restoreAllMocks();
  vi.useRealTimers();
  useAuthStore.setState({ user: null });
  useOrgStore.setState({ activeOrgId: null });
});

describe("continuation authority cache", () => {
  it("does not revive refused evidence when an in-flight read is cancelled during immediate remount", async () => {
    const observed = browserContinuationFixture();
    const pendingWrite = deferred<unknown>(),
      oldRead = deferred<unknown>(),
      freshRead = deferred<unknown>();
    vi.mocked(apiClient.get).mockResolvedValue(observed as never);
    vi.mocked(apiClient.post).mockReturnValue(pendingWrite.promise as never);
    const first = setup();
    await waitFor(() => expect(first.result.current.current).toBe(true));
    let work!: Promise<unknown>, read!: Promise<unknown>;
    act(() => {
      work = first.result.current.confirm
        .mutateAsync({
          row: observed,
          body: {
            document_id: ids.continuationDocument,
            authorization_generation: ids.generation,
            approve: true,
            keep_signed_in: false,
          },
        })
        .catch(() => undefined);
    });
    await waitFor(() => expect(apiClient.post).toHaveBeenCalledTimes(1));
    vi.mocked(apiClient.get).mockReturnValueOnce(oldRead.promise as never);
    act(() => {
      read = first.result.current.refresh();
    });
    await waitFor(() => expect(apiClient.get).toHaveBeenCalledTimes(2));
    await act(async () => {
      pendingWrite.reject(new ApiError(403, "authority refused"));
      await work;
    });
    await waitFor(() => expect(first.result.current.unavailable).toBe(true));
    vi.mocked(apiClient.get).mockReturnValueOnce(freshRead.promise as never);
    first.unmount();
    const second = renderHook(() => useBrowserCredentialContinuation(source, true), {
      wrapper: first.wrapper,
    });
    try {
      expect(second.result.current.row).toBeUndefined();
      expect(second.result.current.current).toBe(false);
    } finally {
      await act(async () => {
        oldRead.resolve(observed);
        freshRead.resolve(observed);
        await read;
      });
    }
    await waitFor(() => expect(second.result.current.row?.state).toBe("awaiting_confirmation"));
  });
  it("preserves a newer terminal receipt after an obsolete confirmation transport error", async () => {
    const observed = browserContinuationFixture();
    const pending = deferred<unknown>();
    vi.mocked(apiClient.get).mockResolvedValue(observed as never);
    vi.mocked(apiClient.post).mockReturnValue(pending.promise as never);
    const { result } = setup();
    await waitFor(() => expect(result.current.current).toBe(true));
    let work!: Promise<unknown>;
    act(() => {
      work = result.current.confirm
        .mutateAsync({
          row: observed,
          body: {
            document_id: ids.continuationDocument,
            authorization_generation: ids.generation,
            approve: true,
            keep_signed_in: false,
          },
        })
        .catch(() => undefined);
    });
    await waitFor(() => expect(apiClient.post).toHaveBeenCalledTimes(1));
    vi.mocked(apiClient.get).mockResolvedValue(
      browserContinuationFixture({ state: "unknown" }) as never,
    );
    await act(async () => {
      await result.current.refresh();
    });
    await waitFor(() => expect(result.current.row?.state).toBe("unknown"));
    await act(async () => {
      pending.reject(new ApiError(503, "lost acknowledgement"));
      await work;
    });
    await waitFor(() => expect(result.current.needsRecovery).toBe(true));
    expect(result.current.row?.state).toBe("unknown");
    expect(result.current.unavailable).toBe(false);
    expect(result.current.current).toBe(false);
    expect(apiClient.post).toHaveBeenCalledTimes(1);
  });
  it("shares the post-failure read requirement with another mounted observer", async () => {
    const observed = browserContinuationFixture();
    const pending = deferred<unknown>();
    vi.mocked(apiClient.get).mockResolvedValue(observed as never);
    vi.mocked(apiClient.post).mockReturnValue(pending.promise as never);
    const first = setup();
    const second = renderHook(() => useBrowserCredentialContinuation(source, true), {
      wrapper: first.wrapper,
    });
    await waitFor(() =>
      expect(first.result.current.current && second.result.current.current).toBe(true),
    );
    let work!: Promise<unknown>;
    act(() => {
      work = first.result.current.confirm
        .mutateAsync({
          row: observed,
          body: {
            document_id: ids.continuationDocument,
            authorization_generation: ids.generation,
            approve: true,
            keep_signed_in: false,
          },
        })
        .catch(() => undefined);
    });
    await waitFor(() => expect(apiClient.post).toHaveBeenCalledTimes(1));
    await act(async () => {
      await second.result.current.refresh();
    });
    await act(async () => {
      pending.reject(new TypeError("lost acknowledgement"));
      await work;
    });
    await waitFor(() =>
      expect(first.result.current.needsRecovery && second.result.current.needsRecovery).toBe(true),
    );
    expect(first.result.current.current).toBe(false);
    expect(second.result.current.current).toBe(false);
    expect(second.result.current.row?.state).toBe("awaiting_confirmation");
    await act(async () => {
      await second.result.current.refresh();
    });
    await waitFor(() =>
      expect(first.result.current.current && second.result.current.current).toBe(true),
    );
    expect(first.result.current.needsRecovery || second.result.current.needsRecovery).toBe(false);
    expect(apiClient.post).toHaveBeenCalledTimes(1);
  });
  it("does not turn an obsolete GET transport failure into a query error over a newer write", async () => {
    const pendingRead = deferred<unknown>();
    vi.mocked(apiClient.post).mockResolvedValue(
      browserContinuationFixture({ state: "requested", origin: null, document_id: null }) as never,
    );
    const { result } = setup();
    await waitFor(() => expect(result.current.current).toBe(true));
    vi.mocked(apiClient.get).mockReturnValueOnce(pendingRead.promise as never);
    let read!: Promise<unknown>;
    act(() => {
      read = result.current.refresh();
    });
    await waitFor(() => expect(apiClient.get).toHaveBeenCalledTimes(2));
    await act(async () => {
      await result.current.prepare.mutateAsync({ request_id: ids.continuation });
    });
    await waitFor(() => expect(result.current.row?.state).toBe("requested"));
    await act(async () => {
      pendingRead.reject(new ApiError(503, "transport unavailable"));
      await read;
    });
    expect(result.current.row?.state).toBe("requested");
    expect(result.current.receipt.isError).toBe(false);
    expect(result.current.unavailable).toBe(false);
  });
  it.each([400, 401, 403, 404, 409, 422])(
    "still scrubs a late actual %s refusal despite a newer receipt",
    async (status) => {
      const observed = browserContinuationFixture();
      const pending = deferred<unknown>();
      vi.mocked(apiClient.get).mockResolvedValue(observed as never);
      vi.mocked(apiClient.post).mockReturnValue(pending.promise as never);
      const { result, client } = setup();
      await waitFor(() => expect(result.current.current).toBe(true));
      let work!: Promise<unknown>;
      act(() => {
        work = result.current.confirm
          .mutateAsync({
            row: observed,
            body: {
              document_id: ids.continuationDocument,
              authorization_generation: ids.generation,
              approve: true,
              keep_signed_in: false,
            },
          })
          .catch(() => undefined);
      });
      await waitFor(() => expect(apiClient.post).toHaveBeenCalledTimes(1));
      vi.mocked(apiClient.get).mockResolvedValue(
        browserContinuationFixture({ state: "unknown" }) as never,
      );
      await act(async () => {
        await result.current.refresh();
      });
      await waitFor(() => expect(result.current.row?.state).toBe("unknown"));
      await act(async () => {
        pending.reject(
          new ApiError(status, "authority refused", {
            error: {
              code: "BAD_REQUEST",
              message: "authority refused",
              details: { reason_code: "authority_changed" },
            },
          }),
        );
        await work;
      });
      await waitFor(() => expect(result.current.unavailable).toBe(true));
      expect(result.current.row).toBeUndefined();
      expect(client.getQueryData(key)).toMatchObject({ refused: true, row: null });
      await act(async () => {
        await result.current.refresh();
      });
      await waitFor(() => expect(result.current.row?.state).toBe("unknown"));
    },
  );
  it("still scrubs a late GET authority refusal after a newer write", async () => {
    const pendingRead = deferred<unknown>();
    vi.mocked(apiClient.post).mockResolvedValue(
      browserContinuationFixture({ state: "requested", origin: null, document_id: null }) as never,
    );
    const { result } = setup();
    await waitFor(() => expect(result.current.current).toBe(true));
    vi.mocked(apiClient.get).mockReturnValueOnce(pendingRead.promise as never);
    let read!: Promise<unknown>;
    act(() => {
      read = result.current.refresh();
    });
    await waitFor(() => expect(apiClient.get).toHaveBeenCalledTimes(2));
    await act(async () => {
      await result.current.prepare.mutateAsync({ request_id: ids.continuation });
    });
    await waitFor(() => expect(result.current.row?.state).toBe("requested"));
    await act(async () => {
      pendingRead.reject(new ApiError(403, "authority refused"));
      await read;
    });
    await waitFor(() => expect(result.current.unavailable).toBe(true));
    expect(result.current.row).toBeUndefined();
  });
  it("does not publish an old audience's write failure into a new audience", async () => {
    const observed = browserContinuationFixture();
    const pending = deferred<unknown>();
    vi.mocked(apiClient.get).mockResolvedValue(observed as never);
    vi.mocked(apiClient.post).mockReturnValue(pending.promise as never);
    const { result } = setup();
    await waitFor(() => expect(result.current.current).toBe(true));
    let work!: Promise<unknown>;
    act(() => {
      work = result.current.confirm
        .mutateAsync({
          row: observed,
          body: {
            document_id: ids.continuationDocument,
            authorization_generation: ids.generation,
            approve: true,
            keep_signed_in: false,
          },
        })
        .catch(() => undefined);
    });
    await waitFor(() => expect(apiClient.post).toHaveBeenCalledTimes(1));
    vi.mocked(apiClient.get).mockResolvedValue(
      browserContinuationFixture({ user_id: ids.other }) as never,
    );
    act(() => useAuthStore.setState({ user: { id: ids.other } as never }));
    await waitFor(() => expect(result.current.row?.user_id).toBe(ids.other));
    await act(async () => {
      pending.reject(new ApiError(403, "old audience refused"));
      await work;
    });
    expect(result.current.row?.user_id).toBe(ids.other);
    expect(result.current.unavailable).toBe(false);
  });
  it("does not reuse an observation generation after the same receipt cache is evicted and remounted", async () => {
    const observed = browserContinuationFixture();
    const pending = deferred<unknown>();
    vi.mocked(apiClient.get).mockResolvedValue(observed as never);
    vi.mocked(apiClient.post).mockReturnValue(pending.promise as never);
    const first = setup();
    await waitFor(() => expect(first.result.current.current).toBe(true));
    let work!: Promise<BrowserCredentialContinuation>;
    act(() => {
      work = first.result.current.confirm.mutateAsync({
        row: observed,
        body: {
          document_id: ids.continuationDocument,
          authorization_generation: ids.generation,
          approve: true,
          keep_signed_in: false,
        },
      });
    });
    await waitFor(() => expect(apiClient.post).toHaveBeenCalledTimes(1));
    first.unmount();
    await waitFor(() => expect(first.client.getQueryState(key)).toBeUndefined());
    vi.mocked(apiClient.get).mockResolvedValue(
      browserContinuationFixture({ state: "unknown" }) as never,
    );
    const second = renderHook(() => useBrowserCredentialContinuation(source, true), {
      wrapper: first.wrapper,
    });
    await waitFor(() => expect(second.result.current.row?.state).toBe("unknown"));
    await act(async () => {
      pending.resolve(browserContinuationFixture({ state: "approved", keep_signed_in: false }));
      await work;
    });
    expect(JSON.stringify(first.client.getQueryData(key))).toContain('"state":"unknown"');
    expect(second.result.current.row?.state).toBe("unknown");
  });
  it("preserves a terminal GET that settles before an older confirmation acknowledgement", async () => {
    const observed = browserContinuationFixture();
    const pending = deferred<unknown>();
    vi.mocked(apiClient.get).mockResolvedValue(observed as never);
    vi.mocked(apiClient.post).mockReturnValue(pending.promise as never);
    const { result, client } = setup();
    await waitFor(() => expect(result.current.current).toBe(true));
    let work!: Promise<BrowserCredentialContinuation>;
    act(() => {
      work = result.current.confirm.mutateAsync({
        row: observed,
        body: {
          document_id: ids.continuationDocument,
          authorization_generation: ids.generation,
          approve: true,
          keep_signed_in: false,
        },
      });
    });
    await waitFor(() => expect(apiClient.post).toHaveBeenCalledTimes(1));
    vi.mocked(apiClient.get).mockResolvedValue(
      browserContinuationFixture({
        state: "unknown",
        reason_code: "uncertain_continuation",
      }) as never,
    );
    await act(async () => {
      await result.current.refresh();
    });
    await waitFor(() => expect(result.current.row?.state).toBe("unknown"));
    await act(async () => {
      pending.resolve(browserContinuationFixture({ state: "approved", keep_signed_in: false }));
      await work;
    });
    await waitFor(() => expect(result.current.confirm.isSuccess).toBe(true));
    expect(JSON.stringify(client.getQueryData(key))).toContain('"state":"unknown"');
    expect(result.current.row?.state).toBe("unknown");
  });
  it("preserves a refusal fence across a successful recovery before an older write completes", async () => {
    const pending = deferred<unknown>();
    vi.mocked(apiClient.post).mockReturnValue(pending.promise as never);
    const { result, client } = setup();
    await waitFor(() => expect(result.current.current).toBe(true));
    let work!: Promise<BrowserCredentialContinuation>;
    act(() => {
      work = result.current.prepare.mutateAsync({ request_id: ids.continuation });
    });
    await waitFor(() => expect(apiClient.post).toHaveBeenCalledTimes(1));
    vi.mocked(apiClient.get).mockRejectedValue(new ApiError(403, "denied"));
    await act(async () => {
      await result.current.refresh();
    });
    await waitFor(() => expect(result.current.unavailable).toBe(true));
    vi.mocked(apiClient.get).mockResolvedValue(browserContinuationFixture() as never);
    await act(async () => {
      await result.current.refresh();
    });
    await waitFor(() => expect(result.current.row?.state).toBe("awaiting_confirmation"));
    await act(async () => {
      pending.resolve(
        browserContinuationFixture({ state: "requested", origin: null, document_id: null }),
      );
      await work;
    });
    await waitFor(() => expect(result.current.prepare.isSuccess).toBe(true));
    expect(JSON.stringify(client.getQueryData(key))).toContain('"state":"awaiting_confirmation"');
    expect(result.current.row?.state).toBe("awaiting_confirmation");
  });
  it.each(["disabled", "actor", "organization"])(
    "does not read or refresh when %s is unavailable",
    async (missing) => {
      if (missing === "actor") useAuthStore.setState({ user: null });
      if (missing === "organization") useOrgStore.setState({ activeOrgId: null });
      const { result } = setup(missing !== "disabled");
      await act(async () => {
        await result.current.refresh();
      });
      expect(result.current.ready).toBe(false);
      expect(result.current.row).toBeUndefined();
      expect(apiClient.get).not.toHaveBeenCalled();
    },
  );
  it("keeps a fresh denial authoritative over a preparation that started earlier", async () => {
    const pending = deferred<unknown>();
    vi.mocked(apiClient.post).mockReturnValue(pending.promise as never);
    const { result, client } = setup();
    await waitFor(() => expect(result.current.current).toBe(true));
    let work!: Promise<BrowserCredentialContinuation>;
    act(() => {
      work = result.current.prepare.mutateAsync({ request_id: ids.continuation });
    });
    await waitFor(() => expect(apiClient.post).toHaveBeenCalledTimes(1));
    vi.mocked(apiClient.get).mockRejectedValue(new ApiError(403, "denied"));
    await act(async () => {
      await result.current.refresh();
    });
    await waitFor(() => expect(result.current.row).toBeUndefined());
    expect(result.current.unavailable).toBe(true);
    await act(async () => {
      pending.resolve(
        browserContinuationFixture({ state: "requested", document_id: null, origin: null }),
      );
      await work;
    });
    expect(result.current.row).toBeUndefined();
    expect(client.getQueryData(key)).toEqual({
      generation: expect.any(Number),
      refused: true,
      recoveryRequired: false,
      row: null,
    });
    vi.mocked(apiClient.get).mockResolvedValue(browserContinuationFixture() as never);
    await act(async () => {
      await result.current.refresh();
    });
    await waitFor(() => expect(result.current.row?.state).toBe("awaiting_confirmation"));
  });
  it("does not let an older successful GET erase a later write refusal", async () => {
    const pendingWrite = deferred<unknown>();
    const pendingRead = deferred<unknown>();
    vi.mocked(apiClient.post).mockReturnValue(pendingWrite.promise as never);
    const { result, client } = setup();
    await waitFor(() => expect(result.current.current).toBe(true));
    let work!: Promise<unknown>;
    act(() => {
      work = result.current.prepare
        .mutateAsync({ request_id: ids.continuation })
        .catch(() => undefined);
    });
    await waitFor(() => expect(apiClient.post).toHaveBeenCalledTimes(1));
    vi.mocked(apiClient.get).mockReturnValueOnce(pendingRead.promise as never);
    let read!: Promise<unknown>;
    act(() => {
      read = result.current.refresh();
    });
    await waitFor(() => expect(apiClient.get).toHaveBeenCalledTimes(2));
    await act(async () => {
      pendingWrite.reject(new ApiError(403, "denied"));
      await work;
    });
    await waitFor(() => expect(result.current.row).toBeUndefined());
    await act(async () => {
      pendingRead.resolve(browserContinuationFixture());
      await read;
    });
    expect(result.current.row).toBeUndefined();
    expect(client.getQueryData(key)).toEqual({
      generation: expect.any(Number),
      refused: true,
      recoveryRequired: false,
      row: null,
    });
  });
  it("retains an acknowledged preparation when an older read later finishes", async () => {
    const pendingRead = deferred<unknown>();
    vi.mocked(apiClient.post).mockResolvedValue(
      browserContinuationFixture({ state: "requested", document_id: null, origin: null }) as never,
    );
    const { result } = setup();
    await waitFor(() => expect(result.current.current).toBe(true));
    vi.mocked(apiClient.get).mockReturnValueOnce(pendingRead.promise as never);
    let read!: Promise<unknown>;
    act(() => {
      read = result.current.refresh();
    });
    await waitFor(() => expect(apiClient.get).toHaveBeenCalledTimes(2));
    await act(async () => {
      await result.current.prepare.mutateAsync({ request_id: ids.continuation });
    });
    await waitFor(() => expect(result.current.row?.state).toBe("requested"));
    await act(async () => {
      pendingRead.resolve(null);
      await read;
    });
    expect(result.current.row?.state).toBe("requested");
    expect(result.current.unavailable).toBe(false);
  });
  it("invalidates saved sign-in metadata only after an acknowledged saved continuation", async () => {
    const row = browserContinuationFixture();
    vi.mocked(apiClient.get).mockResolvedValue(row as never);
    vi.mocked(apiClient.post).mockResolvedValue(
      browserContinuationFixture({
        state: "continued",
        keep_signed_in: true,
        saved_sign_in_id: ids.saved,
        continuation_call_id: ids.continuationCall,
        continuation_tab_id: ids.continuationTab,
      }) as never,
    );
    const { result, client } = setup();
    const invalidate = vi.spyOn(client, "invalidateQueries");
    await waitFor(() => expect(result.current.current).toBe(true));
    await act(async () => {
      await result.current.confirm.mutateAsync({
        row,
        body: {
          document_id: ids.continuationDocument,
          authorization_generation: ids.generation,
          approve: true,
          keep_signed_in: true,
        },
      });
    });
    expect(invalidate).toHaveBeenCalledWith({ queryKey: qk.browserSignIns.mine(ids.org) });
    await waitFor(() => expect(result.current.row?.state).toBe("continued"));
  });
  it("aborts a request across an actor change even if the actor changes back before the response", async () => {
    const pending = deferred<unknown>();
    vi.mocked(apiClient.get).mockReturnValueOnce(pending.promise as never);
    const { result } = setup();
    await waitFor(() => expect(apiClient.get).toHaveBeenCalledTimes(1));
    act(() => {
      useAuthStore.setState({ user: { id: ids.other } as never });
      useAuthStore.setState({ user: { id: ids.owner } as never });
    });
    await act(async () => {
      pending.resolve(browserContinuationFixture());
    });
    await waitFor(() => expect(result.current.unavailable).toBe(true));
    expect(result.current.row).toBeUndefined();
  });
});
