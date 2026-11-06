import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useConnectedAccounts } from "./use-connected-accounts";
import { apiClient } from "@/lib/api-client";

vi.mock("@/lib/api-client", () => ({
  apiClient: { get: vi.fn(), post: vi.fn(), delete: vi.fn() },
}));
const toastError = vi.fn();
vi.mock("sonner", () => ({ toast: { error: (...args: unknown[]) => toastError(...args) } }));
const remember = vi.fn();
vi.mock("@/lib/mcp-oauth", () => ({
  rememberMcpOAuthReturn: (...args: unknown[]) => remember(...args),
}));

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

const ACCOUNT = { id: "a1", email: "ana@acme.com" };
const assign = vi.fn();

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(apiClient.get).mockResolvedValue({ items: [ACCOUNT], total: 1 });
  vi.stubGlobal("location", { ...window.location, assign });
});

afterEach(() => vi.unstubAllGlobals());

describe("useConnectedAccounts", () => {
  it("lists a person's own accounts and the organization's at their own addresses", async () => {
    const mine = renderHook(() => useConnectedAccounts("personal"), { wrapper });
    const theirs = renderHook(() => useConnectedAccounts("organization"), { wrapper });

    await waitFor(() => expect(mine.result.current.accounts).toEqual([ACCOUNT]));
    await waitFor(() => expect(theirs.result.current.accounts).toEqual([ACCOUNT]));
    expect(apiClient.get).toHaveBeenCalledWith("/me/connected-accounts");
    expect(apiClient.get).toHaveBeenCalledWith("/connected-accounts");
  });

  it("does not ask for a list the caller may not read", () => {
    const { result } = renderHook(() => useConnectedAccounts("organization", { enabled: false }), {
      wrapper,
    });

    expect(apiClient.get).not.toHaveBeenCalled();
    expect(result.current.accounts).toEqual([]);
  });

  it("leaves for the consent screen, remembering where to come back to", async () => {
    vi.mocked(apiClient.post).mockResolvedValue({
      authorization_url: "https://accounts.google.com/o/oauth2/v2/auth?x=1",
    });
    const { result } = renderHook(() => useConnectedAccounts("personal"), { wrapper });

    act(() => result.current.connect("/vault"));

    await waitFor(() =>
      expect(assign).toHaveBeenCalledWith("https://accounts.google.com/o/oauth2/v2/auth?x=1"),
    );
    expect(apiClient.post).toHaveBeenCalledWith("/me/connected-accounts/oauth/start");
    expect(remember).toHaveBeenCalledWith("/vault");
  });

  it("says why a consent could not start", async () => {
    vi.mocked(apiClient.post).mockRejectedValue(new Error("Google sign-in is not configured"));
    const { result } = renderHook(() => useConnectedAccounts("organization"), { wrapper });

    act(() => result.current.connect("/vault"));

    await waitFor(() =>
      expect(toastError).toHaveBeenCalledWith("Google sign-in is not configured"),
    );
    expect(assign).not.toHaveBeenCalled();
  });

  it("disconnects an account and reads the list again", async () => {
    vi.mocked(apiClient.delete).mockResolvedValue(undefined);
    const { result } = renderHook(() => useConnectedAccounts("organization"), { wrapper });
    await waitFor(() => expect(result.current.isLoading).toBe(false));

    act(() => result.current.disconnect("a1"));

    await waitFor(() => expect(apiClient.get).toHaveBeenCalledTimes(2));
    expect(apiClient.delete).toHaveBeenCalledWith("/connected-accounts/a1");
  });

  it("says so when a disconnect is refused", async () => {
    vi.mocked(apiClient.delete).mockRejectedValue(new Error("Not yours"));
    const { result } = renderHook(() => useConnectedAccounts("personal"), { wrapper });

    act(() => result.current.disconnect("a1"));

    await waitFor(() => expect(toastError).toHaveBeenCalledWith("Not yours"));
  });
});
