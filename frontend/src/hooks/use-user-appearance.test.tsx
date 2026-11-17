import { act, cleanup, renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { appearanceGeneration, resetAccountAppearance } from "@/lib/account-appearance";
import { qk } from "@/lib/query-keys";
import { DEFAULT_APPEARANCE, type UserAppearance } from "@/lib/user-appearance";
import {
  getUserAppearance,
  resetUserAppearance,
  saveUserAppearance,
} from "@/lib/user-appearance-api";
import { useAuthStore } from "@/stores/auth-store";
import { useThemeStore } from "@/stores/theme-store";
import type { User } from "@/types";
import { useUserAppearance } from "./use-user-appearance";

vi.mock("@/lib/user-appearance-api", () => ({
  getUserAppearance: vi.fn(),
  saveUserAppearance: vi.fn(),
  resetUserAppearance: vi.fn(),
}));

const alice = { id: "alice" } as User;
beforeEach(() => {
  vi.clearAllMocks();
  resetAccountAppearance();
  useAuthStore.setState({ user: alice, sessionOwnerId: alice.id });
  vi.mocked(getUserAppearance).mockResolvedValue(DEFAULT_APPEARANCE);
});
afterEach(cleanup);

it("adopts only acknowledged saves and resets the owner's cached appearance", async () => {
  let finishSave!: (preferences: UserAppearance) => void;
  vi.mocked(saveUserAppearance).mockImplementationOnce(
    () =>
      new Promise((resolve) => {
        finishSave = resolve;
      }),
  );
  vi.mocked(resetUserAppearance).mockResolvedValue(DEFAULT_APPEARANCE);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
  const { result } = renderHook(() => useUserAppearance(), { wrapper });
  await waitFor(() => expect(result.current.preferences).toEqual(DEFAULT_APPEARANCE));

  let saving!: Promise<unknown>;
  act(() => {
    saving = result.current.save({ theme: "dark", radius: "rounded" });
  });
  await waitFor(() => expect(result.current.pending).toBe(true));
  expect(saveUserAppearance).toHaveBeenCalledWith({ theme: "dark", radius: "rounded" });
  expect(useThemeStore.getState().theme).toBe("system");
  expect(result.current.preferences).toEqual(DEFAULT_APPEARANCE);

  const saved = { ...DEFAULT_APPEARANCE, theme: "dark", radius: "rounded" } as const;
  await act(async () => {
    finishSave(saved);
    await saving;
  });
  await waitFor(() => expect(result.current.preferences).toEqual(saved));
  expect(useThemeStore.getState().theme).toBe("dark");
  expect(client.getQueryData(qk.auth.appearance(alice.id))).toEqual({
    owner: alice.id,
    epoch: appearanceGeneration(),
    preferences: saved,
  });

  await act(async () => {
    await result.current.reset();
  });
  expect(resetUserAppearance).toHaveBeenCalledOnce();
  await waitFor(() => expect(result.current.preferences).toEqual(DEFAULT_APPEARANCE));
  expect(useThemeStore.getState().theme).toBe("system");
  expect(result.current.pending).toBe(false);
  client.clear();
});

it("does not send a queued edit or adopt an old response after the same person signs in again", async () => {
  let finishFirst!: (preferences: UserAppearance) => void;
  vi.mocked(saveUserAppearance).mockImplementationOnce(
    () =>
      new Promise((resolve) => {
        finishFirst = resolve;
      }),
  );
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
  const { result } = renderHook(() => useUserAppearance(), { wrapper });
  await waitFor(() => expect(result.current.preferences).toEqual(DEFAULT_APPEARANCE));

  let first!: Promise<unknown>;
  act(() => {
    first = result.current.save({ theme: "dark" });
  });
  await waitFor(() => expect(saveUserAppearance).toHaveBeenCalledTimes(1));
  let second!: Promise<unknown>;
  act(() => {
    second = result.current.save({ accent: "blue" });
  });
  const settled = Promise.allSettled([first, second]);

  act(() => {
    resetAccountAppearance();
    useAuthStore.setState({ user: null });
    useAuthStore.setState({ user: alice });
  });
  let outcomes!: PromiseSettledResult<unknown>[];
  await act(async () => {
    finishFirst({ ...DEFAULT_APPEARANCE, theme: "dark" });
    outcomes = await settled;
  });
  expect(outcomes[1]?.status).toBe("rejected");
  expect(saveUserAppearance).toHaveBeenCalledTimes(1);
  expect(useThemeStore.getState().theme).toBe("system");
  client.clear();
});
