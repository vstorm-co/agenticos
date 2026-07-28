import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { InviteLinkDialog } from "./invite-link-dialog";
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
  render(<InviteLinkDialog open onOpenChange={vi.fn()} orgId="org-1" />, { wrapper });
}

describe("InviteLinkDialog", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(apiClient.get).mockResolvedValue({ items: [], total: 0 });
    vi.mocked(apiClient.post).mockResolvedValue({
      id: "inv-1",
      organization_id: "org-1",
      email: null,
      role: "member",
      status: "pending",
      max_uses: 25,
      used_count: 0,
      email_domain: null,
      invitation_token: "tok-abc",
      expires_at: null,
      created_at: "2026-07-28T00:00:00Z",
    });
  });

  it("sends the limits the administrator chose", async () => {
    mount();

    await userEvent.clear(screen.getByLabelText("How many people"));
    await userEvent.type(screen.getByLabelText("How many people"), "5");
    await userEvent.type(screen.getByLabelText("Only this email domain"), "acme.com");
    await userEvent.click(screen.getByRole("button", { name: "Create link" }));

    await waitFor(() =>
      expect(apiClient.post).toHaveBeenCalledWith("/orgs/org-1/invitations/link", {
        role: "member",
        max_uses: 5,
        email_domain: "acme.com",
      }),
    );
  });

  it("shows the URL once, because no later request returns it", async () => {
    mount();

    await userEvent.click(screen.getByRole("button", { name: "Create link" }));

    expect(await screen.findByText(/\/invitations\/tok-abc$/)).toBeInTheDocument();
  });

  it("warns when a link is both unlimited and open to any address", async () => {
    // Not a refusal - it is a legitimate thing to want. But a URL in a channel
    // can be forwarded, and that has to be said where the choice is made.
    mount();

    await userEvent.clear(screen.getByLabelText("How many people"));

    expect(screen.getByText(/still a working link/)).toBeInTheDocument();
  });

  it("does not offer owner, because ownership moves by transfer", async () => {
    mount();

    await userEvent.click(screen.getByLabelText("Join as"));

    expect(screen.queryByRole("option", { name: /^owner$/i })).toBeNull();
    expect(screen.getByRole("option", { name: /^builder$/i })).toBeInTheDocument();
  });
});
