import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ShareDialog, sharedPerson, toPermission } from "./share-dialog";
import type { OrganizationMember } from "@/types";

const shareConversation = vi.fn();
const fetchShares = vi.fn();
const revokeShare = vi.fn();
const listedMembers = vi.fn<() => OrganizationMember[]>(() => []);
const listedShares = vi.fn<() => Record<string, unknown>[]>(() => []);

vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));
vi.mock("@/hooks", () => ({
  useConversationShares: () => ({
    shares: listedShares(),
    isLoading: false,
    shareConversation,
    fetchShares,
    revokeShare,
  }),
  useMembers: () => ({ members: listedMembers() }),
}));
// Imported by its own path rather than through the barrel, so it is mocked by
// that path too.
vi.mock("@/hooks/use-copy-to-clipboard", () => ({
  useCopyToClipboard: () => ({ copy: copySpy, copied: false }),
}));
vi.mock("@/stores", () => ({
  useOrgStore: (pick: (state: unknown) => unknown) => pick({ activeOrgId: "org-1" }),
}));

const member = (userId: string, email: string, fullName: string | null = null) =>
  ({
    id: `m-${userId}`,
    organization_id: "org-1",
    user_id: userId,
    role: "member",
    email,
    full_name: fullName,
    avatar_url: null,
    avatar_color: null,
    joined_at: "2026-01-01T00:00:00Z",
  }) satisfies OrganizationMember;

const MEMBERS: OrganizationMember[] = [
  member("u1", "sam@example.com", "Sam Fisher"),
  member("u2", "nina@example.com", "Nina Vale"),
];

const copySpy = vi.fn(async () => true);

function renderDialog() {
  render(<ShareDialog conversationId="c1" open onOpenChange={vi.fn()} />);
}

beforeEach(() => {
  vi.clearAllMocks();
  listedMembers.mockReturnValue(MEMBERS);
  listedShares.mockReturnValue([]);
  shareConversation.mockResolvedValue({ id: "s-1" });
  revokeShare.mockResolvedValue(undefined);
});

async function openPicker() {
  await userEvent.click(screen.getByRole("button", { name: /Choose someone|Sam|Nina/ }));
}

async function pick(name: RegExp) {
  await openPicker();
  await userEvent.click(screen.getByRole("option", { name }));
}

describe("toPermission", () => {
  it("takes the two levels a conversation has", () => {
    expect(toPermission("view")).toBe("view");
    expect(toPermission("edit")).toBe("edit");
  });

  it("refuses anything else rather than defaulting", () => {
    // Radix hands back a plain string. A level the catalog does not know is a
    // bug in the caller, and defaulting would grant whichever one is first.
    expect(() => toPermission("owner")).toThrow(/Unknown conversation permission/);
  });
});

describe("sharedPerson", () => {
  it("draws a share as the member it names", () => {
    const person = sharedPerson(
      { id: "s-1", shared_with: "u1", permission: "view" } as never,
      MEMBERS,
    );

    expect(person).toMatchObject({ user_id: "u1", email: "sam@example.com" });
  });

  it("falls back to the address for a share whose member is gone", () => {
    // Still revocable, which is what the row is for.
    const person = sharedPerson(
      {
        id: "s-1",
        shared_with: "u-9",
        shared_with_email: "gone@example.com",
        permission: "view",
      } as never,
      MEMBERS,
    );

    expect(person).toMatchObject({ user_id: "u-9", email: "gone@example.com" });
  });

  it("keys a share that names only an address on the share itself", () => {
    // It still has to be revocable, and the row needs a stable key.
    const person = sharedPerson(
      { id: "s-7", shared_with_email: "invited@example.com", permission: "view" } as never,
      MEMBERS,
    );

    expect(person).toMatchObject({ user_id: "s-7", email: "invited@example.com" });
  });

  it("answers with nobody for a link", () => {
    expect(
      sharedPerson({ id: "s-2", share_token: "tok", permission: "view" } as never, MEMBERS),
    ).toBeNull();
  });
});

