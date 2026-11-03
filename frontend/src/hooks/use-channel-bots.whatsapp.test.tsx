import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { useWhatsAppTemplates } from "./use-channel-bots";
import { apiClient } from "@/lib/api-client";

vi.mock("@/lib/api-client", () => ({ apiClient: { get: vi.fn() } }));

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

beforeEach(() => vi.clearAllMocks());

describe("a WhatsApp bot's templates (#2076)", () => {
  it("fetches the templates for one bot, and nothing without one", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({
      items: [{ name: "late_answer", language: "en_US", body: "Answer: {{1}} - thanks" }],
      total: 1,
    });

    const none = renderHook(() => useWhatsAppTemplates(null), { wrapper });
    expect(none.result.current.fetchStatus).toBe("idle");
    expect(apiClient.get).not.toHaveBeenCalled();

    const { result } = renderHook(() => useWhatsAppTemplates("b1"), { wrapper });

    await waitFor(() => expect(result.current.data).toHaveLength(1));
    expect(apiClient.get).toHaveBeenCalledWith("/channels/bots/b1/whatsapp-templates");
  });
});
