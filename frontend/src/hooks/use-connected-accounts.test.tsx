import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useConnectedAccounts } from "./use-connected-accounts";
import { qk } from "@/lib/query-keys";
import { apiClient } from "@/lib/api-client";

vi.mock("@/lib/api-client", () => ({
  apiClient: { get: vi.fn(), post: vi.fn(), delete: vi.fn() },
}));
const invalidate = vi.spyOn(QueryClient.prototype, "invalidateQueries");
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
    expect(apiClient.post).toHaveBeenCalledWith("/me/connected-accounts/oauth/start", undefined);
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

it("starts consent with the selected provider, products and label", async () => {
  vi.mocked(apiClient.post).mockResolvedValue({ authorization_url: "https://example.com/consent" });
  const { result } = renderHook(() => useConnectedAccounts("personal", { provider: "slack" }), {
    wrapper,
  });
  await waitFor(() => expect(result.current.accounts).toEqual([ACCOUNT]));
  expect(apiClient.get).toHaveBeenCalledWith("/me/connected-accounts?provider=slack");
  const options = { provider: "slack" as const, products: ["slack"], write: false, label: "Work" };
  act(() => result.current.connect("/vault", options));
  await waitFor(() =>
    expect(apiClient.post).toHaveBeenCalledWith("/me/connected-accounts/oauth/start", options),
  );
});
it.each(["connectToken", "connectApplication", "connectImap", "connectOdoo"] as const)(
  "%s refreshes choices after success and reports a refused credential",
  async (method) => {
    const { result } = renderHook(() => useConnectedAccounts("organization"), { wrapper });
    await waitFor(() => expect(result.current.accounts).toEqual([ACCOUNT]));
    const data = {
      connectOdoo: {
        credential: { origin: "https://erp.example.com", database: "company", api_key: "test-key" },
        label: "ERP",
        write: false,
      },
      connectToken: { token: "xoxp-test", label: "Work" },
      connectApplication: {
        provider: "microsoft" as const,
        secret_id: "app",
        subject: "a@example.com",
        products: ["outlook_mail"],
        write: false,
        label: "Work",
      },
      connectImap: {
        credential: {
          host: "imap.example.com",
          port: 993,
          username: "a",
          password: "test",
          folder: "INBOX",
        },
        label: "Work",
      },
    };
    const connect = () => {
      if (method === "connectToken")
        return result.current.connectToken.mutateAsync(data.connectToken);
      if (method === "connectApplication")
        return result.current.connectApplication.mutateAsync(data.connectApplication);
      if (method === "connectOdoo") return result.current.connectOdoo.mutateAsync(data.connectOdoo);
      return result.current.connectImap.mutateAsync(data.connectImap);
    };
    vi.mocked(apiClient.post).mockResolvedValue({ id: "new" });
    await act(async () => {
      await connect();
    });
    await waitFor(() => expect(apiClient.get).toHaveBeenCalledTimes(2));
    const suffix = {
      connectToken: "slack/token",
      connectApplication: "application",
      connectImap: "imap",
      connectOdoo: "odoo",
    }[method];
    expect(apiClient.post).toHaveBeenCalledWith(`/connected-accounts/${suffix}`, data[method]);
    expect(invalidate).toHaveBeenCalledWith({ queryKey: qk.portals.catalog() });
    vi.mocked(apiClient.post).mockRejectedValue(new Error("Credential refused"));
    await act(async () => {
      await expect(connect()).rejects.toThrow("Credential refused");
    });
    expect(toastError).toHaveBeenCalledWith("Credential refused");
  },
);
