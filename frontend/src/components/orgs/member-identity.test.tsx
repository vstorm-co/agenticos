import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { MemberIdentity, displayName } from "./member-identity";

/**
 * One person, as this application draws a person.
 *
 * Extracted because three places were drawing this row from scratch and one of them
 * had drifted into a bare first name - which is not something two colleagues called
 * Bob can be told apart by. Both lines are load-bearing: the name is what somebody
 * recognises, the address is what makes it unambiguous.
 */
describe("drawing a person", () => {
  it("shows the name and the address under it", () => {
    render(
      <MemberIdentity
        member={{ user_id: "u-1", full_name: "Ada Lovelace", email: "ada@acme.test" }}
      />,
    );

    expect(screen.getByText("Ada Lovelace")).toBeVisible();
    expect(screen.getByText("ada@acme.test")).toBeVisible();
  });

  it("says the address once for an account with no name", () => {
    // The line above is already the address; repeating it is a row that says one
    // thing twice.
    render(<MemberIdentity member={{ user_id: "u-2", full_name: null, email: "bob@acme.test" }} />);

    expect(screen.getAllByText(/bob/)).toHaveLength(1);
  });

  it("marks the caller's own row, because every list raises the question", () => {
    render(
      <MemberIdentity
        member={{ user_id: "u-1", full_name: "Ada Lovelace", email: "ada@acme.test" }}
        isSelf
      />,
    );

    expect(screen.getByText("(you)")).toBeVisible();
  });

  it("falls back to initials when there is no picture, from a name or an address", () => {
    const { container } = render(
      <MemberIdentity member={{ user_id: "u-2", full_name: null, email: "bob@acme.test" }} />,
    );

    expect(container.textContent).toContain("BA");
  });

  it("prefers the name somebody gave over their address", () => {
    expect(displayName({ user_id: "u", full_name: "Ada", email: "ada@acme.test" })).toBe("Ada");
    expect(displayName({ user_id: "u", full_name: null, email: "bob@acme.test" })).toBe("bob");
  });
});
