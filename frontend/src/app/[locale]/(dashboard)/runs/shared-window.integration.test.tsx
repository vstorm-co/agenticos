import { render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { NextIntlClientProvider } from "next-intl";
import { beforeEach, describe, expect, it, vi } from "vitest";

import messages from "../../../../../messages/en.json";
import { apiClient } from "@/lib/api-client";
import RunsPage from "./page";

/**
 * The Runs figure and the Spend figure read the same window.
 *
 * They did not. `list_runs` built its count from `organization_id` alone while
 * the money came from a calendar-month sum, so an organization three years old
 * showed "8,412 runs" beside "$31.20" — two numbers on one row inviting a
 * comparison that was wrong by however old the organization was (#198). Neither
 * number was incorrect on its own, which is why nothing caught it.
 *
 * This asserts on the **request**, not on the rendered digits: what the defect
 * was is which rows each figure counted, and a test that reads "8,412" off the
 * page passes just as happily when the window is wrong.
 */
vi.mock("@/hooks/use-permissions", () => ({
  usePermissions: () => ({ can: () => true, permissions: [], isLoading: false }),
}));

vi.mock("next/navigation", () => ({
  useSearchParams: () => new URLSearchParams(),
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
}));

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <NextIntlClientProvider locale="en" messages={messages}>
        <RunsPage />
      </NextIntlClientProvider>
    </QueryClientProvider>,
  );
}

describe("the Runs figure and the Spend figure", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    vi.spyOn(apiClient, "get").mockImplementation((async (path: string) => {
      if (path === "/spend") {
        return { month_to_date_usd: "31.20", by_agent: [], by_provider: [], by_key: [] };
      }
      if (path === "/approvals") return { items: [], total: 0 };
      return { items: [], total: 8412 };
    }) as typeof apiClient.get);
  });

  it("counts runs from the first instant of the current calendar month", async () => {
    renderPage();

    await waitFor(() => {
      const windowed = vi
        .mocked(apiClient.get)
        .mock.calls.find(([path, options]) => path === "/runs" && options?.params?.started_from);
      expect(windowed).toBeDefined();
    });

    const [, options] = vi
      .mocked(apiClient.get)
      .mock.calls.find(([path, opts]) => path === "/runs" && opts?.params?.started_from)!;
    const startedFrom = new Date(String(options?.params?.started_from));
    const now = new Date();

    expect(startedFrom.getUTCDate()).toBe(1);
    expect(startedFrom.getUTCHours()).toBe(0);
    expect(startedFrom.getUTCMonth()).toBe(now.getUTCMonth());
    expect(startedFrom.getUTCFullYear()).toBe(now.getUTCFullYear());
  });

  it("says on screen which window the count is over", async () => {
    renderPage();

    await waitFor(() =>
      expect(screen.getByText(messages.pages.runs.delegationsCountedInTheir)).toBeInTheDocument(),
    );
  });
});
