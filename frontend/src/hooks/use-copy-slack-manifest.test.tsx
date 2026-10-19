import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { toast } from "sonner";

import { apiClient } from "@/lib/api-client";

import { useCopySlackManifest } from "./use-channel-bots";

vi.mock("@/lib/api-client", () => ({ apiClient: { get: vi.fn() } }));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({ defaultOptions: { mutations: { retry: false } } });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

const writeText = vi.fn();

beforeEach(() => {
  vi.clearAllMocks();
  Object.defineProperty(navigator, "clipboard", { value: { writeText }, configurable: true });
});

describe("useCopySlackManifest", () => {
  it("copies the bot's manifest, readable, and says where to paste it", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({ display_information: { name: "Support" } });
    const { result } = renderHook(() => useCopySlackManifest(), { wrapper });

    await act(() => result.current.mutateAsync("b1"));

    expect(apiClient.get).toHaveBeenCalledWith("/channels/bots/b1/slack-manifest");
    expect(writeText).toHaveBeenCalledWith(
      JSON.stringify({ display_information: { name: "Support" } }, null, 2),
    );
    expect(toast.success).toHaveBeenCalledWith(expect.stringContaining("From a manifest"));
  });

  it("says why when it could not", async () => {
    vi.mocked(apiClient.get).mockRejectedValue(new Error("nope"));
    const { result } = renderHook(() => useCopySlackManifest(), { wrapper });

    act(() => result.current.mutate("b1"));

    await waitFor(() => expect(toast.error).toHaveBeenCalled());
  });
});
