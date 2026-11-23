import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, waitFor } from "@testing-library/react";
import { expect, it, vi } from "vitest";

import { apiClient } from "@/lib/api-client";
import { TopOrgsWidget } from "./top-orgs";

vi.mock("@/lib/api-client", () => ({
  apiClient: { get: vi.fn() },
}));

it("asks the server for the five organizations with the most members", async () => {
  vi.mocked(apiClient.get).mockResolvedValue({ items: [], total: 0 });

  render(
    <QueryClientProvider client={new QueryClient()}>
      <TopOrgsWidget
        title="Top organizations"
        hint=""
        period={{ preset: "30d", from: "", to: "" }}
      />
    </QueryClientProvider>,
  );

  await waitFor(() =>
    expect(apiClient.get).toHaveBeenCalledWith("/admin/organizations", {
      params: { limit: "5", sort_by: "members", sort_dir: "desc" },
    }),
  );
});
