import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { AgentAvatar, agentInitials } from "./agent-avatar";

/**
 * The picture that stands in for an agent everywhere one is named.
 *
 * Initials rather than a generic robot whenever there is a name to take them
 * from: a wall of identical robot glyphs tells a reader nothing, and telling two
 * agents apart at a glance is the whole point of having a picture.
 */
describe("agentInitials", () => {
  it("takes the first letter of the first two words", () => {
    expect(agentInitials("Customer Support Bot")).toBe("CS");
  });

  it("takes one letter from a one-word name", () => {
    expect(agentInitials("Support")).toBe("S");
  });

  it("ignores the whitespace somebody left in a name", () => {
    expect(agentInitials("  Customer   Support  ")).toBe("CS");
  });

  it("has nothing to show for a name that is only whitespace", () => {
    // Which is what sends the avatar to the robot rather than to a blank circle.
    expect(agentInitials("   ")).toBe("");
  });
});

describe("AgentAvatar", () => {
  it("shows the initials", () => {
    render(<AgentAvatar agentId="a1" name="Customer Support" />);

    expect(screen.getByText("CS")).toBeInTheDocument();
  });

  it("falls back to a robot when the name yields no initials", () => {
    const { container } = render(<AgentAvatar agentId="a1" name="" />);

    expect(container.querySelector("svg")).not.toBeNull();
  });

  it("still shows the initials while a stored picture is being fetched", () => {
    // The fallback is what a reader sees until the request answers, and the
    // request goes through the API so it carries the same access check as
    // reading the agent.
    render(<AgentAvatar agentId="a1" name="Customer Support" hasAvatar />);

    expect(screen.getByText("CS")).toBeInTheDocument();
  });

  it("renders at the size it was asked for", () => {
    const { container } = render(<AgentAvatar agentId="a1" name="Support" size="xl" />);

    expect(container.firstElementChild).toHaveClass("h-20");
  });

  it("takes a version, which is what defeats the cache after an upload", () => {
    // Without it a replaced picture keeps rendering as the old one until a hard
    // reload, because the URL did not change.
    render(<AgentAvatar agentId="a1" name="Support" hasAvatar version={2} />);

    expect(screen.getByText("S")).toBeInTheDocument();
  });
});
