import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook } from "@testing-library/react";
import type { ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";

const { publishVisual } = vi.hoisted(() => ({ publishVisual: vi.fn() }));
vi.mock("@/lib/visuals-api", () => ({ publishVisual }));

import { usePublishVisual } from "./use-publish-visual";

describe("usePublishVisual", () => {
  it("saves the visual and refreshes the apps everyone sees", async () => {
    const client = new QueryClient();
    const invalidate = vi.spyOn(client, "invalidateQueries");
    const wrapper = ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={client}>{children}</QueryClientProvider>
    );
    publishVisual.mockResolvedValue({ version: 1 });
    const { result } = renderHook(() => usePublishVisual(), { wrapper });

    await act(async () => {
      await result.current.mutateAsync({
        conversationId: "c",
        visualId: "v",
        data: { name: "flow" },
      });
    });

    expect(publishVisual).toHaveBeenCalledWith("c", "v", { name: "flow" });
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ["artifacts"] });
    // And the recent-visuals list, whose rows say which is saved.
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ["visuals"] });
  });
});
