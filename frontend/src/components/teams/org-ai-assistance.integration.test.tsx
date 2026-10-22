import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { toast } from "sonner";

import { OrgAiAssistance } from "./org-ai-assistance";
import { apiClient } from "@/lib/api-client";
import type { Organization } from "@/types";

vi.mock("@/lib/api-client", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api-client")>("@/lib/api-client");
  return { ...actual, apiClient: { get: vi.fn(), patch: vi.fn() } };
});
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

const state = vi.hoisted(() => ({ maySet: true }));
vi.mock("@/hooks/use-permissions", () => ({
  usePermissions: () => ({ can: () => state.maySet }),
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
  state.maySet = true;
  vi.mocked(apiClient.get).mockResolvedValue({ items: [], total: 0 });
  vi.mocked(apiClient.patch).mockImplementation(async (_path, body) =>
    org(body as Partial<Organization>),
  );
});

/**
 * The organization switch for model-backed evals and authoring.
 *
 * The backend refuses the runs; this is where a person with `org:settings`
 * changes it.
 */
describe("the AI assistance switch", () => {
  it("is on until somebody turns it off", () => {
    render(<OrgAiAssistance org={org()} />, { wrapper });

    expect(screen.getByRole("switch")).toBeChecked();
  });

  it("saves turning it off and says so", async () => {
    render(<OrgAiAssistance org={org()} />, { wrapper });

    await userEvent.click(screen.getByRole("switch"));

    await waitFor(() =>
      expect(apiClient.patch).toHaveBeenCalledWith("/orgs/org-1", {
        ai_assistance_enabled: false,
      }),
    );
    expect(toast.success).toHaveBeenCalledWith("AI assistance is off");
  });

  it("saves turning it back on", async () => {
    render(<OrgAiAssistance org={org({ ai_assistance_enabled: false })} />, { wrapper });

    await userEvent.click(screen.getByRole("switch"));

    await waitFor(() => expect(toast.success).toHaveBeenCalledWith("AI assistance is on"));
  });

  it("says so when the server refuses", async () => {
    vi.mocked(apiClient.patch).mockRejectedValue(new Error("Needs org:settings"));
    render(<OrgAiAssistance org={org()} />, { wrapper });

    await userEvent.click(screen.getByRole("switch"));

    await waitFor(() => expect(toast.error).toHaveBeenCalledWith("Needs org:settings"));
  });

  it("is not rendered for somebody who may not change the organization's settings", () => {
    state.maySet = false;

    render(<OrgAiAssistance org={org()} />, { wrapper });

    expect(screen.queryByRole("switch")).toBeNull();
  });
});
