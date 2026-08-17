import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { NextIntlClientProvider } from "next-intl";
import { beforeEach, describe, expect, it, vi } from "vitest";

import messages from "../../../../../messages/en.json";
import { apiClient } from "@/lib/api-client";
import RunsPage from "./page";

/**
 * The Runs figure and the Spend figure read the same window - the page's.
 *
 * They did not. `list_runs` built its count from `organization_id` alone while
 * the money came from a calendar-month sum, so an organization three years old
 * showed "8,412 runs" beside "$31.20" — two numbers on one row inviting a
 * comparison that was wrong by however old the organization was (#198). Neither
 * number was incorrect on its own, which is why nothing caught it. The window
 * both share is now the period control's (#760), so the invariant to hold is
 * that the two requests name the same instants.
 *
 * This asserts on the **request**, not on the rendered digits: what the defect
 * was is which rows each figure counted, and a test that reads "8,412" off the
 * page passes just as happily when the window is wrong.
 */
vi.mock("@/hooks/use-permissions", () => ({
  usePermissions: () => ({ can: () => true, permissions: [], isLoading: false }),
}));

const params = new URLSearchParams();
vi.mock("next/navigation", () => ({
  useSearchParams: () => params,
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  // The header's "?" reads the path to decide whether this page has tips.
  usePathname: () => "/runs",
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
    params.delete("period");
    vi.restoreAllMocks();
    vi.spyOn(apiClient, "get").mockImplementation((async (path: string) => {
      if (path === "/spend") {
        return { month_to_date_usd: "31.20", by_agent: [], by_provider: [], by_key: [] };
      }
      if (path === "/approvals") return { items: [], total: 0 };
      return { items: [], total: 8412 };
    }) as typeof apiClient.get);
  });

  it("counts runs over the very instants the spend request names", async () => {
    renderPage();

    await waitFor(() => {
      const spendCall = vi
        .mocked(apiClient.get)
        .mock.calls.find(
          ([path, options]) =>
            path === "/spend" && (options?.params as Record<string, string> | undefined)?.from,
        );
      expect(spendCall).toBeDefined();
    });

    const [, spendOptions] = vi
      .mocked(apiClient.get)
      .mock.calls.find(
        ([path, opts]) =>
          path === "/spend" && (opts?.params as Record<string, string> | undefined)?.from,
      )!;
    const [, runsOptions] = vi
      .mocked(apiClient.get)
      .mock.calls.find(
        ([path, opts]) =>
          path === "/runs" && (opts?.params as Record<string, string> | undefined)?.started_from,
      )!;

    expect((runsOptions?.params as Record<string, string> | undefined)?.started_from).toBe(
      (spendOptions?.params as Record<string, string> | undefined)?.from,
    );
    expect((runsOptions?.params as Record<string, string> | undefined)?.started_to).toBe(
      (spendOptions?.params as Record<string, string> | undefined)?.to,
    );
    // Whole days, ends inclusive - the shape `periodStart`/`periodEnd` promise.
    expect(String((spendOptions?.params as Record<string, string> | undefined)?.from)).toMatch(
      /T00:00:00\.000Z$/,
    );
    expect(String((spendOptions?.params as Record<string, string> | undefined)?.to)).toMatch(
      /T23:59:59\.999Z$/,
    );
  });

  it("says on screen which window the count is over", async () => {
    renderPage();

    await waitFor(() =>
      expect(screen.getByText(messages.pages.runs.delegationsCountedInTheir)).toBeInTheDocument(),
    );
  });

  it("shows the count the server reports, not the length of the page it returned", async () => {
    // The mock answers `{ items: [], total: 8412 }` on purpose: the two cannot be
    // confused for each other, so a figure reading `items.length` renders 0 here.
    // It used to read a page of fifty and call it the organization's history.
    renderPage();

    // Grouped, like every other figure in the product - four digits of runs
    // read as a quantity rather than as an identifier.
    await waitFor(() => expect(screen.getByText("8,412")).toBeInTheDocument());
  });

  it("opens on the window the URL names, and writes a new pick back to it", async () => {
    // A narrowed view survives a reload and travels in a pasted link (#760):
    // `?period=` in, `?period=` out - the same round-trip the dashboard makes.
    params.set("period", "90d");
    renderPage();

    await waitFor(() => {
      const call = vi
        .mocked(apiClient.get)
        .mock.calls.find(
          ([path, opts]) =>
            path === "/runs" && (opts?.params as Record<string, string> | undefined)?.started_from,
        );
      expect(call).toBeDefined();
      const [, options] = call!;
      const from = new Date(
        String((options?.params as Record<string, string> | undefined)?.started_from),
      );
      const days = Math.round((Date.now() - from.getTime()) / 86_400_000);
      expect(days).toBeGreaterThanOrEqual(89);
      expect(days).toBeLessThanOrEqual(90);
    });

    await userEvent.click(screen.getByRole("button", { name: "Last 7 days" }));

    expect(new URL(window.location.href).searchParams.get("period")).toBe("7d");
    await waitFor(() => {
      const calls = vi
        .mocked(apiClient.get)
        .mock.calls.filter(
          ([path, opts]) =>
            path === "/runs" && (opts?.params as Record<string, string> | undefined)?.started_from,
        );
      const [, options] = calls.at(-1)!;
      const from = new Date(
        String((options?.params as Record<string, string> | undefined)?.started_from),
      );
      const days = Math.round((Date.now() - from.getTime()) / 86_400_000);
      expect(days).toBeGreaterThanOrEqual(6);
      expect(days).toBeLessThanOrEqual(7);
    });
  });
});
