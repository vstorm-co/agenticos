import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { OrgSpendingLimit } from "./org-spending-limit";
import { apiClient } from "@/lib/api-client";
import { ApiError } from "@/lib/api-error";
import { useOrgStore } from "@/stores";
import type { Organization, OrgRole } from "@/types";

vi.mock("@/lib/api-client", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api-client")>("@/lib/api-client");
  return {
    ...actual,
    apiClient: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() },
  };
});
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

const ORG_ID = "org-1";

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

function org(overrides: Partial<Organization> = {}): Organization {
  return {
    id: ORG_ID,
    name: "Acme",
    slug: "acme",
    avatar_url: null,
    is_personal: false,
    owner_id: "u1",
    stripe_customer_id: null,
    subscription_tier: "free",
    seats_limit: null,
    monthly_budget_usd: null,
    created_at: "2026-07-01T00:00:00Z",
    updated_at: null,
    ...overrides,
  };
}

function serve(role: OrgRole, monthToDate = "12.5") {
  vi.mocked(apiClient.get).mockImplementation(async (path: string) => {
    if (path === "/me/permissions") {
      return {
        organization_id: ORG_ID,
        role,
        is_app_admin: false,
        // The hook reads the catalog the server sends, so the role alone does
        // not decide anything here - this is the permission under test.
        permissions: role === "owner" ? [{ permission: "org:settings", scope: "all" }] : [],
      };
    }
    if (path === "/spend") return { period_days: 30, month_to_date_usd: monthToDate, by_agent: [] };
    if (path === "/orgs") return { items: [org()], total: 1 };
    throw new Error(`unexpected GET ${path}`);
  });
}

describe("OrgSpendingLimit", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useOrgStore.setState({ activeOrgId: ORG_ID });
  });

  it("sets a ceiling the whole workspace runs under", async () => {
    serve("owner");
    vi.mocked(apiClient.patch).mockResolvedValue(org({ monthly_budget_usd: 500 }));
    render(<OrgSpendingLimit org={org()} />, { wrapper });

    const input = await screen.findByLabelText("Limit (USD)");
    await userEvent.type(input, "500");
    await userEvent.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() =>
      expect(apiClient.patch).toHaveBeenCalledWith(`/orgs/${ORG_ID}`, {
        monthly_budget_usd: 500,
      }),
    );
  });

  it("lifts the ceiling by sending null, not by omitting the field", async () => {
    // An omitted field is how every other update leaves the cap alone. If
    // clearing the box sent nothing, the limit would be impossible to remove.
    serve("owner");
    vi.mocked(apiClient.patch).mockResolvedValue(org());
    render(<OrgSpendingLimit org={org({ monthly_budget_usd: 500 })} />, { wrapper });

    await userEvent.clear(await screen.findByLabelText("Limit (USD)"));
    await userEvent.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() =>
      expect(apiClient.patch).toHaveBeenCalledWith(`/orgs/${ORG_ID}`, {
        monthly_budget_usd: null,
      }),
    );
  });

  it("shows what the month has spent against the limit in force", async () => {
    serve("owner", "12.5");
    render(<OrgSpendingLimit org={org({ monthly_budget_usd: 500 })} />, { wrapper });

    expect(await screen.findByText("$12.50 of $500.00 spent this month.")).toBeInTheDocument();
  });

  it("puts the server's refusal under the input rather than only in a toast", async () => {
    serve("owner");
    vi.mocked(apiClient.patch).mockRejectedValue(
      new ApiError(422, "Invalid request", {
        error: {
          code: "VALIDATION_ERROR",
          message: "Invalid request",
          details: {
            fields: [{ field: "monthly_budget_usd", message: "Input should be greater than 0" }],
          },
        },
      }),
    );
    render(<OrgSpendingLimit org={org()} />, { wrapper });

    await userEvent.type(await screen.findByLabelText("Limit (USD)"), "0");
    await userEvent.click(screen.getByRole("button", { name: "Save" }));

    expect(await screen.findByText("Input should be greater than 0")).toBeInTheDocument();
  });

  it("shows a member nothing, and asks the spend endpoint nothing", async () => {
    // Changing what an organization may spend is an organization setting. A
    // section that could only report a refusal is worse than no section, and
    // the figure beside it comes from an endpoint the same roles gate.
    serve("member");
    render(<OrgSpendingLimit org={org({ monthly_budget_usd: 500 })} />, { wrapper });

    await waitFor(() => expect(apiClient.get).toHaveBeenCalledWith("/me/permissions"));
    expect(screen.queryByText("Monthly spending limit")).not.toBeInTheDocument();
    expect(apiClient.get).not.toHaveBeenCalledWith("/spend", expect.anything());
  });
});
