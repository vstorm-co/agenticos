import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { toast } from "sonner";

import { OrgApprovalWaiver } from "./org-approval-waiver";
import { apiClient } from "@/lib/api-client";
import type { Organization } from "@/types";

vi.mock("@/lib/api-client", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api-client")>("@/lib/api-client");
  return { ...actual, apiClient: { get: vi.fn(), patch: vi.fn() } };
});
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

const state = vi.hoisted(() => ({ mayDecide: true }));
vi.mock("@/hooks/use-permissions", () => ({
  usePermissions: () => ({ can: () => state.mayDecide }),
}));

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

function org(overrides: Partial<Organization> = {}): Organization {
  return {
    id: "org-1",
    name: "Acme",
    slug: "acme",
    avatar_url: null,
    avatar_color: null,
    is_personal: false,
    owner_id: "u1",
    stripe_customer_id: null,
    subscription_tier: "free",
    seats_limit: null,
    monthly_budget_usd: null,
    chat_may_waive_approvals: false,
    created_at: "2026-08-01T00:00:00Z",
    updated_at: null,
    ...overrides,
  };
}

beforeEach(() => {
  vi.clearAllMocks();
  state.mayDecide = true;
  vi.mocked(apiClient.get).mockResolvedValue({ items: [], total: 0 });
  vi.mocked(apiClient.patch).mockImplementation(async (_path, body) =>
    org(body as Partial<Organization>),
  );
});

/**
 * The ceiling on standing consent (#925).
 *
 * A chat session can waive an organization's approvals only if the organization
 * has said it may. Without that, a Builder's deliberate gate on `send_email` is
 * one click from nothing in every conversation.
 */
describe("the approval waiver switch", () => {
  it("is off until somebody turns it on, so an upgrade changes nothing", () => {
    render(<OrgApprovalWaiver org={org()} />, { wrapper });

    expect(screen.getByRole("switch")).not.toBeChecked();
  });

  it("reflects an organization that has allowed it", () => {
    render(<OrgApprovalWaiver org={org({ chat_may_waive_approvals: true })} />, { wrapper });

    expect(screen.getByRole("switch")).toBeChecked();
  });

  it("saves the change and says which way it went", async () => {
    render(<OrgApprovalWaiver org={org()} />, { wrapper });

    await userEvent.click(screen.getByRole("switch"));

    await waitFor(() =>
      expect(apiClient.patch).toHaveBeenCalledWith("/orgs/org-1", {
        chat_may_waive_approvals: true,
      }),
    );
    expect(toast.success).toHaveBeenCalledWith("Conversations may now waive approvals");
  });

  it("says so when the server refuses", async () => {
    vi.mocked(apiClient.patch).mockRejectedValue(new Error("Needs approvals:decide"));
    render(<OrgApprovalWaiver org={org()} />, { wrapper });

    await userEvent.click(screen.getByRole("switch"));

    await waitFor(() => expect(toast.error).toHaveBeenCalledWith("Needs approvals:decide"));
  });

  it("is not rendered at all for somebody who may not decide approvals", () => {
    // Hidden rather than disabled, like the spending limit beside it: raising
    // the ceiling on standing consent is a decision about the approval queue,
    // and a section that could only report a refusal is worse than none.
    state.mayDecide = false;

    render(<OrgApprovalWaiver org={org()} />, { wrapper });

    expect(screen.queryByRole("switch")).toBeNull();
  });
});
