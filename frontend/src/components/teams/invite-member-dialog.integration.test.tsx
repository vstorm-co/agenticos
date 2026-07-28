import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { InviteMemberDialog } from "./invite-member-dialog";
import { apiClient } from "@/lib/api-client";

vi.mock("@/lib/api-client", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api-client")>("@/lib/api-client");
  return {
    ...actual,
    apiClient: { ...actual.apiClient, get: vi.fn(), post: vi.fn() },
  };
});
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

function mount() {
  render(<InviteMemberDialog open onOpenChange={vi.fn()} orgId="org-1" />, { wrapper });
}

describe("InviteMemberDialog", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    // The dialog fetches two things: the invitation list and the role catalog
    // the picker is derived from.
    vi.mocked(apiClient.get).mockImplementation((url: string) =>
      url === "/roles/catalog"
        ? Promise.resolve({
            all_permissions: [],
            resource_permissions: [],
            roles: [
              { name: "owner", permissions: [] },
              { name: "admin", permissions: [] },
              { name: "builder", permissions: [] },
              { name: "operator", permissions: [] },
              { name: "member", permissions: [] },
              { name: "viewer", permissions: [] },
            ],
          })
        : Promise.resolve({ items: [], total: 0 }),
    );
    vi.mocked(apiClient.post).mockResolvedValue({
      id: "inv-1",
      organization_id: "org-1",
      email: "colleague@acme.test",
      role: "operator",
      status: "pending",
      max_uses: null,
      used_count: 0,
      email_domain: null,
      invitation_token: "tok-abc",
      expires_at: null,
      created_at: "2026-07-28T00:00:00Z",
    });
  });

  it("offers every role the deployment has, not just admin and member", async () => {
    // The regression: this platform seeds six roles and the picker offered two,
    // so "builder" and "operator" were unreachable from an emailed invitation.
    mount();

    await userEvent.click(screen.getByLabelText("Role"));

    const labels = screen.getAllByRole("option").map((option) => option.textContent?.trim());

    expect(labels).toEqual(["admin", "builder", "operator", "member", "viewer"]);
  });

  it("never offers owner, because ownership moves by transfer", async () => {
    mount();

    await userEvent.click(screen.getByLabelText("Role"));

    expect(screen.queryByRole("option", { name: /^owner$/i })).toBeNull();
  });

  it("sends the role the administrator chose", async () => {
    mount();

    await userEvent.type(screen.getByLabelText("Email address"), "colleague@acme.test");
    await userEvent.click(screen.getByLabelText("Role"));
    await userEvent.click(screen.getByRole("option", { name: /^operator$/i }));
    await userEvent.click(screen.getByRole("button", { name: "Send invite" }));

    await waitFor(() =>
      expect(apiClient.post).toHaveBeenCalledWith("/orgs/org-1/invitations", {
        email: "colleague@acme.test",
        role: "operator",
      }),
    );
  });
});
