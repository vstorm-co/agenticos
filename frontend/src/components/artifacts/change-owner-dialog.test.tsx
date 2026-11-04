import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

import { ChangeOwnerDialog } from "./change-owner-dialog";
import { useOrgStore } from "@/stores";
import { useAuthStore } from "@/stores/auth-store";
import type { OrganizationMember, User } from "@/types";
import type { ArtifactDetail } from "@/types/artifact";

/**
 * Handing a page to another member: the picker offers everyone but the current
 * owner, and nothing is sent until a second step has said what it does.
 */

let members: OrganizationMember[];
const useMembers = vi.fn((_orgId: string) => ({ members }));
vi.mock("@/hooks", () => ({ useMembers: (orgId: string) => useMembers(orgId) }));

function member(userId: string, email: string, fullName: string | null = null) {
  return {
    id: `m-${userId}`,
    organization_id: "org-1",
    user_id: userId,
    role: "member",
    email,
    full_name: fullName,
    avatar_url: null,
    avatar_color: null,
    joined_at: "2026-01-01T00:00:00Z",
    source: "manual",
  } as OrganizationMember;
}

const ARTIFACT = { id: "a1", title: "Weekly report", owner_user_id: "u-olga" } as ArtifactDetail;

function renderDialog(overrides: { pending?: boolean; ownerless?: boolean } = {}) {
  const onOpenChange = vi.fn();
  const onChangeOwner = vi.fn();
  render(
    <ChangeOwnerDialog
      artifact={overrides.ownerless ? { ...ARTIFACT, owner_user_id: null } : ARTIFACT}
      open
      onOpenChange={onOpenChange}
      onChangeOwner={onChangeOwner}
      pending={overrides.pending ?? false}
    />,
  );
  return { onOpenChange, onChangeOwner };
}

async function pick(email: string) {
  await userEvent.click(screen.getByRole("combobox"));
  await userEvent.click(await screen.findByRole("option", { name: email }));
}

beforeAll(() => {
  Element.prototype.hasPointerCapture = () => false;
  Element.prototype.setPointerCapture = () => {};
  Element.prototype.releasePointerCapture = () => {};
  Element.prototype.scrollIntoView = () => {};
});

beforeEach(() => {
  members = [member("u-olga", "olga@example.com"), member("u-bea", "bea@example.com")];
});

describe("the change owner dialog", () => {
  it("lists the members of the organization the page was opened in", () => {
    renderDialog();
    expect(useMembers).toHaveBeenLastCalledWith("");

    useOrgStore.setState({ activeOrgId: "org-1" });
    renderDialog();
    expect(useMembers).toHaveBeenLastCalledWith("org-1");
    useOrgStore.setState({ activeOrgId: null });
  });

  it("offers every member but the current owner, and continues only with one chosen", async () => {
    renderDialog();
    expect(screen.getByRole("button", { name: "Continue" })).toBeDisabled();

    await userEvent.click(screen.getByRole("combobox"));
    expect(await screen.findByRole("option", { name: "bea@example.com" })).toBeInTheDocument();
    expect(screen.queryByRole("option", { name: "olga@example.com" })).not.toBeInTheDocument();
  });

  it("says what the change does before sending it, then sends the chosen member", async () => {
    const { onChangeOwner, onOpenChange } = renderDialog();
    await pick("bea@example.com");
    await userEvent.click(screen.getByRole("button", { name: "Continue" }));

    expect(screen.getByText(/is hidden from others until bea@example.com confirms it/)).toBe(
      screen.getByText(/is hidden from others/),
    );
    expect(onChangeOwner).not.toHaveBeenCalled();

    await userEvent.click(screen.getByRole("button", { name: "Change owner" }));
    expect(onChangeOwner).toHaveBeenCalledWith("u-bea", expect.any(Function));

    // Once the server took it, the callback closes the dialog.
    onChangeOwner.mock.calls[0]?.[1]();
    expect(onOpenChange).toHaveBeenCalledWith(false);
  });

  it("names the previous owner as notified when an admin makes the switch", async () => {
    useAuthStore.setState({ user: { id: "u-admin" } as User });
    renderDialog();
    await pick("bea@example.com");
    await userEvent.click(screen.getByRole("button", { name: "Continue" }));

    expect(
      screen.getByText(/bea@example.com and the previous owner are notified/),
    ).toBeInTheDocument();
    useAuthStore.setState({ user: null });
  });

  it("names only the new owner when the owner hands the page over, or nobody owned it", async () => {
    useAuthStore.setState({ user: { id: "u-olga" } as User });
    renderDialog();
    await pick("bea@example.com");
    await userEvent.click(screen.getByRole("button", { name: "Continue" }));
    expect(screen.getByText(/\. bea@example.com is notified\./)).toBeInTheDocument();
    expect(screen.queryByText(/previous owner/i)).not.toBeInTheDocument();
    useAuthStore.setState({ user: null });
  });

  it("names only the new owner when the page has no owner", async () => {
    useAuthStore.setState({ user: { id: "u-admin" } as User });
    renderDialog({ ownerless: true });
    await pick("bea@example.com");
    await userEvent.click(screen.getByRole("button", { name: "Continue" }));

    expect(screen.getByText(/\. bea@example.com is notified\./)).toBeInTheDocument();
    useAuthStore.setState({ user: null });
  });

  it("goes back from the second step to the picker with the choice kept", async () => {
    renderDialog();
    await pick("bea@example.com");
    await userEvent.click(screen.getByRole("button", { name: "Continue" }));
    await userEvent.click(screen.getByRole("button", { name: "Back" }));

    expect(screen.getByRole("combobox")).toHaveTextContent("bea@example.com");
  });

  it("closes from Cancel, forgetting the choice", async () => {
    const { onOpenChange } = renderDialog();
    await pick("bea@example.com");
    await userEvent.click(screen.getByRole("button", { name: "Cancel" }));

    expect(onOpenChange).toHaveBeenCalledWith(false);
    expect(screen.getByRole("combobox")).toHaveTextContent("Choose a member");
  });

  it("holds the confirm while the change is in flight", async () => {
    renderDialog({ pending: true });
    await pick("bea@example.com");
    await userEvent.click(screen.getByRole("button", { name: "Continue" }));

    expect(screen.getByRole("button", { name: "…" })).toBeDisabled();
  });
});
