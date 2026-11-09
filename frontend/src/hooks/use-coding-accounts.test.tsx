import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import type { ReactNode } from "react";
import { useCodingAccounts } from "./use-coding-accounts";
import { useAuthStore } from "@/stores";
import type { CodingAccount } from "@/lib/coding-accounts-api";
import * as api from "@/lib/coding-accounts-api";
const scope = vi.hoisted(() => ({ tenant: "organization" as string | null }));
vi.mock("@/hooks/use-organizations", () => ({
  useTenantId: () => scope.tenant,
  useTenantGuard: () => (tenant: string | null) => scope.tenant === tenant,
}));
vi.mock("@/lib/coding-accounts-api", () => ({
  listCodingAccounts: vi.fn(),
  connectCodingAccount: vi.fn(),
  disconnectCodingAccount: vi.fn(),
  enableCodingAccount: vi.fn(),
  completeCodingSignIn: vi.fn(),
  startCodingSignIn: vi.fn(),
}));
const account: CodingAccount = {
  id: "coding",
  harness: "claude_code",
  label: "Personal",
  secret_kind: "api_key",
  enabled: false,
  generation: "generation",
};
function mount() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
  return { client, ...renderHook(() => useCodingAccounts(), { wrapper }) };
}
beforeEach(() => {
  vi.clearAllMocks();
  scope.tenant = "organization";
  useAuthStore.setState({
    user: {
      id: "person",
      email: "person@example.com",
      is_active: true,
      created_at: "2026-11-01T00:00:00Z",
    },
  });
  vi.mocked(api.listCodingAccounts).mockResolvedValue({ items: [] });
});
it.each(["tenant", "person"])(
  "does not refresh another private account after %s changes during sign-in",
  async (change) => {
    let finish: ((account: CodingAccount) => void) | undefined;
    vi.mocked(api.connectCodingAccount).mockImplementation(
      () =>
        new Promise((resolve) => {
          finish = resolve;
        }),
    );
    const { result, client, rerender } = mount();
    await waitFor(() => expect(result.current.accounts.isSuccess).toBe(true));
    const invalidated = vi.spyOn(client, "invalidateQueries");
    let pending: Promise<CodingAccount> | undefined;
    act(() => {
      pending = result.current.connect.mutateAsync({
        harness: "claude_code",
        label: "Personal",
        api_key: "private",
        enabled: false,
      });
    });
    await waitFor(() => expect(finish).toBeDefined());
    act(() => {
      if (change === "tenant") scope.tenant = "other";
      else useAuthStore.setState({ user: null });
    });
    rerender();
    await act(async () => {
      finish?.(account);
      await pending;
    });
    expect(invalidated).not.toHaveBeenCalled();
  },
);
it.each(["tenant", "person"])("does not query private coding accounts without %s", (missing) => {
  if (missing === "tenant") scope.tenant = null;
  else useAuthStore.setState({ user: null });
  const { result } = mount();
  expect(result.current.ready).toBe(false);
  expect(api.listCodingAccounts).not.toHaveBeenCalled();
});
