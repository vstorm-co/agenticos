import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { useOnboardingTour } from "./use-onboarding";
import { ApiError, apiClient } from "@/lib/api-client";
import { TOUR_STEPS } from "@/lib/onboarding/tour";
import { useAuthStore, useOnboardingStore } from "@/stores";
import { Perm } from "@/types/permissions";
import type { User } from "@/types";

const nav = vi.hoisted(() => ({ pathname: "/dashboard" }));
vi.mock("next/navigation", () => ({
  usePathname: () => nav.pathname,
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), prefetch: vi.fn(), back: vi.fn() }),
  useSearchParams: () => new URLSearchParams(),
  useParams: () => ({}),
}));

vi.mock("@/lib/api-client", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api-client")>("@/lib/api-client");
  return { ...actual, apiClient: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() } };
});
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

import { toast } from "sonner";

const ALL = Object.values(Perm);

function user(overrides: Partial<User> = {}): User {
  return {
    id: "u1",
    email: "a@example.com",
    is_active: true,
    created_at: "2026-01-01T00:00:00Z",
    onboarding_completed_at: null,
    ...overrides,
  };
}

function servePermissions(permissions: readonly string[] = ALL) {
  vi.mocked(apiClient.get).mockResolvedValue({
    organization_id: "org-1",
    role: "owner",
    is_app_admin: false,
    permissions: permissions.map((permission) => ({ permission, scope: "all" })),
  });
}

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

describe("useOnboardingTour", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    nav.pathname = "/dashboard";
    useOnboardingStore.setState({ isOpen: false, index: 0 });
    useAuthStore.setState({ user: user(), isAuthenticated: true });
    servePermissions();
  });

  it("auto-opens on the dashboard for a user who has not finished onboarding", async () => {
    const { result } = renderHook(() => useOnboardingTour(), { wrapper });
    await waitFor(() => expect(result.current.isOpen).toBe(true));
    expect(result.current.steps.length).toBe(TOUR_STEPS.length);
    expect(result.current.isFirst).toBe(true);
  });

  it("does not auto-open once onboarding is finished", async () => {
    useAuthStore.setState({ user: user({ onboarding_completed_at: "2020-01-01T00:00:00Z" }) });
    const { result } = renderHook(() => useOnboardingTour(), { wrapper });
    await waitFor(() => expect(result.current.steps.length).toBe(TOUR_STEPS.length));
    expect(result.current.isOpen).toBe(false);
  });

  it("does not auto-open away from the dashboard", async () => {
    nav.pathname = "/agents";
    const { result } = renderHook(() => useOnboardingTour(), { wrapper });
    await waitFor(() => expect(result.current.steps.length).toBe(TOUR_STEPS.length));
    expect(result.current.isOpen).toBe(false);
  });

  it("does not auto-open while permissions are still loading", () => {
    vi.mocked(apiClient.get).mockReturnValue(new Promise(() => {}));
    const { result } = renderHook(() => useOnboardingTour(), { wrapper });
    expect(result.current.isOpen).toBe(false);
  });

  it("does not auto-open when the permission set is in error", async () => {
    // A refused organization leaves can() answering false forever, which would
    // collapse the tour to its four ungated steps on top of the org-recovery
    // banner. A 404 is refused without a retry, so the error settles at once.
    vi.mocked(apiClient.get).mockRejectedValue(new ApiError(404, "no such organization"));
    const { result } = renderHook(() => useOnboardingTour(), { wrapper });
    await waitFor(() => expect(result.current.steps.length).toBe(4));
    expect(result.current.isOpen).toBe(false);
  });

  it("does not auto-open for a signed-out visitor", async () => {
    useAuthStore.setState({ user: null });
    const { result } = renderHook(() => useOnboardingTour(), { wrapper });
    await waitFor(() => expect(result.current.steps.length).toBe(TOUR_STEPS.length));
    expect(result.current.isOpen).toBe(false);
  });

  it("persists completion and closes when dismissed", async () => {
    vi.mocked(apiClient.patch).mockResolvedValue(
      user({ onboarding_completed_at: "2026-02-02T00:00:00Z" }),
    );
    const { result } = renderHook(() => useOnboardingTour(), { wrapper });
    await waitFor(() => expect(result.current.isOpen).toBe(true));

    act(() => result.current.dismiss());
    expect(result.current.isOpen).toBe(false);
    expect(apiClient.patch).toHaveBeenCalledWith("/users/me", {
      onboarding_completed_at: expect.any(String),
    });
    await waitFor(() =>
      expect(useAuthStore.getState().user?.onboarding_completed_at).toBe("2026-02-02T00:00:00Z"),
    );
  });

  it("does not write again for a user who already finished", async () => {
    useAuthStore.setState({ user: user({ onboarding_completed_at: "2020-01-01T00:00:00Z" }) });
    const { result } = renderHook(() => useOnboardingTour(), { wrapper });
    await waitFor(() => expect(result.current.steps.length).toBe(TOUR_STEPS.length));

    act(() => useOnboardingStore.getState().restart());
    expect(result.current.isOpen).toBe(true);
    act(() => result.current.dismiss());
    expect(result.current.isOpen).toBe(false);
    expect(apiClient.patch).not.toHaveBeenCalled();
  });

  it("closes without a write for a signed-out caller", () => {
    useAuthStore.setState({ user: null });
    const { result } = renderHook(() => useOnboardingTour(), { wrapper });
    act(() => useOnboardingStore.getState().restart());
    act(() => result.current.dismiss());
    expect(result.current.isOpen).toBe(false);
    expect(apiClient.patch).not.toHaveBeenCalled();
  });

  it("surfaces an API error's message when the write fails", async () => {
    vi.mocked(apiClient.patch).mockRejectedValue(new ApiError(500, "boom"));
    const { result } = renderHook(() => useOnboardingTour(), { wrapper });
    await waitFor(() => expect(result.current.isOpen).toBe(true));
    act(() => result.current.dismiss());
    await waitFor(() => expect(toast.error).toHaveBeenCalledWith("boom"));
  });

  it("falls back to a generic message when the failure is not an API error", async () => {
    vi.mocked(apiClient.patch).mockRejectedValue(new Error("network"));
    const { result } = renderHook(() => useOnboardingTour(), { wrapper });
    await waitFor(() => expect(result.current.isOpen).toBe(true));
    act(() => result.current.dismiss());
    await waitFor(() =>
      expect(toast.error).toHaveBeenCalledWith(expect.stringContaining("walkthrough")),
    );
  });

  it("steps forward and back, clamped at both ends", async () => {
    const { result } = renderHook(() => useOnboardingTour(), { wrapper });
    await waitFor(() => expect(result.current.isOpen).toBe(true));

    act(() => result.current.back());
    expect(result.current.index).toBe(0);
    act(() => result.current.next());
    expect(result.current.index).toBe(1);

    const last = result.current.steps.length - 1;
    for (let i = 0; i < last + 2; i++) act(() => result.current.next());
    expect(result.current.index).toBe(last);
    expect(result.current.isLast).toBe(true);
  });

  it("does not reopen itself after a dismissal in the same session", async () => {
    // The persisted user still reads as not-onboarded, so only the once-per-load
    // guard keeps the modal from springing back open.
    vi.mocked(apiClient.patch).mockResolvedValue(user());
    const { result, rerender } = renderHook(() => useOnboardingTour(), { wrapper });
    await waitFor(() => expect(result.current.isOpen).toBe(true));

    act(() => result.current.dismiss());
    expect(result.current.isOpen).toBe(false);
    rerender();
    expect(result.current.isOpen).toBe(false);
  });
});
