import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { toast } from "sonner";

import { OrgRoutineTrust } from "./org-routine-trust";
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
    speech_to_text_provider: null,
    speech_to_text_model: null,
    speech_to_text_secret_id: null,
    speech_to_text_language: null,
    dictation_max_seconds: 300,
    chat_may_waive_approvals: false,
    public_live_data: false,
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
 * Whether routines may trust their agent: follow its future access without a
 * new review. Off until somebody who may decide approvals turns it on.
 */
describe("the routine trust switch", () => {
  it("is off until somebody turns it on, including on a server that omits it", () => {
    render(<OrgRoutineTrust org={org()} />, { wrapper });

    expect(
      screen.getByRole("switch", { name: "Routines may trust their agent" }),
    ).not.toBeChecked();
  });

  it("reflects an organization that has allowed it", () => {
    render(<OrgRoutineTrust org={org({ routines_may_trust_agent: true })} />, { wrapper });

    expect(screen.getByRole("switch")).toBeChecked();
  });

  it("saves the change and says which way it went", async () => {
    render(<OrgRoutineTrust org={org()} />, { wrapper });

    await userEvent.click(screen.getByRole("switch"));

    await waitFor(() =>
      expect(apiClient.patch).toHaveBeenCalledWith("/orgs/org-1", {
        routines_may_trust_agent: true,
      }),
    );
    expect(toast.success).toHaveBeenCalledWith("Routines may now trust their agent");
  });

  it("says when it was turned off", async () => {
    render(<OrgRoutineTrust org={org({ routines_may_trust_agent: true })} />, { wrapper });

    await userEvent.click(screen.getByRole("switch"));

    await waitFor(() =>
      expect(toast.success).toHaveBeenCalledWith("Routines can no longer trust their agent"),
    );
  });

  it("says so when the server refuses", async () => {
    vi.mocked(apiClient.patch).mockRejectedValue(new Error("Needs approvals:decide"));
    render(<OrgRoutineTrust org={org()} />, { wrapper });

    await userEvent.click(screen.getByRole("switch"));

    await waitFor(() => expect(toast.error).toHaveBeenCalledWith("Needs approvals:decide"));
  });

  it("is not rendered at all for somebody who may not decide approvals", () => {
    state.mayDecide = false;

    render(<OrgRoutineTrust org={org()} />, { wrapper });

    expect(screen.queryByRole("switch")).toBeNull();
  });
});
