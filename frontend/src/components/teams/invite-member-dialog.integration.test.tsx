import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { InviteMemberDialog } from "./invite-member-dialog";
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
  render(<InviteMemberDialog open onOpenChange={vi.fn()} orgId="org-1" />, { wrapper });
}

/** Answer the three requests the dialog makes, as a caller holding `role`. */
function serve(role: string) {
  vi.mocked(apiClient.get).mockImplementation((url: string) => {
    if (url === "/roles/catalog") return Promise.resolve(ROLE_CATALOG);
    if (url.startsWith("/me/permissions")) return Promise.resolve(permissionsOf(role));
    return Promise.resolve({ items: [], total: 0 });
  });
}

describe("InviteMemberDialog", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    // Three things: the invitation list, the role catalog, and who is asking -
    // the picker is derived from the last two together.
    serve("owner");
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

  it("offers an Admin no way to invite another Admin", async () => {
    // The defect: the picker offered every catalog role bar owner, whoever was
    // asking, and the service refused the ones the caller could not assign -
    // after the email address had been typed (#1028). `assignable_roles` on the
    // server is the same relation this is derived from.
    serve("admin");
    mount();

    await userEvent.click(screen.getByLabelText("Role"));

    const labels = screen.getAllByRole("option").map((option) => option.textContent?.trim());
    expect(labels).toEqual(["builder", "operator", "member", "viewer"]);
  });

  it("still starts an Admin's invite on Member", async () => {
    // The default is preserved where it is on offer, which for every built-in
    // role that may invite at all it is.
    serve("admin");
    mount();

    await waitFor(() => expect(screen.getByLabelText("Role")).toHaveTextContent("member"));
  });

  it("offers nothing, and sends nothing, until it knows who is asking", async () => {
    // A picker that offers nothing for a beat is a control somebody waits for;
    // one that offers too much is a refusal they walk into.
    vi.mocked(apiClient.get).mockReturnValue(new Promise(() => {}));
    mount();

    await userEvent.type(screen.getByLabelText("Email address"), "colleague@acme.test");

    expect(screen.getByRole("button", { name: "Send invite" })).toBeDisabled();
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
    expect(screen.queryByLabelText("Role")).toBeNull();
  });
});
