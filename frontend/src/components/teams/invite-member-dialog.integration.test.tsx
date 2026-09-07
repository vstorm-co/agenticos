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
      email_delivered: true,
      expires_at: null,
      created_at: "2026-07-28T00:00:00Z",
    });
  });

  /** The reply to a successful invite, with delivery as the server reported it. */
  function created(emailDelivered: boolean | null) {
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
      email_delivered: emailDelivered,
      expires_at: null,
      created_at: "2026-07-28T00:00:00Z",
    });
  }

  async function send() {
    await userEvent.type(screen.getByLabelText("Email address"), "colleague@acme.test");
    await userEvent.click(screen.getByRole("button", { name: "Send invite" }));
  }

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
  it("hands over the link, because nothing else will", async () => {
    // The whole point. The token is returned once, is not cached and is in no
    // listing, so a dialog that closed on success threw away the only copy - and
    // on a deployment with no mail service, nobody had been sent anything
    // either (#1484).
    created(false);
    mount();
    await waitFor(() => expect(screen.getByLabelText("Role")).toBeInTheDocument());

    await send();

    const link = await screen.findByLabelText("Invitation link");
    expect(link).toHaveValue(`${window.location.origin}/invitations/tok-abc`);
    expect(link).toHaveAttribute("readonly");
  });

  it("does not claim to have emailed anything when it did not", async () => {
    created(false);
    mount();
    await waitFor(() => expect(screen.getByLabelText("Role")).toBeInTheDocument());

    await send();

    expect(await screen.findByText(/did not send one/)).toBeInTheDocument();
    expect(screen.queryByText(/^Emailed to/)).not.toBeInTheDocument();
  });

  it("says it was emailed when the server says it was", async () => {
    created(true);
    mount();
    await waitFor(() => expect(screen.getByLabelText("Role")).toBeInTheDocument());

    await send();

    expect(await screen.findByText(/Emailed to colleague@acme.test/)).toBeInTheDocument();
    // And still offers the link: the copy for the sender is the point of it
    // being returned at all, whether or not the mail went.
    expect(screen.getByLabelText("Invitation link")).toBeInTheDocument();
  });

  it("stays open holding the link rather than closing on success", async () => {
    const onOpenChange = vi.fn();
    created(false);
    render(<InviteMemberDialog open onOpenChange={onOpenChange} orgId="org-1" />, { wrapper });
    await waitFor(() => expect(screen.getByLabelText("Role")).toBeInTheDocument());

    await send();
    await screen.findByLabelText("Invitation link");

    expect(onOpenChange).not.toHaveBeenCalledWith(false);
  });

  it("closes when the sender is done with the link", async () => {
    const onOpenChange = vi.fn();
    created(false);
    render(<InviteMemberDialog open onOpenChange={onOpenChange} orgId="org-1" />, { wrapper });
    await waitFor(() => expect(screen.getByLabelText("Role")).toBeInTheDocument());
    await send();
    await screen.findByLabelText("Invitation link");

    await userEvent.click(screen.getByRole("button", { name: "Done" }));

    expect(onOpenChange).toHaveBeenCalledWith(false);
  });

  it("offers a copy control somebody can actually see", async () => {
    // Not `CopyButton`, which is `opacity-0` outside a hovered `group` - in a
    // dialog that makes the primary action permanently invisible, including to
    // the keyboard, and a test asserting on the field would not notice.
    created(false);
    mount();
    await waitFor(() => expect(screen.getByLabelText("Role")).toBeInTheDocument());

    await send();
    await screen.findByLabelText("Invitation link");

    expect(screen.getByRole("button", { name: "Copy" })).toBeVisible();
  });

  it("cannot be dismissed while the request carrying the link is out", async () => {
    // Escape, the backdrop and the close icon all reach the same handler, and
    // between the submit and its answer the request holds the only copy of the
    // token - so a dismissal there creates a pending invitation into an empty
    // screen.
    const onOpenChange = vi.fn();
    let answer: (value: unknown) => void = () => {};
    vi.mocked(apiClient.post).mockImplementation(
      () => new Promise((resolve) => (answer = resolve)),
    );
    render(<InviteMemberDialog open onOpenChange={onOpenChange} orgId="org-1" />, { wrapper });
    await waitFor(() => expect(screen.getByLabelText("Role")).toBeInTheDocument());

    await send();
    await userEvent.keyboard("{Escape}");

    expect(onOpenChange).not.toHaveBeenCalledWith(false);
    expect(screen.getByRole("button", { name: "Cancel" })).toBeDisabled();
    answer({});
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
