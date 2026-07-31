import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { useInvitations } from "./use-invitations";
import { apiClient } from "@/lib/api-client";
import type { Invitation, InvitationCreated } from "@/types";

vi.mock("@/lib/api-client", () => ({
  apiClient: { get: vi.fn(), post: vi.fn(), delete: vi.fn() },
}));

vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

const ORG_ID = "org-1";
const TOKEN = "a-live-bearer-credential";

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

function invitation(overrides: Partial<Invitation> = {}): Invitation {
  return {
    id: "inv-1",
    organization_id: ORG_ID,
    email: "invitee@example.com",
    role: "member",
    status: "pending",
    expires_at: "2026-08-01T00:00:00Z",
    created_at: "2026-07-25T00:00:00Z",
    ...overrides,
  };
}

async function loaded() {
  const hook = renderHook(() => useInvitations(ORG_ID), { wrapper });
  await waitFor(() => expect(hook.result.current.isLoading).toBe(false));
  return hook;
}

describe("useInvitations", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(apiClient.get).mockResolvedValue({ items: [invitation()], total: 1 });
  });

  it("revokes by id, under the organization, never by token", async () => {
    // An invitation token is a bearer credential: whoever holds it joins the
    // organization as the role offered to somebody else's address. Sending one
    // through the URL of an authenticated admin action would write it into
    // server logs and browser history, which is why the id addresses this.
    vi.mocked(apiClient.delete).mockResolvedValue(undefined);
    const { result } = await loaded();

    await act(async () => {
      await result.current.revokeInvitation("inv-1");
    });

    expect(apiClient.delete).toHaveBeenCalledWith(`/orgs/${ORG_ID}/invitations/inv-1`);
    await waitFor(() => expect(result.current.invitations).toEqual([]));
  });

  it("keeps the token out of the cached invitation it just created", async () => {
    // The token comes back once so the inviter has the link when the email does
    // not arrive. Nothing on the members page reads it, and the cache backing
    // that page is the last place a live credential should sit.
    const created: InvitationCreated = { ...invitation({ id: "inv-2" }), invitation_token: TOKEN };
    vi.mocked(apiClient.post).mockResolvedValue(created);
    const { result } = await loaded();

    await act(async () => {
      await result.current.invite({ email: "second@example.com", role: "member" });
    });

    await waitFor(() =>
      expect(result.current.invitations.map((i) => i.id)).toEqual(["inv-2", "inv-1"]),
    );
    expect(JSON.stringify(result.current.invitations)).not.toContain(TOKEN);
  });

  it("leaves the list alone when revoking fails", async () => {
    // The row disappearing from a screen whose server still has it is worse
    // than the error: the admin believes the offer was withdrawn.
    vi.mocked(apiClient.delete).mockRejectedValue(new Error("Insufficient permissions"));
    const { result } = await loaded();

    await act(async () => {
      await result.current.revokeInvitation("inv-1");
    });

    expect(result.current.invitations.map((i) => i.id)).toEqual(["inv-1"]);
  });

  it("does not fetch until an organization is named", () => {
    // Some callers mount with "" only to accept an invitation, and a request for
    // `/orgs//invitations` answers 404 in their network log.
    renderHook(() => useInvitations(""), { wrapper });

    expect(apiClient.get).not.toHaveBeenCalled();
  });

  it("refreshes the list on demand, and does nothing without an organization", async () => {
    const hook = await loaded();

    await act(async () => {
      hook.result.current.fetchInvitations();
    });
    await waitFor(() => expect(apiClient.get).toHaveBeenCalledTimes(2));

    const { result } = renderHook(() => useInvitations(""), { wrapper });
    result.current.fetchInvitations();
    expect(apiClient.get).toHaveBeenCalledTimes(2);
  });

  it("reports a refused invitation rather than raising it", async () => {
    const { toast } = await import("sonner");
    vi.mocked(apiClient.post).mockRejectedValue(new Error("Already a member"));
    const hook = await loaded();

    let sent: Invitation | null | undefined;
    await act(async () => {
      sent = await hook.result.current.invite({ email: "x@example.com", role: "member" });
    });

    expect(sent).toBeNull();
    expect(toast.error).toHaveBeenCalledWith("Failed to send invitation");
  });

  it("accepts an invitation on the route that is the accept", async () => {
    // `POST /invitations/<token>/accept` hit no route at all and came back as the
    // 404 page, which the swallowed failure then announced as success.
    const { toast } = await import("sonner");
    vi.mocked(apiClient.post).mockResolvedValue({});
    const hook = await loaded();

    await act(async () => {
      await hook.result.current.acceptInvitation(TOKEN);
    });

    expect(apiClient.post).toHaveBeenCalledWith(`/invitations/${TOKEN}`);
    expect(toast.success).toHaveBeenCalledWith("Joined organization!");
  });

  it("raises a refused accept, so the screen can say nobody joined", async () => {
    const { toast } = await import("sonner");
    vi.mocked(apiClient.post).mockRejectedValue(new Error("This link has expired"));
    const hook = await loaded();

    await expect(hook.result.current.acceptInvitation(TOKEN)).rejects.toThrow(
      "This link has expired",
    );
    expect(toast.error).toHaveBeenCalledWith("Failed to accept invitation");
  });

  it("hands a shareable link back once, and keeps its token out of the cache", async () => {
    // A link nobody can copy is a link that does nothing - but the listing this
    // cache backs still carries no tokens.
    vi.mocked(apiClient.post).mockResolvedValue({
      ...invitation({ id: "inv-link" }),
      invitation_token: TOKEN,
    } as InvitationCreated);
    const hook = await loaded();

    let url: string | null | undefined;
    await act(async () => {
      url = await hook.result.current.createLink({ role: "member" });
    });

    expect(apiClient.post).toHaveBeenCalledWith(`/orgs/${ORG_ID}/invitations/link`, {
      role: "member",
    });
    expect(url).toBe(`${window.location.origin}/invitations/${TOKEN}`);
    await waitFor(() =>
      expect(hook.result.current.invitations[0]).not.toHaveProperty("invitation_token"),
    );
  });

  it("reports a refused link rather than handing back a broken one", async () => {
    const { toast } = await import("sonner");
    vi.mocked(apiClient.post).mockRejectedValue(new Error("nope"));
    const hook = await loaded();

    let url: string | null | undefined;
    await act(async () => {
      url = await hook.result.current.createLink({ role: "member" });
    });

    expect(url).toBeNull();
    expect(toast.error).toHaveBeenCalledWith("Failed to create the link");
  });
});
