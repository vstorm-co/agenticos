import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Suspense, type ReactNode } from "react";
import { expect, it, vi } from "vitest";

import RetentionPage from "./page";
import { apiClient } from "@/lib/api-client";

vi.mock("@/lib/api-client", () => ({ apiClient: { get: vi.fn(), put: vi.fn() } }));
vi.mock("@/hooks", async () => ({
  useRetention: (await import("@/hooks/use-retention")).useRetention,
  usePermissions: () => ({ can: () => true, isLoaded: true, error: null }),
}));

it("shows and retries a failed policy read instead of leaving the page loading", async () => {
  vi.mocked(apiClient.get)
    .mockRejectedValueOnce(new Error("unavailable"))
    .mockResolvedValue({
      requested: {},
      effective: { audit: 2190 },
      ceilings: {},
      audit_floor_days: 2190,
      conflicts: [],
    });
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>
      <Suspense fallback={null}>{children}</Suspense>
    </QueryClientProvider>
  );
  await act(async () => {
    render(<RetentionPage params={Promise.resolve({ id: "org-1" })} />, { wrapper });
  });
  const retry = await screen.findByRole("button", { name: "Retry" });
  await userEvent.click(retry);
  expect(await screen.findAllByRole("spinbutton")).toHaveLength(7);
  expect(screen.queryByRole("button", { name: "Retry" })).toBeNull();
});
