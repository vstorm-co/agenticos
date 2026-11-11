import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { toast } from "sonner";

import { OrgPublicAttribution } from "./org-public-attribution";
import type { Organization } from "@/types";

const { can, save } = vi.hoisted(() => ({ can: vi.fn(), save: vi.fn() }));
vi.mock("@/hooks", () => ({
  usePermissions: () => ({ can }),
  useOrganizations: () => ({ setPublicAttribution: save }),
}));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

const org: Organization = {
  id: "org-1",
  name: "Acme",
  slug: "acme",
  avatar_url: null,
  avatar_color: null,
  is_personal: false,
  owner_id: "owner",
  stripe_customer_id: null,
  subscription_tier: "free",
  seats_limit: null,
  monthly_budget_usd: null,
  chat_may_waive_approvals: false,
  public_live_data: false,
  speech_to_text_provider: null,
  speech_to_text_model: null,
  speech_to_text_secret_id: null,
  speech_to_text_language: null,
  dictation_max_seconds: 300,
  created_at: "2026-11-11T00:00:00Z",
  updated_at: null,
};

beforeEach(() => {
  vi.clearAllMocks();
  can.mockReturnValue(true);
  save.mockResolvedValue(org);
});

describe("public page attribution setting", () => {
  it("hides the control without organization settings permission", () => {
    can.mockReturnValue(false);
    render(<OrgPublicAttribution org={org} />);
    expect(screen.queryByRole("switch")).not.toBeInTheDocument();
  });
  it("defaults to on with older responses and sends false when switched off", async () => {
    const { rerender } = render(<OrgPublicAttribution org={org} />);
    expect(screen.getByRole("switch")).toBeChecked();
    await userEvent.click(screen.getByRole("switch"));
    await waitFor(() => expect(save).toHaveBeenCalledWith("org-1", false));
    rerender(<OrgPublicAttribution org={{ ...org, public_agenticos_attribution: false }} />);
    expect(screen.getByRole("switch")).not.toBeChecked();
    await userEvent.click(screen.getByRole("switch"));
    await waitFor(() => expect(save).toHaveBeenLastCalledWith("org-1", true));
  });
  it("keeps the old setting and reports a failed write", async () => {
    save.mockRejectedValue(new Error("Offline"));
    render(<OrgPublicAttribution org={org} />);
    await userEvent.click(screen.getByRole("switch"));
    await waitFor(() => expect(toast.error).toHaveBeenCalled());
    expect(toast.success).not.toHaveBeenCalled();
    expect(screen.getByRole("switch")).toBeChecked();
    expect(screen.getByRole("switch")).not.toBeDisabled();
  });
});
