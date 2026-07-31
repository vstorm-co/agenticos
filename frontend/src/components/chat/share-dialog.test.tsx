import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ShareDialog, matchingMembers } from "./share-dialog";
import type { OrganizationMember } from "@/types";

const shareConversation = vi.fn();
const fetchShares = vi.fn();
const listedMembers = vi.fn<() => OrganizationMember[]>(() => []);

vi.mock("next-intl", () => ({ useTranslations: () => (key: string) => key }));
vi.mock("@/hooks", () => ({
  useConversationShares: () => ({
    shares: [],
    isLoading: false,
    shareConversation,
    fetchShares,
    revokeShare: vi.fn(),
  }),
  useMembers: () => ({ members: listedMembers() }),
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

function renderDialog() {
  render(<ShareDialog conversationId="c1" open onOpenChange={vi.fn()} />);
}

beforeEach(() => {
  vi.clearAllMocks();
  listedMembers.mockReturnValue(MEMBERS);
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

    expect(screen.getByLabelText("memberEmail")).toHaveAttribute("type", "email");
    expect(screen.queryByPlaceholderText(/user id/i)).not.toBeInTheDocument();
  });

  it("suggests matching organization members while typing", async () => {
    renderDialog();

    await userEvent.type(screen.getByLabelText("memberEmail"), "sam");

    const listbox = screen.getByRole("listbox", { name: "memberSuggestions" });
    expect(listbox).toHaveTextContent("sam@example.com");
    expect(listbox).toHaveTextContent("Sam Fisher");
    expect(listbox).not.toHaveTextContent("nina@example.com");
  });

  it("fills the email when a suggestion is picked", async () => {
    renderDialog();

    await userEvent.type(screen.getByLabelText("memberEmail"), "nina");
    await userEvent.click(screen.getByRole("option", { name: /nina@example.com/ }));

    expect(screen.getByLabelText("memberEmail")).toHaveValue("nina@example.com");
    expect(screen.queryByRole("listbox")).not.toBeInTheDocument();
  });

  it("shares with the typed email", async () => {
    shareConversation.mockResolvedValue({});
    renderDialog();

    await userEvent.type(screen.getByLabelText("memberEmail"), "nina@example.com");
    await userEvent.click(screen.getByRole("button", { name: "Share conversation" }));

    // As `shared_with_email`, not `shared_with`: the latter is a UUID field,
    // and an email sent there is a 422 before the service ever runs.
    expect(shareConversation).toHaveBeenCalledWith("c1", {
      shared_with_email: "nina@example.com",
      permission: "view",
    });
  });
});
