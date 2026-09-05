import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { toast } from "sonner";

import { useImpersonation } from "./use-impersonation";
import { apiClient } from "@/lib/api-client";
import { useAuthStore } from "@/stores/auth-store";
import type { User } from "@/types";

const push = vi.fn();
const reauthenticate = vi.fn();

vi.mock("next/navigation", () => ({ useRouter: () => ({ push }) }));
vi.mock("@/hooks/use-auth", () => ({ useReauthenticate: () => reauthenticate }));
vi.mock("@/lib/api-client", () => ({ apiClient: { delete: vi.fn() } }));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

const IN_TEN_MINUTES = new Date(Date.now() + 10 * 60 * 1000).toISOString();

const ACTING_AS: User = {
  id: "u-1",
  email: "customer@example.com",
  is_active: true,
  created_at: "2026-07-01T00:00:00Z",
  impersonation: {
    session_id: "s-1",
    impersonator: { id: "a-1", email: "admin@example.com" },
    expires_at: IN_TEN_MINUTES,
  },
};

function signedInAs(user: User | null) {
  useAuthStore.setState({ user, isAuthenticated: user !== null });
}

beforeEach(() => {
  vi.clearAllMocks();
  reauthenticate.mockResolvedValue(undefined);
  vi.mocked(apiClient.delete).mockResolvedValue({ ok: true });
});

afterEach(() => {
  vi.useRealTimers();
  signedInAs(null);
});

/**
 * The one way out of acting as somebody else.
 *
 * What is pinned is the order and the destination: the backend is told first, so
 * the row is closed and the end is audited; then the identity is re-read, which is
 * what adopts the administrator back and empties the cache that was the other
 * account's; and the administrator lands on a page that is theirs. Expiry takes
 * the same exit on its own, because the alternative is a page of somebody else's
 * that has started answering 404 under a banner that still says "acting as".
 */
describe("useImpersonation", () => {
  it("reads who is being acted as from the session the store already holds", () => {
    signedInAs(ACTING_AS);

    const { result } = renderHook(() => useImpersonation());

    expect(result.current.impersonation?.impersonator.email).toBe("admin@example.com");
    expect(result.current.actingAs?.email).toBe("customer@example.com");
  });

  it("is nobody acting as anybody for an ordinary session", () => {
    signedInAs({ ...ACTING_AS, impersonation: null });

    const { result } = renderHook(() => useImpersonation());

    expect(result.current.impersonation).toBeNull();
    expect(result.current.actingAs).toBeNull();
  });

  it("ends by telling the backend, re-reading who we are, and going home", async () => {
    signedInAs(ACTING_AS);
    const { result } = renderHook(() => useImpersonation());

    await act(() => result.current.end());

    expect(apiClient.delete).toHaveBeenCalledWith("/auth/impersonation");
    expect(reauthenticate).toHaveBeenCalledTimes(1);
    expect(vi.mocked(apiClient.delete).mock.invocationCallOrder[0]).toBeLessThan(
      reauthenticate.mock.invocationCallOrder[0]!,
    );
    expect(toast.success).toHaveBeenCalledWith("Impersonation ended. You are yourself again.");
    expect(push).toHaveBeenCalledWith("/admin/users");
    expect(result.current.ending).toBe(false);
  });

  it("still re-reads who we are when the end was refused", async () => {
    // Refused means over already - ended from another tab, or expired. The row
    // is closed either way, and the identity read is what puts the
    // administrator back.
    signedInAs(ACTING_AS);
    vi.mocked(apiClient.delete).mockRejectedValue(new Error("401"));
    const { result } = renderHook(() => useImpersonation());

    await act(() => result.current.end());

    expect(reauthenticate).toHaveBeenCalledTimes(1);
    expect(push).toHaveBeenCalledWith("/admin/users");
  });

  it("marks the end as in flight while the backend is being told", async () => {
    signedInAs(ACTING_AS);
    let release: (value: unknown) => void = () => {};
    vi.mocked(apiClient.delete).mockReturnValue(
      new Promise((resolve) => {
        release = resolve;
      }),
    );
    const { result } = renderHook(() => useImpersonation());

    let pending: Promise<void> = Promise.resolve();
    act(() => {
      pending = result.current.end();
    });

    expect(result.current.ending).toBe(true);
    await act(async () => {
      release({ ok: true });
      await pending;
    });
    expect(result.current.ending).toBe(false);
  });

  it("takes the exit on its own when the window closes", async () => {
    vi.useFakeTimers();
    signedInAs({
      ...ACTING_AS,
      impersonation: {
        ...ACTING_AS.impersonation!,
        expires_at: new Date(Date.now() + 5_000).toISOString(),
      },
    });
    renderHook(() => useImpersonation());

    await act(async () => {
      await vi.advanceTimersByTimeAsync(4_999);
    });
    expect(apiClient.delete).not.toHaveBeenCalled();

    await act(async () => {
      await vi.advanceTimersByTimeAsync(1);
    });
    expect(apiClient.delete).toHaveBeenCalledWith("/auth/impersonation");
    expect(reauthenticate).toHaveBeenCalledTimes(1);
  });

  it("takes the exit at once for a window that has already closed", async () => {
    // A tab reopened after lunch: the store still says "acting as", the token
    // would be refused on the next request, and waiting for nothing helps nobody.
    vi.useFakeTimers();
    signedInAs({
      ...ACTING_AS,
      impersonation: {
        ...ACTING_AS.impersonation!,
        expires_at: new Date(Date.now() - 60_000).toISOString(),
      },
    });
    renderHook(() => useImpersonation());

    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });

    expect(apiClient.delete).toHaveBeenCalledWith("/auth/impersonation");
  });

  it("sets no timer for an ordinary session", async () => {
    vi.useFakeTimers();
    signedInAs({ ...ACTING_AS, impersonation: null });
    renderHook(() => useImpersonation());

    await act(async () => {
      await vi.advanceTimersByTimeAsync(60 * 60 * 1000);
    });

    expect(apiClient.delete).not.toHaveBeenCalled();
  });
});
