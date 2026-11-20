import { act, render, renderHook, screen, waitFor, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, expect, it, vi } from "vitest";
import type { ReactNode } from "react";
import userEvent from "@testing-library/user-event";
import { AppearanceSettings } from "@/components/settings/appearance-settings";
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
  useThemeStore.setState({ theme: "system", look: "standard", editRevision: 0, editedField: null });
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
  await waitFor(() => expect(api.save).toHaveBeenCalledTimes(3));
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

it.each(["theme", "look"] as const)(
  "saves an explicit %s choice even when it matches the device default",
  async (field) => {
    api.read.mockResolvedValue({ theme: null, look: null, locale: null });
    renderHook(() => useAccountAppearance(), { wrapper });
    await waitFor(() => expect(client.getQueryData(qk.accountPreferences(user.id))).toBeDefined());
    expect(api.save).not.toHaveBeenCalled();
    act(() => {
      if (field === "theme") useThemeStore.getState().setTheme("system");
      else useThemeStore.getState().setLook("standard");
    });
    await waitFor(() =>
      expect(api.save).toHaveBeenCalledWith(
        field === "theme" ? { theme: "system" } : { look: "standard" },
      ),
    );
  },
);

it("retries the same unsaved selection without changing to another theme first", async () => {
  api.read.mockResolvedValue({ theme: null, look: null, locale: null });
  api.save.mockRejectedValueOnce(new Error("offline"));
  renderHook(() => useAccountAppearance(), { wrapper });
  await waitFor(() => expect(client.getQueryData(qk.accountPreferences(user.id))).toBeDefined());
  act(() => useThemeStore.getState().setTheme("light"));
  await waitFor(() => expect(api.error).toHaveBeenCalled());
  await waitFor(() => expect(client.isMutating()).toBe(0));
  expect(useThemeStore.getState().theme).toBe("light");
  act(() => useThemeStore.getState().setTheme("light"));
  await waitFor(() => expect(api.save).toHaveBeenCalledTimes(2));
  expect(api.save).toHaveBeenLastCalledWith({ theme: "light" });
});

it("persists already-selected Settings defaults as deliberate account choices", async () => {
  api.read.mockResolvedValue({ theme: null, look: null, locale: null });
  function Preferences() {
    useAccountAppearance();
    return <AppearanceSettings />;
  }
  render(<Preferences />, { wrapper });
  await waitFor(() => expect(client.getQueryData(qk.accountPreferences(user.id))).toBeDefined());
  const system = within(screen.getByRole("radiogroup", { name: "Theme" })).getByRole("radio", {
    name: "System",
  });
  expect(system).toBeChecked();
  await userEvent.click(system);
  await waitFor(() => expect(api.save).toHaveBeenCalledWith({ theme: "system" }));
  const standard = screen.getByRole("radio", { name: /^Standard/ });
  expect(standard).toBeChecked();
  await userEvent.click(standard);
  await waitFor(() => expect(api.save).toHaveBeenCalledWith({ look: "standard" }));
});
