import { useState } from "react";
import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { AudiencePicker, EVERYONE, audiencePayload, type Audience } from "./audience-picker";

const { groups } = vi.hoisted(() => ({ groups: vi.fn() }));
vi.mock("@/hooks", () => ({ useGroups: () => ({ groups: groups() }) }));

const FINANCE = { id: "g-fin", name: "Finance", icon: "banknote" as const };
const SALES = { id: "g-sales", name: "Sales", icon: null };

function Harness({ onChange }: { onChange: (audience: Audience) => void }) {
  const [value, setValue] = useState<Audience>(EVERYONE);
  return (
    <AudiencePicker
      value={value}
      onChange={(next) => {
        setValue(next);
        onChange(next);
      }}
    />
  );
}

describe("AudiencePicker", () => {
  it("starts with the whole organization", () => {
    groups.mockReturnValue([FINANCE]);
    render(<Harness onChange={vi.fn()} />);

    expect(screen.getByRole("radio", { name: /Everyone/ })).toHaveAttribute("aria-checked", "true");
  });

  it("narrows to chosen groups, one chip at a time", async () => {
    groups.mockReturnValue([FINANCE, SALES]);
    const onChange = vi.fn();
    render(<Harness onChange={onChange} />);

    await userEvent.click(screen.getByRole("radio", { name: /Chosen groups/ }));
    await userEvent.click(screen.getByRole("button", { name: "Finance" }));
    await userEvent.click(screen.getByRole("button", { name: "Sales" }));
    await userEvent.click(screen.getByRole("button", { name: "Sales" }));

    expect(onChange).toHaveBeenLastCalledWith({ mode: "groups", group_ids: ["g-fin"] });
    expect(screen.getByRole("button", { name: "Finance" })).toHaveAttribute("aria-pressed", "true");
  });

  it("offers no groups to choose before there are any, and says where to add them", () => {
    groups.mockReturnValue([]);
    render(<Harness onChange={vi.fn()} />);

    expect(screen.getByRole("radio", { name: /Chosen groups/ })).toBeDisabled();
    expect(screen.getByText(/No groups yet/)).toBeInTheDocument();
  });

  it("keeps it to the creator", async () => {
    groups.mockReturnValue([]);
    const onChange = vi.fn();
    render(<Harness onChange={onChange} />);

    await userEvent.click(screen.getByRole("radio", { name: /Only me/ }));

    expect(onChange).toHaveBeenLastCalledWith({ mode: "private", group_ids: [] });
  });
});

describe("audiencePayload", () => {
  it.each([
    [EVERYONE, { visibility: "org", group_ids: [] }],
    [
      { mode: "private", group_ids: [] },
      { visibility: "private", group_ids: [] },
    ],
    [
      { mode: "groups", group_ids: ["g"] },
      { visibility: "private", group_ids: ["g"] },
    ],
    // A choice half made is not a reason to hide the new thing from everyone.
    [
      { mode: "groups", group_ids: [] },
      { visibility: "org", group_ids: [] },
    ],
  ] as const)("sends %o as %o", (audience, payload) => {
    expect(audiencePayload({ ...audience, group_ids: [...audience.group_ids] })).toEqual(payload);
  });
});
