import { act, cleanup, renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { resetAccountAppearance } from "@/lib/account-appearance";
import { DEFAULT_APPEARANCE, type UserAppearance } from "@/lib/user-appearance";
import { getUserAppearance, saveUserAppearance } from "@/lib/user-appearance-api";
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
