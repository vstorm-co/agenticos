import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { toast } from "sonner";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { apiClient } from "@/lib/api-client";
import { ApiError } from "@/lib/api-error";
import { useOrgStore } from "@/stores";
import type { Organization } from "@/types";

import { OrgVoiceConversations } from "./org-voice-conversations";

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
    avatar_color: null,
    is_personal: false,
    owner_id: "u1",
    stripe_customer_id: null,
    chat_may_waive_approvals: false,
    subscription_tier: "free",
    seats_limit: null,
    monthly_budget_usd: null,
    chat_dictation: "browser",
    speech_to_text_provider: null,
    speech_to_text_model: null,
    speech_to_text_secret_id: null,
    speech_to_text_language: null,
    dictation_max_seconds: 300,
    chat_dictation_ready: false,
    voice_conversations_enabled: false,
    voice_in_chat: true,
    voice_max_call_seconds: 600,
    voice_monthly_minutes: 600,
    created_at: "2026-07-01T00:00:00Z",
    updated_at: null,
    ...overrides,
  };
}

/** What `/me/permissions` grants this caller. */
function grant(permissions: string[]) {
  vi.mocked(apiClient.get).mockImplementation(async (path: string) => {
    if (path === "/me/permissions") {
      return {
        organization_id: ORG_ID,
        role: "admin",
        is_app_admin: false,
        permissions: permissions.map((permission) => ({ permission, scope: "all" })),
      };
    }
    if (path === "/orgs") return { items: [org()], total: 1 };
    if (path.startsWith("/voice/usage?")) {
      return {
        start: "2026-10-01T00:00:00Z",
        end: "2026-10-14T12:00:00Z",
        seconds: 1500,
        calls: 6,
        by_agent: [],
        month_seconds: 2520,
        monthly_minutes: 600,
      };
    }
    throw new Error(`unexpected GET ${path}`);
  });
}

function refusal(field: string, message: string) {
  return new ApiError(422, "Invalid request", {
    error: {
      code: "VALIDATION_ERROR",
      message: "Invalid request",
      details: { fields: [{ field, message }] },
    },
  });
}

const LONGEST = "Longest call (minutes)";

async function typeInto(label: string, value: string) {
  const field = screen.getByLabelText(label);
  await userEvent.clear(field);
  if (value) await userEvent.type(field, value);
}

