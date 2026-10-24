import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { useAuthStore } from "@/stores";
import type { User } from "@/types";

import { useChooseLocale } from "./use-choose-locale";

const env = vi.hoisted(() => ({ push: vi.fn(), save: vi.fn(), toastError: vi.fn() }));
vi.mock("@/lib/locale-navigation", () => ({
  usePathname: () => "/agents",
  useRouter: () => ({ push: env.push }),
}));
vi.mock("@/lib/account-locale-api", () => ({ saveAccountLocale: env.save }));
vi.mock("sonner", () => ({ toast: { error: env.toastError } }));

const ADA: User = {
  id: "u-1",
  email: "ada@example.com",
  is_active: true,
  created_at: "2026-10-21T00:00:00Z",
};

beforeEach(() => {
  vi.clearAllMocks();
  env.save.mockResolvedValue("pl");
});

describe("useChooseLocale", () => {
  it("keeps the choice on the account before switching the page", () => {
    useAuthStore.setState({ user: ADA });
    const { result } = renderHook(() => useChooseLocale());

    act(() => result.current("pl"));

    // In the store first, so the page that follows the account does not pull
    // it back while the save is on its way.
    expect(useAuthStore.getState().user?.locale).toBe("pl");
    expect(env.save).toHaveBeenCalledWith("pl");
    expect(env.push).toHaveBeenCalledWith("/agents", { locale: "pl" });
  });

  it("says so when the account could not keep it", async () => {
    useAuthStore.setState({ user: ADA });
    env.save.mockRejectedValue(new Error("offline"));
    const { result } = renderHook(() => useChooseLocale());

    act(() => result.current("de"));

    await waitFor(() => expect(env.toastError).toHaveBeenCalled());
    expect(env.push).toHaveBeenCalledWith("/agents", { locale: "de" });
  });

  it("only switches the page for somebody not signed in", () => {
    useAuthStore.setState({ user: null });
    const { result } = renderHook(() => useChooseLocale());

    act(() => result.current("de"));

    expect(env.save).not.toHaveBeenCalled();
    expect(env.push).toHaveBeenCalledWith("/agents", { locale: "de" });
  });
});
