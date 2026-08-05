import { render, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AuthGuard } from "./auth-guard";
import { apiClient } from "@/lib/api-client";
import { ROUTES } from "@/lib/constants";
import { useAuthStore } from "@/stores";

/**
 * What the guard hands to the login page when it turns a visitor away.
 *
 * The adoption side of the guard is covered by
 * `session-adoption.integration.test.tsx`; this file covers the refusal. The
 * `returnTo` it builds is the only copy of where the visitor was headed, so
 * anything it drops - the fragment is the easy one to drop, `pathname + search`
 * reads complete - is silently swallowed by the login round trip.
 */
vi.mock("@/lib/api-client", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api-client")>("@/lib/api-client");
  return { ...actual, apiClient: { get: vi.fn(), post: vi.fn() } };
});
vi.mock("@/hooks/use-auth", () => ({ useAdoptSession: () => vi.fn() }));

const replace = vi.hoisted(() => vi.fn());
vi.mock("next/navigation", () => ({ useRouter: () => ({ replace, push: vi.fn() }) }));

beforeEach(() => {
  vi.clearAllMocks();
  useAuthStore.getState().logout();
});

describe("the dashboard guard, refusing", () => {
  it("carries the whole address to login - path, query and fragment", async () => {
    window.history.replaceState(null, "", "/agents/a-1?tab=spec#monthly");
    vi.mocked(apiClient.get).mockRejectedValue(new Error("401"));

    render(
      <AuthGuard>
        <p>the dashboard</p>
      </AuthGuard>,
    );

    await waitFor(() =>
      expect(replace).toHaveBeenCalledWith(
        `${ROUTES.LOGIN}?returnTo=${encodeURIComponent("/agents/a-1?tab=spec#monthly")}`,
      ),
    );
  });
});
