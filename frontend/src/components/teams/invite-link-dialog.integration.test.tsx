import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { InviteLinkDialog } from "./invite-link-dialog";
import { apiClient } from "@/lib/api-client";
import { permissionsOf, ROLE_CATALOG } from "@/test-utils/role-catalog";

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

/** Answer the three requests the dialog makes, as a caller holding `role`. */
function serve(role: string) {
  vi.mocked(apiClient.get).mockImplementation((url: string) => {
    if (url === "/roles/catalog") return Promise.resolve(ROLE_CATALOG);
    if (url.startsWith("/me/permissions")) return Promise.resolve(permissionsOf(role));
    return Promise.resolve({ items: [], total: 0 });
  });
}

describe("InviteLinkDialog", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    // Three things: the invitation list, the role catalog, and who is asking -
    // the picker is derived from the last two together.
    serve("owner");
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

  it("offers an Admin no way to mint a link that joins as Admin", async () => {
    // A link is the wider of the two paths - one URL, many joiners - and it took
    // the same offer-then-refuse as the email invite: the picker listed every
    // catalog role bar owner whoever was asking (#1028).
    serve("admin");
    mount();

    await userEvent.click(screen.getByLabelText("Join as"));

    const labels = screen.getAllByRole("option").map((option) => option.textContent?.trim());
    expect(labels).toEqual(["builder", "operator", "member", "viewer"]);
  });

  it("mints nothing until it knows who is asking", async () => {
    vi.mocked(apiClient.get).mockReturnValue(new Promise(() => {}));
    mount();

    expect(screen.getByRole("button", { name: /create link/i })).toBeDisabled();
  });
  it("says the role list could not be read, rather than offering an empty picker", async () => {
    // A catalog that failed and a caller who may assign nothing render the same
    // way, and only one of them is worth reloading the page over (#1028).
    vi.mocked(apiClient.get).mockImplementation((url: string) =>
      url === "/roles/catalog"
        ? Promise.reject(new Error("nope"))
        : Promise.resolve({ items: [], total: 0 }),
    );
    mount();

    expect(await screen.findByText(/role list could not be loaded/i)).toBeVisible();
    expect(screen.queryByLabelText("Join as")).toBeNull();
  });
});
