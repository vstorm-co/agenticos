import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { MemberPicker } from "./member-picker";
import type { IdentifiedMember } from "./member-identity";

function member(index: number): IdentifiedMember {
  return {
    user_id: `u-${index}`,
    full_name: index === 0 ? "Ada Lovelace" : `Person ${index}`,
    email: index === 0 ? "ada@acme.test" : `person${index}@acme.test`,
  };
}

function picker(props: Partial<React.ComponentProps<typeof MemberPicker>> = {}) {
  const onToggle = vi.fn();
  render(
    <MemberPicker
      members={[member(0), member(1), member(2)]}
      selected={[]}
      onToggle={onToggle}
      label={(count) => (count === 0 ? "Choose people" : `${count} chosen`)}
      scope="Approval requests"
      {...props}
    />,
  );
  return { onToggle };
}

async function open() {
  await userEvent.click(screen.getByRole("button", { name: /Choose people|chosen/ }));
}

/**
 * Choosing people out of an organization.
 *
 * An organization is not a handful, which is the whole reason this exists: forty
 * members as pills filled a settings card, and forty in an unbounded panel is a page
 * that scrolls past its own controls. So it is searched and bounded - and searched
 * with `cmdk` rather than inside a menu, because a menu reads keystrokes for its own
 * typeahead and typing "bo" would move focus instead of filtering.
 */
describe("the people picker", () => {
  it("says how many are chosen, on the thing you press", () => {
    picker({ selected: ["u-1", "u-2"] });

    expect(screen.getByRole("button", { name: "2 chosen" })).toBeVisible();
  });

  it("names each person by name and address", async () => {
    // A bare first name is not something two colleagues called Bob are told apart
    // by; the address is the part that is unique.
    picker();
    await open();

    expect(
      screen.getByRole("option", { name: "Approval requests: Ada Lovelace (ada@acme.test)" }),
    ).toBeVisible();
  });

  it("filters by name", async () => {
    picker();
    await open();

    await userEvent.type(screen.getByPlaceholderText("Search people…"), "Ada");

    expect(screen.getAllByRole("option")).toHaveLength(1);
  });

  it("filters by address, because that is what somebody remembers", async () => {
    picker();
    await open();

    await userEvent.type(screen.getByPlaceholderText("Search people…"), "person2@");

    expect(screen.getAllByRole("option")).toHaveLength(1);
  });

  it("says nobody matched rather than showing an empty panel", async () => {
    picker();
    await open();

    await userEvent.type(screen.getByPlaceholderText("Search people…"), "zzz");

    expect(screen.getByText("Nobody here matches that.")).toBeVisible();
  });

  it("marks who is already on the list", async () => {
    picker({ selected: ["u-0"] });
    await open();

    expect(
      screen.getByRole("option", { name: "Approval requests: Ada Lovelace (ada@acme.test)" }),
    ).toHaveAttribute("aria-selected", "true");
  });

  it("toggles the person that was pressed", async () => {
    const { onToggle } = picker();
    await open();

    await userEvent.click(
      screen.getByRole("option", { name: "Approval requests: Person 1 (person1@acme.test)" }),
    );

    expect(onToggle).toHaveBeenCalledWith("u-1");
  });

  it("scrolls rather than growing past ten people", async () => {
    // The ceiling is the point: an organization of forty would otherwise push the
    // panel past the bottom of the page.
    picker({ members: Array.from({ length: 40 }, (_, index) => member(index)) });
    await open();

    // `cmdk` wraps the items in a sizer div, so the scrolling element is the
    // listbox itself rather than the option's parent.
    const list = screen.getByRole("listbox");
    expect(list.className).toContain("overflow-y-auto");
    expect(list.className).toContain("max-h-[min(26rem,60vh)]");
  });

  it("cannot be opened at all when the panel is read-only", () => {
    picker({ disabled: true });

    expect(screen.getByRole("button", { name: "Choose people" })).toBeDisabled();
  });
});
