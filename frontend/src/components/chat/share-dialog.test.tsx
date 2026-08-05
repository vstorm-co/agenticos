import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ShareDialog, matchingMembers } from "./share-dialog";
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

describe("matchingMembers", () => {
  it("matches by email and by name, case-insensitively", () => {
    expect(matchingMembers(MEMBERS, "SAM")).toHaveLength(1);
    expect(matchingMembers(MEMBERS, "vale")).toHaveLength(1);
  });

  it("suggests nothing for an empty query", () => {
    expect(matchingMembers(MEMBERS, "  ")).toHaveLength(0);
  });

  it("does not suggest what the field already says", () => {
    // An exact match is a decision already made, not a suggestion.
    expect(matchingMembers(MEMBERS, "sam@example.com")).toHaveLength(0);
  });

  it("caps the list", () => {
    const many = Array.from({ length: 10 }, (_, i) => member(`u${i}`, `user${i}@example.com`));
    expect(matchingMembers(many, "user")).toHaveLength(6);
  });
});

describe("the share dialog", () => {
  it("offers an email field only - there is no user id input", () => {
    renderDialog();

    expect(screen.getByLabelText("Email address")).toHaveAttribute("type", "email");
    expect(screen.queryByPlaceholderText(/user id/i)).not.toBeInTheDocument();
  });

  it("suggests matching organization members while typing", async () => {
    renderDialog();

    await userEvent.type(screen.getByLabelText("Email address"), "sam");

    const listbox = screen.getByRole("listbox", { name: "Matching members" });
    expect(listbox).toHaveTextContent("sam@example.com");
    expect(listbox).toHaveTextContent("Sam Fisher");
    expect(listbox).not.toHaveTextContent("nina@example.com");
  });

  it("fills the email when a suggestion is picked", async () => {
    renderDialog();

    await userEvent.type(screen.getByLabelText("Email address"), "nina");
    await userEvent.click(screen.getByRole("option", { name: /nina@example.com/ }));

    expect(screen.getByLabelText("Email address")).toHaveValue("nina@example.com");
    expect(screen.queryByRole("listbox")).not.toBeInTheDocument();
  });

  it("shares with the typed email", async () => {
    shareConversation.mockResolvedValue({});
    renderDialog();

    await userEvent.type(screen.getByLabelText("Email address"), "nina@example.com");
    await userEvent.click(screen.getByRole("button", { name: "Share conversation" }));

    // As `shared_with_email`, not `shared_with`: the latter is a UUID field,
    // and an email sent there is a 422 before the service ever runs.
    expect(shareConversation).toHaveBeenCalledWith("c1", {
      shared_with_email: "nina@example.com",
      permission: "view",
    });
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
    await userEvent.type(screen.getByLabelText("Email address"), "sam@example.com");
    await userEvent.click(screen.getByRole("combobox"));
    await userEvent.click(screen.getByRole("option", { name: "Edit" }));

    await userEvent.click(screen.getByRole("button", { name: "Share conversation" }));

    expect(shareConversation).toHaveBeenCalledWith("c1", {
      shared_with_email: "sam@example.com",
      permission: "edit",
    });
  });

  it("shares with view access unless told otherwise", async () => {
    renderDialog();
    await userEvent.type(screen.getByLabelText("Email address"), "sam@example.com");

    await userEvent.click(screen.getByRole("button", { name: "Share conversation" }));

    expect(shareConversation).toHaveBeenCalledWith("c1", {
      shared_with_email: "sam@example.com",
      permission: "view",
    });
  });

  it("empties the field on success, so the next share starts clean", async () => {
    const { toast } = await import("sonner");
    renderDialog();
    await userEvent.type(screen.getByLabelText("Email address"), "sam@example.com");

    await userEvent.click(screen.getByRole("button", { name: "Share conversation" }));

    expect(screen.getByLabelText("Email address")).toHaveValue("");
    expect(toast.success).toHaveBeenCalledWith("Conversation shared");
  });

  it("keeps what was typed when the share is refused, and says why", async () => {
    // "That person is not in this organization" is worth reading beside the
    // address that produced it.
    const { toast } = await import("sonner");
    shareConversation.mockRejectedValue(new Error("Not in this organization"));
    renderDialog();
    await userEvent.type(screen.getByLabelText("Email address"), "outsider@example.com");

    await userEvent.click(screen.getByRole("button", { name: "Share conversation" }));

    expect(toast.error).toHaveBeenCalledWith("Not in this organization");
    expect(screen.getByLabelText("Email address")).toHaveValue("outsider@example.com");
  });

  it("shares with nobody when the field is empty", async () => {
    renderDialog();

    await userEvent.click(screen.getByRole("button", { name: "Share conversation" }));

    expect(shareConversation).not.toHaveBeenCalled();
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
    await userEvent.click(screen.getByRole("combobox"));
    await userEvent.click(screen.getByRole("option", { name: "Edit" }));

    await userEvent.click(screen.getByRole("button", { name: /Generate share link/ }));

    expect(shareConversation).toHaveBeenCalledWith("c1", {
      generate_link: true,
      permission: "edit",
    });
  });
});

describe("who it is shared with", () => {
  it("lists each share by name, level, and whether it is a link", () => {
    listedShares.mockReturnValue([
      { id: "s-1", shared_with_email: "sam@example.com", permission: "view" },
      { id: "s-2", share_token: "tok", permission: "edit" },
      { id: "s-3", shared_with: "u-9", permission: "view" },
    ]);
    renderDialog();

    expect(screen.getByText("sam@example.com")).toBeInTheDocument();
    // A link share has no address, so it is named "Link" *and* badged as one.
    expect(screen.getAllByText("Link")).toHaveLength(2);
    // A share the server could only resolve to a user id is shown by that id
    // rather than dropped.
    expect(screen.getByText("u-9")).toBeInTheDocument();
    expect(screen.getByText("edit")).toBeInTheDocument();
  });

  it("says nothing at all when it is shared with nobody", () => {
    renderDialog();

    expect(screen.queryByText("Shared with")).toBeNull();
  });

  it("revokes the share whose button was pressed", async () => {
    const { toast } = await import("sonner");
    listedShares.mockReturnValue([
      { id: "s-1", shared_with_email: "sam@example.com", permission: "view" },
      { id: "s-2", shared_with_email: "nina@example.com", permission: "view" },
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
    listedShares.mockReturnValue([
      { id: "s-1", shared_with_email: "sam@example.com", permission: "view" },
    ]);
    renderDialog();

    await userEvent.click(screen.getByRole("button", { name: "Revoke access" }));

    expect(toast.error).toHaveBeenCalledWith("Not yours to revoke");
  });
});
