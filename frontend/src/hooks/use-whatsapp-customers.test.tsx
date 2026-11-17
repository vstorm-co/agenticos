import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { useWhatsAppCustomers } from "./use-whatsapp-customers";
import { apiClient } from "@/lib/api-client";
import type { WhatsAppCustomer } from "@/types/channels";

vi.mock("@/lib/api-client", () => ({ apiClient: { get: vi.fn(), post: vi.fn() } }));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

function customer(overrides: Partial<WhatsAppCustomer> = {}): WhatsAppCustomer {
  return {
    id: "c1",
    bsuid: "PL.1234",
    phone: "48600700800",
    profile_name: "Ana",
    username: null,
    last_message_at: "2026-11-04T09:00:00Z",
    linked: false,
    ...overrides,
  };
}

beforeEach(() => vi.clearAllMocks());

describe("a WhatsApp bot's customers", () => {
  it("lists them for one bot, and nothing for none", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({ items: [customer()], total: 1 });

    const none = renderHook(() => useWhatsAppCustomers(null), { wrapper });
    expect(none.result.current.customers).toEqual([]);
    expect(apiClient.get).not.toHaveBeenCalled();

    const { result } = renderHook(() => useWhatsAppCustomers("b1"), { wrapper });

    await waitFor(() => expect(result.current.customers).toHaveLength(1));
    expect(apiClient.get).toHaveBeenCalledWith(
      "/channels/bots/b1/whatsapp-customers?skip=0&limit=50",
    );
  });

  it("has none before it has answered", () => {
    vi.mocked(apiClient.get).mockReturnValue(new Promise(() => undefined));

    const { result } = renderHook(() => useWhatsAppCustomers("b1"), { wrapper });

    expect(result.current.customers).toEqual([]);
  });

  it("searches by number in the body, never in the url", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({ items: [], total: 0 });
    vi.mocked(apiClient.post).mockResolvedValue({ items: [customer()], total: 1 });
    const { result } = renderHook(() => useWhatsAppCustomers("b1"), { wrapper });

    const found = await result.current.search.mutateAsync("+48 600 700 800");

    expect(apiClient.post).toHaveBeenCalledWith("/channels/bots/b1/whatsapp-customers/search", {
      phone: "+48 600 700 800",
    });
    expect(found).toHaveLength(1);
  });

  it("shows why a search was refused", async () => {
    const { toast } = await import("sonner");
    vi.mocked(apiClient.get).mockResolvedValue({ items: [], total: 0 });
    vi.mocked(apiClient.post).mockRejectedValue(new Error("Not a phone number"));
    const { result } = renderHook(() => useWhatsAppCustomers("b1"), { wrapper });

    await expect(result.current.search.mutateAsync("abc")).rejects.toThrow();

    expect(toast.error).toHaveBeenCalledWith("Not a phone number");
  });

  it("loads the next page from where the last one ended", async () => {
    const page = (ids: string[]) => ({ items: ids.map((id) => customer({ id })), total: 3 });
    vi.mocked(apiClient.get)
      .mockResolvedValueOnce(page(["c1", "c2"]))
      .mockResolvedValueOnce(page(["c3"]));
    const { result } = renderHook(() => useWhatsAppCustomers("b1"), { wrapper });
    await waitFor(() => expect(result.current.customers).toHaveLength(2));
    expect(result.current.total).toBe(3);
    expect(result.current.hasMore).toBe(true);

    await result.current.loadMore();

    await waitFor(() => expect(result.current.customers).toHaveLength(3));
    expect(apiClient.get).toHaveBeenLastCalledWith(
      "/channels/bots/b1/whatsapp-customers?skip=2&limit=50",
    );
    expect(result.current.hasMore).toBe(false);
  });

  it("forgets one customer by id, says so, and re-reads the list", async () => {
    const { toast } = await import("sonner");
    vi.mocked(apiClient.get).mockResolvedValue({ items: [customer()], total: 1 });
    vi.mocked(apiClient.post).mockResolvedValue({
      identities: 1,
      sessions: 1,
      customers: 1,
      conversations: 0,
      workspaces: 0,
      link_requests: 0,
      prompts: 0,
      runs_ended: 1,
      approvals_ended: 0,
      approvals_redacted: 0,
      manifests: 0,
      notifications: 0,
      handback_jobs: 0,
      handback_jobs_running: 0,
    });
    const { result } = renderHook(() => useWhatsAppCustomers("b1"), { wrapper });
    await waitFor(() => expect(result.current.customers).toHaveLength(1));

    await result.current.forget.mutateAsync("c1");

    expect(apiClient.post).toHaveBeenCalledWith("/channels/bots/b1/whatsapp-customers/forget", {
      customer_id: "c1",
    });
    expect(toast.success).toHaveBeenCalledWith("Customer forgotten");
    await waitFor(() => expect(vi.mocked(apiClient.get).mock.calls.length).toBeGreaterThan(1));
  });

  it("leaves the refusal of a forget to the sheet that asked", async () => {
    const refused = new Error("This customer has linked an account");
    vi.mocked(apiClient.get).mockResolvedValue({ items: [customer()], total: 1 });
    vi.mocked(apiClient.post).mockRejectedValue(refused);
    const { result } = renderHook(() => useWhatsAppCustomers("b1"), { wrapper });

    await expect(result.current.forget.mutateAsync("c1")).rejects.toThrow(refused);
  });
});
