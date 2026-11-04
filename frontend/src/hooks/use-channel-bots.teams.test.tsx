import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { toast } from "sonner";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { useDownloadTeamsPackage, useTeamsConversations } from "./use-channel-bots";
import { apiClient } from "@/lib/api-client";
import { saveBlob } from "@/lib/file-access";

vi.mock("@/lib/api-client", () => ({ apiClient: { get: vi.fn(), raw: vi.fn() } }));
vi.mock("@/lib/file-access", () => ({ saveBlob: vi.fn() }));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

beforeEach(() => vi.clearAllMocks());

describe("the Teams app package (#1985)", () => {
  it("is downloaded as a zip named for the bot", async () => {
    const blob = new Blob(["PK"]);
    vi.mocked(apiClient.raw).mockResolvedValue({ blob: () => Promise.resolve(blob) } as Response);
    const { result } = renderHook(() => useDownloadTeamsPackage(), { wrapper });

    await act(() => result.current.mutateAsync({ id: "b1", name: "Support desk" }));

    expect(apiClient.raw).toHaveBeenCalledWith("/channels/bots/b1/teams-app-package");
    expect(saveBlob).toHaveBeenCalledWith(blob, "Support-desk-teams-app.zip");
  });

  it("says why when it cannot be built", async () => {
    vi.mocked(apiClient.raw).mockRejectedValue(new Error("Only a Teams bot has an app package"));
    const { result } = renderHook(() => useDownloadTeamsPackage(), { wrapper });

    await act(async () => {
      await result.current.mutateAsync({ id: "b1", name: "x" }).catch(() => undefined);
    });

    expect(toast.error).toHaveBeenCalled();
    expect(saveBlob).not.toHaveBeenCalled();
  });
});

describe("where a trigger can post", () => {
  it("lists the Teams channels and group chats", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({
      items: [{ id: "c1", bot_id: "b1", name: "General", conversation_type: "channel" }],
    });
    const { result } = renderHook(() => useTeamsConversations(), { wrapper });

    await waitFor(() => expect(result.current.data).toHaveLength(1));
    expect(apiClient.get).toHaveBeenCalledWith("/channels/teams-conversations");
  });

  it("asks nothing until it is wanted", () => {
    renderHook(() => useTeamsConversations(false), { wrapper });
    expect(apiClient.get).not.toHaveBeenCalled();
  });
});