describe("OrgVoiceConversations", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useOrgStore.setState({ activeOrgId: ORG_ID });
    vi.mocked(apiClient.patch).mockImplementation(async (_path, body) => ({
      ...org(),
      ...(body as object),
    }));
  });

  it("turns calls on with a cap in minutes, sending seconds", async () => {
    grant(["org:settings", "budgets:manage"]);
    render(<OrgVoiceConversations org={org({ voice_conversations_enabled: false })} />, {
      wrapper,
    });
    const section = await screen.findByRole("heading", { name: "Voice conversations" });
    expect(section.closest("[data-tour]")).toHaveAttribute("data-tour", "org-voice-conversations");
    // Chat is offered only once calls are allowed at all.
    expect(screen.getByRole("switch", { name: "Offer calls in chat" })).toBeDisabled();

    await userEvent.click(screen.getByRole("switch", { name: "Allow voice conversations" }));
    expect(screen.getByRole("switch", { name: "Offer calls in chat" })).toBeEnabled();
    await typeInto(LONGEST, "15");
    await userEvent.click(screen.getByRole("button", { name: "Save changes" }));

    await waitFor(() =>
      expect(apiClient.patch).toHaveBeenCalledWith("/orgs/org-1", {
        voice_conversations_enabled: true,
        voice_max_call_seconds: 900,
      }),
    );
    expect(toast.success).toHaveBeenCalledWith("Voice conversation settings saved");
  });

  it("refuses a cap past fifty minutes before sending", async () => {
    grant(["org:settings"]);
    render(<OrgVoiceConversations org={org()} />, { wrapper });
    await screen.findByLabelText(LONGEST);
    await typeInto(LONGEST, "55");
    await userEvent.click(screen.getByRole("button", { name: "Save changes" }));
    expect(screen.getByText("Enter between 1 and 50 minutes.")).toBeInTheDocument();
    expect(screen.getByLabelText(LONGEST)).toHaveAttribute("aria-invalid", "true");
    expect(apiClient.patch).not.toHaveBeenCalled();

    // Typing again clears the complaint.
    await typeInto(LONGEST, "1.5");
    expect(screen.queryByText("Enter between 1 and 50 minutes.")).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: "Save changes" }));
    expect(screen.getByText("Enter between 1 and 50 minutes.")).toBeInTheDocument();
  });

  it("shows the monthly minutes read-only to somebody without budgets:manage, and never sends them", async () => {
    grant(["org:settings"]);
    render(
      <OrgVoiceConversations
        org={org({ voice_conversations_enabled: true, voice_monthly_minutes: 600 })}
      />,
      { wrapper },
    );
    expect(await screen.findByText("600 call minutes a month")).toBeInTheDocument();
    expect(screen.queryByLabelText("Monthly call minutes")).toBeNull();
    await userEvent.click(screen.getByRole("switch", { name: "Offer calls in chat" }));
    await userEvent.click(screen.getByRole("button", { name: "Save changes" }));
    await waitFor(() => expect(apiClient.patch).toHaveBeenCalled());
    expect(vi.mocked(apiClient.patch).mock.calls[0]?.[1]).toEqual({ voice_in_chat: false });
  });

  it("says there is no monthly limit to somebody who cannot change it", async () => {
    grant(["org:settings"]);
    render(<OrgVoiceConversations org={org({ voice_monthly_minutes: null })} />, { wrapper });
    expect(await screen.findByText("No monthly limit")).toBeInTheDocument();
  });

  it("lets a budget manager clear the minutes to rely on budgets alone", async () => {
    grant(["org:settings", "budgets:manage"]);
    render(<OrgVoiceConversations org={org({ voice_monthly_minutes: 600 })} />, { wrapper });
    await userEvent.click(
      await screen.findByRole("checkbox", { name: "No monthly limit (budgets only)" }),
    );
    expect(screen.getByLabelText("Monthly call minutes")).toBeDisabled();
    await userEvent.click(screen.getByRole("button", { name: "Save changes" }));
    await waitFor(() =>
      expect(apiClient.patch).toHaveBeenCalledWith("/orgs/org-1", { voice_monthly_minutes: null }),
    );
  });

  it("lets a budget manager set the monthly minutes, and refuses one that is not a count", async () => {
    grant(["org:settings", "budgets:manage"]);
    render(<OrgVoiceConversations org={org({ voice_monthly_minutes: null })} />, { wrapper });
    await userEvent.click(
      await screen.findByRole("checkbox", { name: "No monthly limit (budgets only)" }),
    );
    await typeInto("Monthly call minutes", "0");
    await userEvent.click(screen.getByRole("button", { name: "Save changes" }));
    expect(screen.getByText("Enter a whole number of minutes above 0.")).toBeInTheDocument();
    expect(apiClient.patch).not.toHaveBeenCalled();

    await typeInto("Monthly call minutes", "900");
    await userEvent.click(screen.getByRole("button", { name: "Save changes" }));
    await waitFor(() =>
      expect(apiClient.patch).toHaveBeenCalledWith("/orgs/org-1", { voice_monthly_minutes: 900 }),
    );
  });

  it("has nothing to save when edits cancel out", async () => {
    grant(["org:settings", "budgets:manage"]);
    render(<OrgVoiceConversations org={org({ voice_monthly_minutes: null })} />, { wrapper });
    const unlimited = await screen.findByRole("checkbox", {
      name: "No monthly limit (budgets only)",
    });
    await userEvent.click(unlimited);
    await typeInto("Monthly call minutes", "900");
    expect(screen.getByRole("button", { name: "Save changes" })).toBeEnabled();
    await userEvent.click(unlimited);
    expect(screen.getByRole("button", { name: "Save changes" })).toBeDisabled();
    await typeInto(LONGEST, "11");
    await typeInto(LONGEST, "10");
    expect(screen.getByRole("button", { name: "Save changes" })).toBeDisabled();
  });

  it("puts a draft back with Cancel", async () => {
    grant(["org:settings"]);
    render(<OrgVoiceConversations org={org()} />, { wrapper });
    await screen.findByLabelText(LONGEST);
    await typeInto(LONGEST, "55");
    await userEvent.click(screen.getByRole("button", { name: "Save changes" }));
    await userEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(screen.getByLabelText(LONGEST)).toHaveValue("10");
    expect(screen.queryByText("Enter between 1 and 50 minutes.")).toBeNull();
    expect(screen.getByRole("button", { name: "Save changes" })).toBeDisabled();
  });

  it("marks the field the server refused", async () => {
    grant(["org:settings"]);
    vi.mocked(apiClient.patch).mockRejectedValue(refusal("voice_max_call_seconds", "Too long"));
    render(<OrgVoiceConversations org={org()} />, { wrapper });
    await screen.findByLabelText(LONGEST);
    await typeInto(LONGEST, "20");
    await userEvent.click(screen.getByRole("button", { name: "Save changes" }));
    expect(await screen.findByText("Too long")).toBeInTheDocument();
    expect(toast.error).not.toHaveBeenCalled();
  });

  it("puts a refusal about a switch under that switch", async () => {
    grant(["org:settings"]);
    vi.mocked(apiClient.patch).mockRejectedValue(
      refusal("voice_conversations_enabled", "Not on this plan"),
    );
    render(<OrgVoiceConversations org={org()} />, { wrapper });
    await userEvent.click(await screen.findByRole("switch", { name: "Allow voice conversations" }));
    await userEvent.click(screen.getByRole("button", { name: "Save changes" }));
    expect(await screen.findByText("Not on this plan")).toHaveClass("text-destructive");
  });

  it("toasts a refusal that names no field", async () => {
    grant(["org:settings"]);
    vi.mocked(apiClient.patch).mockRejectedValue(new ApiError(500, "Server exploded"));
    render(<OrgVoiceConversations org={org()} />, { wrapper });
    await userEvent.click(await screen.findByRole("switch", { name: "Allow voice conversations" }));
    await userEvent.click(screen.getByRole("button", { name: "Save changes" }));
    await waitFor(() => expect(toast.error).toHaveBeenCalled());
  });

  it("tells somebody who may read runs how much of the month's minutes calls used", async () => {
    grant(["org:settings", "runs:view"]);
    render(<OrgVoiceConversations org={org({ voice_monthly_minutes: 600 })} />, { wrapper });
    expect(await screen.findByText("Call minutes used this month: 42 of 600")).toBeInTheDocument();
    // The window is this calendar month so far, from its first UTC midnight.
    const now = new Date();
    const monthStart = new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), 1));
    const asked = vi.mocked(apiClient.get).mock.calls.map(([path]) => String(path));
    const usage = new URLSearchParams(
      asked.find((path) => path.startsWith("/voice/usage?"))?.split("?")[1],
    );
    expect(usage.get("start")).toBe(monthStart.toISOString());
  });

  it("states the month's minutes alone when only budgets bound calls", async () => {
    grant(["org:settings", "runs:view"]);
    render(<OrgVoiceConversations org={org({ voice_monthly_minutes: null })} />, { wrapper });
    expect(await screen.findByText("Call minutes used this month: 42")).toBeInTheDocument();
  });

  it("never asks for the minutes used without runs:view", async () => {
    grant(["org:settings"]);
    render(<OrgVoiceConversations org={org()} />, { wrapper });
    await screen.findByLabelText(LONGEST);
    const asked = vi.mocked(apiClient.get).mock.calls.map(([path]) => String(path));
    expect(asked.some((path) => path.startsWith("/voice/usage"))).toBe(false);
    expect(screen.queryByText(/Call minutes used this month/)).toBeNull();
  });
});
