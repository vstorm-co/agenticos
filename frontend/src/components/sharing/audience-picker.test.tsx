import { useState } from "react";
import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { AudiencePicker, EVERYONE, audiencePayload, type Audience } from "./audience-picker";

const { groups, members } = vi.hoisted(() => ({ groups: vi.fn(), members: vi.fn() }));
vi.mock("@/hooks", () => ({
  useGroups: () => ({ groups: groups() }),
  useMembers: () => ({ members: members() }),
}));

const FINANCE = { id: "g-fin", name: "Finance", icon: "banknote" as const };
const SALES = { id: "g-sales", name: "Sales", icon: null };
const ANNA = { user_id: "u-anna", email: "anna@acme.example", full_name: "Anna Nowak" };
const BOB = { user_id: "u-bob", email: "bob@acme.example", full_name: null };

function Harness({
  onChange,
  withOnlyMe,
}: {
  onChange: (audience: Audience) => void;
  withOnlyMe?: boolean;
}) {
  const [value, setValue] = useState<Audience>(EVERYONE);
  return (
    <AudiencePicker
      value={value}
      withOnlyMe={withOnlyMe}
      onChange={(next) => {
        setValue(next);
        onChange(next);
      }}
    />
  );
}

function given(groupRows: unknown[], memberRows: unknown[] = []) {
  groups.mockReturnValue(groupRows);
  members.mockReturnValue(memberRows);
}

describe("AudiencePicker", () => {
  it("starts with the whole organization", () => {
    given([FINANCE]);
    render(<Harness onChange={vi.fn()} />);

    expect(screen.getByRole("radio", { name: /Everyone/ })).toHaveAttribute("aria-checked", "true");
  });

  it("offers the groups at once and keeps each one picked as a chip", async () => {
    given([FINANCE, SALES]);
    const onChange = vi.fn();
    render(<Harness onChange={onChange} />);

    await userEvent.click(screen.getByRole("radio", { name: /Chosen groups or people/ }));
    await userEvent.click(screen.getByRole("button", { name: "Finance" }));
    await userEvent.click(screen.getByRole("button", { name: "Sales" }));
    await userEvent.click(screen.getByRole("button", { name: "Remove Sales" }));

    expect(onChange).toHaveBeenLastCalledWith({
      mode: "chosen",
      group_ids: ["g-fin"],
      user_ids: [],
    });
    expect(screen.getByRole("list", { name: "Chosen so far" })).toHaveTextContent("Finance");
  });

  it("finds a person by name or address, and drops them again", async () => {
    given([FINANCE], [ANNA, BOB]);
    const onChange = vi.fn();
    render(<Harness onChange={onChange} />);

    await userEvent.click(screen.getByRole("radio", { name: /Chosen groups or people/ }));
    expect(screen.queryByRole("button", { name: "Anna Nowak" })).not.toBeInTheDocument();

    await userEvent.type(screen.getByRole("textbox", { name: "Search groups and people" }), "anna");
    await userEvent.click(screen.getByRole("button", { name: "Anna Nowak" }));
    await userEvent.type(screen.getByRole("textbox", { name: "Search groups and people" }), "bob@");
    await userEvent.click(screen.getByRole("button", { name: "bob@acme.example" }));

    expect(onChange).toHaveBeenLastCalledWith({
      mode: "chosen",
      group_ids: [],
      user_ids: ["u-anna", "u-bob"],
    });

    await userEvent.click(screen.getByRole("button", { name: "Remove Anna Nowak" }));
    expect(onChange).toHaveBeenLastCalledWith({
      mode: "chosen",
      group_ids: [],
      user_ids: ["u-bob"],
    });
  });

  it("says when nothing matches, and how to find a person before anything is typed", async () => {
    given([], [ANNA]);
    render(<Harness onChange={vi.fn()} />);

    await userEvent.click(screen.getByRole("radio", { name: /Chosen groups or people/ }));
    expect(screen.getByText(/No groups yet/)).toBeInTheDocument();

    await userEvent.type(screen.getByRole("textbox", { name: "Search groups and people" }), "zed");
    expect(screen.getByText(/Nothing matches/)).toBeInTheDocument();
  });

  it("explains how to find a person when every group is already picked", async () => {
    given([FINANCE]);
    render(<Harness onChange={vi.fn()} />);

    await userEvent.click(screen.getByRole("radio", { name: /Chosen groups or people/ }));
    await userEvent.click(screen.getByRole("button", { name: "Finance" }));

    expect(screen.getByText(/Type a name or an email address/)).toBeInTheDocument();
  });

  it("keeps it to the creator", async () => {
    given([]);
    const onChange = vi.fn();
    render(<Harness onChange={onChange} />);

    await userEvent.click(screen.getByRole("radio", { name: /Only me/ }));

    expect(onChange).toHaveBeenLastCalledWith({ mode: "private", group_ids: [], user_ids: [] });
  });

  it("leaves out only-me where the form has its own control for it", () => {
    given([]);
    render(<Harness onChange={vi.fn()} withOnlyMe={false} />);

    expect(screen.queryByRole("radio", { name: /Only me/ })).not.toBeInTheDocument();
    expect(screen.getAllByRole("radio")).toHaveLength(2);
  });
});

describe("audiencePayload", () => {
  it.each([
    [EVERYONE, { visibility: "org", group_ids: [], user_ids: [] }],
    [
      { mode: "private", group_ids: [], user_ids: [] },
      { visibility: "private", group_ids: [], user_ids: [] },
    ],
    [
      { mode: "chosen", group_ids: ["g"], user_ids: [] },
      { visibility: "private", group_ids: ["g"], user_ids: [] },
    ],
    [
      { mode: "chosen", group_ids: [], user_ids: ["u"] },
      { visibility: "private", group_ids: [], user_ids: ["u"] },
    ],
    // A choice half made is not a reason to hide the new thing from everyone.
    [
      { mode: "chosen", group_ids: [], user_ids: [] },
      { visibility: "org", group_ids: [], user_ids: [] },
    ],
  ] as const)("sends %o as %o", (audience, payload) => {
    expect(
      audiencePayload({
        mode: audience.mode,
        group_ids: [...audience.group_ids],
        user_ids: [...audience.user_ids],
      }),
    ).toEqual(payload);
  });
});
