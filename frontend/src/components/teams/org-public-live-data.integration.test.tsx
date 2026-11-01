import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { toast } from "sonner";

import { OrgPublicLiveData } from "./org-public-live-data";
import { apiClient } from "@/lib/api-client";
import type { Organization } from "@/types";

vi.mock("@/lib/api-client", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api-client")>("@/lib/api-client");
  return { ...actual, apiClient: { get: vi.fn(), patch: vi.fn() } };
});
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

const state = vi.hoisted(() => ({ mayChange: true }));
vi.mock("@/hooks/use-permissions", () => ({
  usePermissions: () => ({ can: (perm: string) => perm === "org:settings" && state.mayChange }),
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
    ai_assistance_enabled: true,
    public_live_data: false,
    speech_to_text_provider: null,
    speech_to_text_model: null,
    speech_to_text_secret_id: null,
    speech_to_text_language: null,
    dictation_max_seconds: 300,
    created_at: "2026-08-01T00:00:00Z",
    updated_at: null,
    ...overrides,
  };
}

beforeEach(() => {
  vi.clearAllMocks();
  state.mayChange = true;
  vi.mocked(apiClient.get).mockResolvedValue({ items: [], total: 0 });
  vi.mocked(apiClient.patch).mockImplementation(async (_path, body) =>
    org(body as Partial<Organization>),
  );
});

/** The organization's ceiling on page data reaching people with no account (#1975). */
describe("the public live data switch", () => {
  it("is off until somebody turns it on", () => {
    render(<OrgPublicLiveData org={org()} />, { wrapper });

    expect(screen.getByRole("switch", { name: "Public pages with live data" })).not.toBeChecked();
  });

  it("reflects an organization that has allowed it", () => {
    render(<OrgPublicLiveData org={org({ public_live_data: true })} />, { wrapper });

    expect(screen.getByRole("switch")).toBeChecked();
  });

  it("asks first when turning it on, and sends only that field", async () => {
    render(<OrgPublicLiveData org={org()} />, { wrapper });

    await userEvent.click(screen.getByRole("switch"));

    const dialog = await screen.findByRole("dialog");
    expect(dialog).toHaveTextContent(
      "Anyone with a page's public link, and every site that embeds it, will see its table data without signing in",
    );
    expect(apiClient.patch).not.toHaveBeenCalled();
    await userEvent.click(within(dialog).getByRole("button", { name: "Allow" }));

    await waitFor(() =>
      expect(apiClient.patch).toHaveBeenCalledWith("/orgs/org-1", { public_live_data: true }),
    );
    expect(toast.success).toHaveBeenCalledWith("Public pages may now show live data");
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  });

  it("changes nothing when the question is cancelled", async () => {
    render(<OrgPublicLiveData org={org()} />, { wrapper });

    await userEvent.click(screen.getByRole("switch"));
    await userEvent.click(
      within(await screen.findByRole("dialog")).getByRole("button", { name: "Cancel" }),
    );

    expect(apiClient.patch).not.toHaveBeenCalled();
    expect(screen.getByRole("switch")).not.toBeChecked();
  });

  it("turns it off at once, without asking, which only narrows", async () => {
    render(<OrgPublicLiveData org={org({ public_live_data: true })} />, { wrapper });

    await userEvent.click(screen.getByRole("switch"));

    await waitFor(() =>
      expect(apiClient.patch).toHaveBeenCalledWith("/orgs/org-1", { public_live_data: false }),
    );
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(toast.success).toHaveBeenCalledWith("Public pages no longer show live data");
  });

  it("says so when the server refuses, and keeps the question open", async () => {
    vi.mocked(apiClient.patch).mockRejectedValue(new Error("Needs org:settings"));
    render(<OrgPublicLiveData org={org()} />, { wrapper });

    await userEvent.click(screen.getByRole("switch"));
    await userEvent.click(
      within(await screen.findByRole("dialog")).getByRole("button", { name: "Allow" }),
    );

    await waitFor(() => expect(toast.error).toHaveBeenCalledWith("Needs org:settings"));
    expect(screen.getByRole("dialog")).toBeVisible();
  });

  it("is not rendered for somebody who may not change organization settings", () => {
    state.mayChange = false;

    render(<OrgPublicLiveData org={org()} />, { wrapper });

    expect(screen.queryByRole("switch")).toBeNull();
  });
});
