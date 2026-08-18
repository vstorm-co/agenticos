import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { useCanCreateTrigger } from "./use-can-create-trigger";
import { apiClient } from "@/lib/api-client";

vi.mock("@/lib/api-client", () => ({
  apiClient: { get: vi.fn() },
}));

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

function serve(agents: Array<{ id: string; can_run: boolean }>) {
  vi.mocked(apiClient.get).mockResolvedValue({ items: agents, total: agents.length });
}

describe("useCanCreateTrigger", () => {
  beforeEach(() => vi.clearAllMocks());

  it("is true when at least one agent is runnable", async () => {
    // The floor is per-agent, not the role: one runnable agent - by role or by a
    // run grant on it - is enough to offer the org-wide create controls.
    serve([
      { id: "a1", can_run: false },
      { id: "a2", can_run: true },
    ]);
    const { result } = renderHook(() => useCanCreateTrigger(), { wrapper });

    await waitFor(() => expect(result.current).toBe(true));
  });

  it("is false when no agent is runnable", async () => {
    serve([{ id: "a1", can_run: false }]);
    const { result } = renderHook(() => useCanCreateTrigger(), { wrapper });

    // It resolves - the list answered - and the answer is false.
    await waitFor(() => expect(apiClient.get).toHaveBeenCalled());
    expect(result.current).toBe(false);
  });

  it("is false while the list is still loading", () => {
    // The same conservatism `usePermissions` applies: reveal the control once the
    // data says it may be, rather than flash it and withdraw it.
    vi.mocked(apiClient.get).mockReturnValue(new Promise(() => {}));
    const { result } = renderHook(() => useCanCreateTrigger(), { wrapper });

    expect(result.current).toBe(false);
  });
});
