import { act, renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, expect, it, vi } from "vitest";
import type { ReactNode } from "react";
import { useAccountAppearance } from "./use-account-appearance";
import { useAuthStore } from "@/stores";
import { useThemeStore } from "@/stores/theme-store";
import type { User } from "@/types";
import { qk } from "@/lib/query-keys";

const api = vi.hoisted(() => ({ read: vi.fn(), save: vi.fn(), error: vi.fn() }));
vi.mock("@/lib/account-preferences-api", () => ({
  readAccountPreferences: api.read,
  saveAccountAppearance: api.save,
}));
vi.mock("sonner", () => ({ toast: { error: api.error } }));
const user: User = {
  id: "u-1",
  email: "one@example.com",
  is_active: true,
  created_at: "2026-01-01",
};
let client: QueryClient;
function wrapper({ children }: { children: ReactNode }) {
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}
beforeEach(() => {
  vi.clearAllMocks();
  client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  useAuthStore.setState({ user });
  useThemeStore.setState({ theme: "system", look: "standard", editRevision: 0 });
  api.read.mockResolvedValue({ theme: "dark", look: "glass", locale: "pl" });
  api.save.mockResolvedValue({ theme: "light", look: "glass", locale: "pl" });
});

it("adopts MCP/remote appearance without echoing another write", async () => {
  renderHook(() => useAccountAppearance(), { wrapper });
  await waitFor(() => expect(useThemeStore.getState().look).toBe("glass"));
  expect(useThemeStore.getState().theme).toBe("dark");
  expect(useAuthStore.getState().user?.locale).toBe("pl");
  expect(api.save).not.toHaveBeenCalled();
  act(() => {
    client.setQueryData(qk.accountPreferences(user.id), {
      theme: "light",
      look: "paper",
      locale: "en",
    });
  });
  await waitFor(() => expect(useThemeStore.getState().look).toBe("paper"));
  expect(useAuthStore.getState().user?.locale).toBe("en");
  act(() => {
    client.setQueryData(qk.accountPreferences(user.id), { theme: null, look: null, locale: null });
  });
  await waitFor(() => expect(useAuthStore.getState().user?.locale).toBe("en"));
});

it("keeps device defaults until a choice, and saves local edits only", async () => {
  api.read.mockResolvedValue({ theme: null, look: null, locale: null });
  renderHook(() => useAccountAppearance(), { wrapper });
  await waitFor(() => expect(api.read).toHaveBeenCalled());
  act(() => {
    useThemeStore.getState().setTheme("light");
  });
  await waitFor(() => expect(api.save).toHaveBeenCalledWith({ theme: "light" }));
  act(() => {
    useThemeStore.getState().setLook("paper");
  });
  await waitFor(() => expect(api.save).toHaveBeenCalledWith({ look: "paper" }));
  act(() => {
    useThemeStore.getState().setLook("paper");
  });
  expect(api.save).toHaveBeenCalledTimes(2);
});

it("does not read or save another person's preferences after sign-out", async () => {
  useAuthStore.setState({ user: null });
  renderHook(() => useAccountAppearance(), { wrapper });
  act(() => useThemeStore.getState().setLook("glass"));
  expect(api.read).not.toHaveBeenCalled();
  expect(api.save).not.toHaveBeenCalled();
});

it("surfaces save failures", async () => {
  api.save.mockRejectedValue(new Error("offline"));
  renderHook(() => useAccountAppearance(), { wrapper });
  await waitFor(() => expect(useThemeStore.getState().look).toBe("glass"));
  act(() => useThemeStore.getState().setLook("paper"));
  await waitFor(() => expect(api.error).toHaveBeenCalled());
});

it("keeps local choices while saves are pending and refuses queued writes after an account change", async () => {
  let finish: (value: { theme: "light"; look: "glass"; locale: "pl" }) => void = () => {
    throw new Error("No pending save");
  };
  api.save.mockImplementationOnce(
    () =>
      new Promise((resolve) => {
        finish = resolve;
      }),
  );
  renderHook(() => useAccountAppearance(), { wrapper });
  await waitFor(() => expect(useThemeStore.getState().theme).toBe("dark"));
  act(() => useThemeStore.getState().setTheme("light"));
  await waitFor(() => expect(api.save).toHaveBeenCalledTimes(1));
  act(() => useThemeStore.getState().setLook("paper"));
  expect(useThemeStore.getState().theme).toBe("light");
  act(() => useAuthStore.setState({ user: { ...user, id: "u-2" } }));
  await act(async () => {
    finish({ theme: "light", look: "glass", locale: "pl" });
  });
  await waitFor(() => expect(api.error).toHaveBeenCalled());
  expect(api.save).toHaveBeenCalledTimes(1);
});
