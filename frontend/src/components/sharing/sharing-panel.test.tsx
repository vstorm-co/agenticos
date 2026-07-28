import { beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { SharingPanel } from "./sharing-panel";
import type { OrganizationMember } from "@/types";
import type { ResourceGrant, ResourceSharing } from "@/types/sharing";

const share = { mutate: vi.fn(), isPending: false };
const revoke = { mutate: vi.fn(), isPending: false };
const setVisibility = { mutate: vi.fn(), isPending: false };

let sharing: ResourceSharing | undefined;
let members: OrganizationMember[];

// Read at render time, not at factory time, so each test can reshape the state
// the panel is given.
vi.mock("@/hooks", () => ({
  useSharing: () => ({ sharing, isLoading: sharing === undefined, share, revoke, setVisibility }),
  useMembers: () => ({ members }),
}));

function member(userId: string, email: string): OrganizationMember {
  return {
    id: `m-${userId}`,
    organization_id: "org-1",
    user_id: userId,
    role: "member",
    email,
    full_name: null,
    avatar_url: null,
    joined_at: "2026-01-01T00:00:00Z",
  };
}

const GRANT: ResourceGrant = {
  id: "g1",
  subject_user_id: "u-sam",
  subject_email: "sam@example.com",
  resource_type: "agent",
  resource_id: "a1",
  level: "read",
};

const SHARING: ResourceSharing = {
  resource_type: "agent",
  resource_id: "a1",
  owner_user_id: "u-owner",
  visibility: "private",
  grants: [GRANT],
};

function renderPanel(canManage = true, overrides?: Partial<ResourceSharing>) {
  // Only when a test asks: the others set `sharing` themselves, including to
  // `undefined` for the loading state, and overwriting it here would decide
  // for them.
  if (overrides) sharing = { ...SHARING, ...overrides };
  return render(<SharingPanel resourceType="agent" resourceId="a1" canManage={canManage} />);
}

/** Open a Radix select and choose one of its options. */
async function choose(trigger: HTMLElement, option: string) {
  await userEvent.click(trigger);
  await userEvent.click(await screen.findByRole("option", { name: option }));
}

beforeAll(() => {
  // Radix drives its listbox with pointer-capture and scrolling APIs jsdom does
  // not implement; without them the menu never opens and every select test
  // fails for a reason that has nothing to do with this component.
  Element.prototype.hasPointerCapture = () => false;
  Element.prototype.setPointerCapture = () => {};
  Element.prototype.releasePointerCapture = () => {};
  Element.prototype.scrollIntoView = () => {};
});

beforeEach(() => {
  vi.clearAllMocks();
  sharing = structuredClone(SHARING);
  members = [
    member("u-owner", "owner@example.com"),
    member("u-sam", "sam@example.com"),
    member("u-nina", "nina@example.com"),
  ];
});

describe("SharingPanel", () => {
  it("waits for the sharing state rather than rendering an empty one", () => {
    sharing = undefined;
    renderPanel();
    expect(screen.queryByText("Visibility")).not.toBeInTheDocument();
  });

  it("says who each visibility reaches, in the place the choice is made", () => {
    renderPanel();
    expect(screen.getByText(/Nobody else finds this agent in their list/)).toBeInTheDocument();
    expect(
      screen.getByText("Everyone in the organization who can view agents at all."),
    ).toBeInTheDocument();
  });

  it("does not offer a visibility this product has no concept of", () => {
    // "Team" is a third value the column accepts and `resolve_access`
    // understands, and it means "anyone whose role reaches team resources" -
    // a role scope with no team behind it, because there are no teams here.
    // Offering it asked people to choose between a concept the product has and
    // one it does not.
    renderPanel();
    expect(screen.queryByRole("radio", { name: /Team/ })).toBeNull();
  });

  it("still shows Team for a row already set to it", () => {
    // Otherwise a legacy row renders with nothing selected, and the one action
    // that would fix it - picking something else - looks like it is already done.
    renderPanel(true, { visibility: "team" });
    expect(screen.getByRole("radio", { name: /Team/ })).toBeChecked();
  });

  it("shows the visibility the resource actually has", () => {
    renderPanel();
    expect(screen.getByRole("radio", { name: "Private" })).toBeChecked();
    expect(screen.getByRole("radio", { name: "Organization" })).not.toBeChecked();
  });

  it("asks the server to widen visibility instead of assuming it worked", async () => {
    renderPanel();
    await userEvent.click(screen.getByRole("radio", { name: "Organization" }));
    expect(setVisibility.mutate).toHaveBeenCalledWith("org");
  });

  it("names each person the resource is shared with, and at what level", () => {
    renderPanel();
    expect(screen.getByText("sam@example.com")).toBeInTheDocument();
    expect(screen.getByLabelText("Access for sam@example.com")).toHaveTextContent("Can view");
    expect(screen.getByText("Owned by owner@example.com")).toBeInTheDocument();
  });

  it("says plainly that nobody has been shared with", () => {
    sharing = { ...SHARING, grants: [] };
    renderPanel();
    expect(screen.getByText("Not shared with anyone yet.")).toBeInTheDocument();
  });

  it("explains an empty picker rather than offering an empty menu", () => {
    // Everyone in this organization already reaches the resource, which is a
    // different thing from the member list having failed to load.
    members = [member("u-owner", "owner@example.com"), member("u-sam", "sam@example.com")];
    renderPanel();
    expect(screen.getByLabelText("Add someone")).toHaveTextContent("Everyone already has access");
    expect(screen.getByLabelText("Add someone")).toBeDisabled();
  });

  it("falls back to the subject id when the server could not name them", () => {
    // A grant outlives the membership that explains it. Showing nothing would
    // leave a row nobody can identify well enough to revoke.
    sharing = { ...SHARING, grants: [{ ...GRANT, subject_email: null }] };
    renderPanel();
    expect(screen.getByText("u-sam")).toBeInTheDocument();
  });

  it("changes a level with the same call that created the share", async () => {
    renderPanel();
    await choose(screen.getByLabelText("Access for sam@example.com"), "Can edit");
    expect(share.mutate).toHaveBeenCalledWith({ subject_user_id: "u-sam", level: "edit" });
  });

  it("revokes the person whose row was clicked", async () => {
    renderPanel();
    await userEvent.click(screen.getByRole("button", { name: "Remove sam@example.com" }));
    expect(revoke.mutate).toHaveBeenCalledWith("u-sam");
  });

  it("offers only members who do not already reach it", async () => {
    renderPanel();
    await userEvent.click(screen.getByLabelText("Add someone"));

    expect(await screen.findByRole("option", { name: "nina@example.com" })).toBeInTheDocument();
    // Sam already has a grant and the owner cannot be granted access they
    // already own - offering either produces a call the server refuses.
    expect(screen.queryByRole("option", { name: "sam@example.com" })).not.toBeInTheDocument();
    expect(screen.queryByRole("option", { name: "owner@example.com" })).not.toBeInTheDocument();
  });

  it("shares with the member and level that were chosen", async () => {
    renderPanel();
    await choose(screen.getByLabelText("Add someone"), "nina@example.com");
    await choose(screen.getByLabelText("Access"), "Can use");
    await userEvent.click(screen.getByRole("button", { name: "Share" }));

    expect(share.mutate).toHaveBeenCalledWith({ subject_user_id: "u-nina", level: "use" });
  });

  it("cannot share with nobody", () => {
    renderPanel();
    expect(screen.getByRole("button", { name: "Share" })).toBeDisabled();
  });

  it("leaves someone who cannot edit the resource nothing to change", () => {
    renderPanel(false);
    expect(screen.queryByRole("button", { name: "Share" })).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Remove sam@example.com" }),
    ).not.toBeInTheDocument();
    expect(screen.getByRole("radio", { name: "Organization" })).toBeDisabled();
    expect(screen.getByLabelText("Access for sam@example.com")).toBeDisabled();
  });

  it("wires every label to the control it names", () => {
    // A label with no htmlFor reads as decoration to a screen reader and leaves
    // the control it describes unnamed. This regressed once already.
    const { container } = renderPanel();
    const labels = Array.from(container.querySelectorAll<HTMLLabelElement>("label"));

    expect(labels.length).toBeGreaterThan(0);
    for (const label of labels) {
      expect(label.htmlFor, `"${label.textContent}" names no control`).not.toBe("");
      expect(document.getElementById(label.htmlFor)).not.toBeNull();
    }
  });
});
