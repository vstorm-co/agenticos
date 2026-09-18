import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
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
// Stable across renders, as the real hook's `useCallback` is - the verify effect
// depends on it, and a fresh function per render would re-run the effect on every
// state change and stage the same token twice.
const adoptSession = vi.hoisted(() => vi.fn());
vi.mock("@/hooks/use-auth", () => ({ useAdoptSession: () => adoptSession }));

// One router object across renders, as `next/navigation` hands out: a fresh one per
// render would re-run the verify effect on every state change and stage twice.
const router = vi.hoisted(() => ({ replace: vi.fn(), push: vi.fn() }));
const replace = router.replace;
vi.mock("next/navigation", () => ({ useRouter: () => router }));

const FLOW = "0123456789abcdef0123456789abcdef";
const PENDING_FOR_FLOW = `${ROUTES.INVITATION_PENDING}?flow=${FLOW}`;

beforeEach(() => {
  vi.clearAllMocks();
  useAuthStore.getState().logout();
});

function renderGuard() {
  return render(
    <AuthGuard>
      <p>the dashboard</p>
    </AuthGuard>,
  );
}

describe("the dashboard guard, refusing", () => {
  it("carries the whole address to login - path, query and fragment", async () => {
    window.history.replaceState(null, "", "/agents/a-1?tab=spec#monthly");
    vi.mocked(apiClient.get).mockRejectedValue(new Error("401"));

    renderGuard();

    await waitFor(() =>
      expect(replace).toHaveBeenCalledWith(
        `${ROUTES.LOGIN}?returnTo=${encodeURIComponent("/agents/a-1?tab=spec#monthly")}`,
      ),
    );
  });

  it("exchanges an invitation token before login and returns a landing bound to its flow (#1414)", async () => {
    // A signed-out invitee's token must not ride the round trip. The guard stages it
    // - into an httpOnly cookie the exchange sets - and sends them to the pending
    // landing naming the flow, so `returnTo` carries no credential into history or
    // session storage, and the landing can find this staging's cookie among others.
    window.history.replaceState(null, "", "/invitations/a-live-token");
    vi.mocked(apiClient.get).mockRejectedValue(new Error("401"));
    vi.mocked(apiClient.post).mockResolvedValue({ staged: true, flow: FLOW });

    renderGuard();

    await waitFor(() =>
      expect(apiClient.post).toHaveBeenCalledWith("/invitations/stage", { token: "a-live-token" }),
    );
    expect(replace).toHaveBeenCalledWith(
      `${ROUTES.LOGIN}?returnTo=${encodeURIComponent(PENDING_FOR_FLOW)}`,
    );
  });

  it("stays on the invitation when staging fails, and offers to try again", async () => {
    // The token in the URL is the only credential the invitee holds. Leaving for the
    // credential-free landing with nothing staged - on a transient failure or a rate
    // limit - would lose it: they would sign in and find no invitation to accept.
    window.history.replaceState(null, "", "/invitations/a-live-token");
    vi.mocked(apiClient.get).mockRejectedValue(new Error("401"));
    vi.mocked(apiClient.post).mockRejectedValue(new Error("429"));

    renderGuard();

    await screen.findByText(/could not be prepared/i);
    expect(replace).not.toHaveBeenCalled();
    expect(screen.queryByText("the dashboard")).not.toBeInTheDocument();
    expect(window.location.pathname).toBe("/invitations/a-live-token");
  });

  it("retries the exchange from the error state and leaves once it succeeds", async () => {
    window.history.replaceState(null, "", "/invitations/a-live-token");
    vi.mocked(apiClient.get).mockRejectedValue(new Error("401"));
    vi.mocked(apiClient.post)
      .mockRejectedValueOnce(new Error("503"))
      .mockResolvedValueOnce({ staged: true, flow: FLOW });

    renderGuard();
    await userEvent.click(await screen.findByRole("button", { name: /try again/i }));

    await waitFor(() =>
      expect(replace).toHaveBeenCalledWith(
        `${ROUTES.LOGIN}?returnTo=${encodeURIComponent(PENDING_FOR_FLOW)}`,
      ),
    );
    expect(apiClient.post).toHaveBeenCalledTimes(2);
    expect(screen.queryByText(/could not be prepared/i)).not.toBeInTheDocument();
  });
});
