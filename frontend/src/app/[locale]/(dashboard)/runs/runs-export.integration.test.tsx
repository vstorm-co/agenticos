import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import RunsPage from "./page";
import { apiClient } from "@/lib/api-client";
import { saveBlob } from "@/lib/file-access";
import type { Permission } from "@/types/permissions";

/**
 * The export control on the Activity page.
 *
 * Two page-level claims the component test cannot make: that the runs export
 * carries the `?agent=` the page was opened on - so the file is what the table
 * was narrowed to - and that the control is absent for a caller without
 * `runs:view`, gated exactly as the tab it sits on. Real `usePermissions` over a
 * mocked `/me/permissions`, because a permission decision is the thing on trial.
 */

vi.mock("@/lib/api-client", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api-client")>("@/lib/api-client");
  return { ...actual, apiClient: { ...actual.apiClient, get: vi.fn(), raw: vi.fn() } };
});
vi.mock("@/lib/file-access", () => ({ saveBlob: vi.fn() }));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

const params = new URLSearchParams("agent=agent-1");
vi.mock("next/navigation", () => ({ useSearchParams: () => params }));

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

function serve(permissions: Permission[]) {
  vi.mocked(apiClient.get).mockImplementation((path: string) => {
    if (path === "/me/permissions")
      return Promise.resolve({
        organization_id: "o1",
        role: "operator",
        is_app_admin: false,
        permissions: permissions.map((permission) => ({ permission, scope: "all" })),
      });
    return Promise.resolve({ items: [], total: 0 });
  });
  vi.mocked(apiClient.raw).mockResolvedValue({
    blob: async () => new Blob(["run_id\n"], { type: "text/csv" }),
    headers: { get: () => 'attachment; filename="runs_export.csv"' },
  } as unknown as Response);
}

beforeEach(() => {
  vi.mocked(apiClient.get).mockReset();
  vi.mocked(apiClient.raw).mockReset();
  vi.mocked(saveBlob).mockReset();
});

describe("exporting run history from a filtered Activity page", () => {
  it("carries the agent the page was narrowed to, and the page's window", async () => {
    serve(["runs:view"]);

    render(<RunsPage />, { wrapper });

    await userEvent.click(await screen.findByRole("button", { name: "Export CSV" }));

    await waitFor(() => expect(apiClient.raw).toHaveBeenCalledTimes(1));
    const call = vi.mocked(apiClient.raw).mock.calls.at(-1);
    if (call === undefined) throw new Error("apiClient.raw was not called");
    expect(call[0]).toBe("/runs/export");
    const query = (call[1] as { params: Record<string, string> }).params;
    expect(query.agent_id).toBe("agent-1");
    expect(query.include_delegations).toBe("true");
    expect(query.started_from).toMatch(/^\d{4}-\d{2}-\d{2}T/);
    expect(query.started_to).toMatch(/^\d{4}-\d{2}-\d{2}T/);
    await waitFor(() => expect(saveBlob).toHaveBeenCalled());
  });

  it("is absent for a caller without runs:view", async () => {
    serve([]);

    render(<RunsPage />, { wrapper });

    // The Runs tab still renders (only Approvals is gated away); the export does not.
    expect(await screen.findByRole("tab", { name: "Runs" })).toBeVisible();
    expect(screen.queryByRole("button", { name: "Export CSV" })).toBeNull();
  });
});