describe("choosing who to share with", () => {
  it("has no email field at all", () => {
    // The whole of #931: a blank box you had to already know the answer to fill,
    // and every mistyped address a 404.
    renderDialog();

    expect(screen.queryByLabelText("Email address")).not.toBeInTheDocument();
    expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
  });

  it("offers the organization before anything is typed", async () => {
    renderDialog();

    await openPicker();

    expect(screen.getByRole("option", { name: /Sam Fisher/ })).toBeVisible();
    expect(screen.getByRole("option", { name: /Nina Vale/ })).toBeVisible();
  });

  it("says who is chosen, on the thing you press", async () => {
    renderDialog();

    await pick(/Nina Vale/);

    expect(screen.getByRole("button", { name: "Nina Vale" })).toBeVisible();
  });

  it("does not offer somebody who already has access", async () => {
    // Offering them again is a row that answers "already shared" after the click
    // rather than before it.
    listedShares.mockReturnValue([{ id: "s-1", shared_with: "u1", permission: "view" }]);
    renderDialog();

    await openPicker();

    expect(screen.queryByRole("option", { name: /Sam Fisher/ })).not.toBeInTheDocument();
    expect(screen.getByRole("option", { name: /Nina Vale/ })).toBeVisible();
  });

  it("shares with the id the picker holds, not an address", async () => {
    // `shared_with` has always been accepted beside `shared_with_email`, so
    // this is a client change rather than a contract one - and it cannot name
    // somebody outside the organization.
    renderDialog();
    await pick(/Nina Vale/);

    await userEvent.click(screen.getByRole("button", { name: "Share conversation" }));

    expect(shareConversation).toHaveBeenCalledWith("c1", {
      shared_with: "u2",
      permission: "view",
    });
  });

  it("cannot be pressed until somebody is picked", async () => {
    // The disabled state *is* the guard: a handler that re-checked would hold a
    // branch nothing can reach.
    renderDialog();

    expect(screen.getByRole("button", { name: "Share conversation" })).toBeDisabled();
    await userEvent.click(screen.getByRole("button", { name: "Share conversation" }));

    expect(shareConversation).not.toHaveBeenCalled();
  });

  it("says what the level permits, and changes when it changes", async () => {
    // "Edit" on a conversation is not obvious: it carries renaming, archiving,
    // deleting the thread and appending turns.
    renderDialog();
    expect(screen.getByText(/View lets them read/)).toBeVisible();

    await userEvent.click(screen.getByRole("combobox", { name: "Access level" }));
    await userEvent.click(screen.getByRole("option", { name: "Edit" }));

    expect(screen.getByText(/Edit lets them rename/)).toBeVisible();
  });
});

describe("sharing a conversation", () => {
  it("reads who it is already shared with, when it opens", () => {
    // The dialog is the only place a share can be revoked, so it has to know
    // about the ones that exist.
    renderDialog();

    expect(fetchShares).toHaveBeenCalledWith("c1");
  });

  it("reads nothing for a conversation the server has not saved yet", () => {
    render(<ShareDialog conversationId="" open onOpenChange={vi.fn()} />);

    expect(fetchShares).not.toHaveBeenCalled();
  });

  it("reads nothing while it is closed", () => {
    render(<ShareDialog conversationId="c1" open={false} onOpenChange={vi.fn()} />);

    expect(fetchShares).not.toHaveBeenCalled();
  });

  it("shares at the access level that was chosen", async () => {
    // View and edit are different grants; defaulting to edit would hand somebody
    // more than was asked for.
    renderDialog();
    await pick(/Sam Fisher/);
    await userEvent.click(screen.getByRole("combobox", { name: "Access level" }));
    await userEvent.click(screen.getByRole("option", { name: "Edit" }));

    await userEvent.click(screen.getByRole("button", { name: "Share conversation" }));

    expect(shareConversation).toHaveBeenCalledWith("c1", {
      shared_with: "u1",
      permission: "edit",
    });
  });

  it("clears the choice on success, so the next share starts clean", async () => {
    const { toast } = await import("sonner");
    renderDialog();
    await pick(/Sam Fisher/);

    await userEvent.click(screen.getByRole("button", { name: "Share conversation" }));

    expect(screen.getByRole("button", { name: "Choose someone" })).toBeVisible();
    expect(toast.success).toHaveBeenCalledWith("Conversation shared");
  });

  it("keeps the choice when the share is refused, and says why", async () => {
    const { toast } = await import("sonner");
    shareConversation.mockRejectedValue(new Error("Not in this organization"));
    renderDialog();
    await pick(/Sam Fisher/);

    await userEvent.click(screen.getByRole("button", { name: "Share conversation" }));

    expect(toast.error).toHaveBeenCalledWith("Not in this organization");
    expect(screen.getByRole("button", { name: "Sam Fisher" })).toBeVisible();
  });
});

