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
  window.history.replaceState(null, "", "/");
});

describe("useChooseLocale", () => {
  it.each(["pl", "tr"] as const)("keeps %s on the account before switching the page", (locale) => {
    useAuthStore.setState({ user: ADA });
    const { result } = renderHook(() => useChooseLocale());

    act(() => result.current(locale));

    // In the store first, so the page that follows the account does not pull
    // it back while the save is on its way.
    expect(useAuthStore.getState().user?.locale).toBe(locale);
    expect(env.save).toHaveBeenCalledWith(locale);
    expect(env.push).toHaveBeenCalledWith("/agents", { locale });
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

it("preserves the wizard workspace, question and fragment when choosing a language", () => {
  window.history.replaceState(
    null,
    "",
    "/onboarding?start-step=admin.organization&workspace=org&question=budget#limits",
  );
  const { result } = renderHook(() => useChooseLocale());
  act(() => result.current("pl"));
  expect(env.push).toHaveBeenCalledWith(
    "/agents?start-step=admin.organization&workspace=org&question=budget#limits",
    { locale: "pl" },
  );
});