describe("sharing by link", () => {
  it("builds the link from the token the server minted", async () => {
    // Only the server can mint one, and only this response carries it.
    const { toast } = await import("sonner");
    shareConversation.mockResolvedValue({ id: "s-1", share_token: "tok-123" });
    renderDialog();

    await userEvent.click(screen.getByRole("button", { name: /Generate share link/ }));

    expect(shareConversation).toHaveBeenCalledWith("c1", {
      generate_link: true,
      permission: "view",
    });
    expect(screen.getByText(`${window.location.origin}/shared/tok-123`)).toBeInTheDocument();
    expect(toast.success).toHaveBeenCalledWith("Share link generated");
  });

  it("offers a copy only once there is a link to copy", async () => {
    shareConversation.mockResolvedValue({ id: "s-1", share_token: "tok-123" });
    renderDialog();
    expect(screen.queryByRole("button", { name: "Copy share link" })).toBeNull();

    await userEvent.click(screen.getByRole("button", { name: /Generate share link/ }));
    const copyButton = await screen.findByRole("button", { name: "Copy share link" });
    await userEvent.click(copyButton);

    expect(copySpy).toHaveBeenCalledWith(`${window.location.origin}/shared/tok-123`);
  });

  it("shows nothing when the server answered without a token", async () => {
    // A response with no token is not a link; showing the origin alone would be a
    // link to the app's front page.
    shareConversation.mockResolvedValue({ id: "s-1" });
    renderDialog();

    await userEvent.click(screen.getByRole("button", { name: /Generate share link/ }));

    expect(screen.queryByRole("button", { name: "Copy share link" })).toBeNull();
  });

  it("says why a link could not be minted", async () => {
    const { toast } = await import("sonner");
    shareConversation.mockRejectedValue(new Error("Link sharing is off for this organization"));
    renderDialog();

    await userEvent.click(screen.getByRole("button", { name: /Generate share link/ }));

    expect(toast.error).toHaveBeenCalledWith("Link sharing is off for this organization");
  });

  it("carries the chosen access level into the link", async () => {
    shareConversation.mockResolvedValue({ id: "s-1", share_token: "tok" });
    renderDialog();
    await userEvent.click(screen.getByRole("combobox", { name: "Access level" }));
    await userEvent.click(screen.getByRole("option", { name: "Edit" }));

    await userEvent.click(screen.getByRole("button", { name: /Generate share link/ }));

    expect(shareConversation).toHaveBeenCalledWith("c1", {
      generate_link: true,
      permission: "edit",
    });
  });
});

describe("who it is shared with", () => {
  it("lists each share as a person, with its level in words", () => {
    listedShares.mockReturnValue([
      { id: "s-1", shared_with: "u1", permission: "view" },
      { id: "s-2", share_token: "tok", permission: "edit" },
      { id: "s-3", shared_with: "u-9", permission: "view" },
    ]);
    renderDialog();

    // The member as the rest of the product draws one: the name, and the
    // address beneath it.
    expect(screen.getByText("Sam Fisher")).toBeInTheDocument();
    expect(screen.getByText("sam@example.com")).toBeInTheDocument();
    // A share the server could only resolve to a user id is shown by that id
    // rather than dropped - it still has to be revocable.
    expect(screen.getByText("u-9")).toBeInTheDocument();
    // A link share is a link, not a person.
    expect(screen.getByText("Link")).toBeInTheDocument();
    // The catalog's word, capitalised - not the API's raw `"edit"`, which was
    // English in every locale one row below a translated select.
    expect(screen.getByText("Edit")).toBeInTheDocument();
    expect(screen.queryByText("edit")).toBeNull();
  });

  it("says nothing at all when it is shared with nobody", () => {
    renderDialog();

    expect(screen.queryByText("Shared with")).toBeNull();
  });

  it("revokes the share whose button was pressed", async () => {
    const { toast } = await import("sonner");
    listedShares.mockReturnValue([
      { id: "s-1", shared_with: "u1", permission: "view" },
      { id: "s-2", shared_with: "u2", permission: "view" },
    ]);
    renderDialog();

    const [, second] = screen.getAllByRole("button", { name: "Revoke access" });
    await userEvent.click(second!);

    expect(revokeShare).toHaveBeenCalledWith("c1", "s-2");
    expect(toast.success).toHaveBeenCalledWith("Access revoked");
  });

  it("says why a revoke was refused", async () => {
    const { toast } = await import("sonner");
    revokeShare.mockRejectedValue(new Error("Not yours to revoke"));
    listedShares.mockReturnValue([{ id: "s-1", shared_with: "u1", permission: "view" }]);
    renderDialog();

    await userEvent.click(screen.getByRole("button", { name: "Revoke access" }));

    expect(toast.error).toHaveBeenCalledWith("Not yours to revoke");
  });
});
