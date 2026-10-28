import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ConversationAgents } from "./conversation-agents";
import type { ConversationAgent } from "@/types";

function agent(name: string): ConversationAgent {
  return { id: `${name}-id`, slug: name.toLowerCase(), name, has_avatar: false };
}

describe("who answered in a conversation", () => {
  it("renders nothing when no agent took part", () => {
    // That is the general assistant, and a badge saying so on every row would be
    // noise on the common case.
    const { container } = render(<ConversationAgents agents={[]} />);

    expect(container).toBeEmptyDOMElement();
  });

  it("renders nothing when the field is absent altogether", () => {
    // A listing that predates the column, or a response that omitted it.
    const { container } = render(<ConversationAgents agents={undefined} />);

    expect(container).toBeEmptyDOMElement();
  });

  it("names the one agent when only one answered", () => {
    render(<ConversationAgents agents={[agent("Support")]} />);

    expect(screen.getByText("Support")).toBeInTheDocument();
  });

  it("counts them instead of naming them once there are several", () => {
    // The picker can be changed mid-thread, so two agents in one conversation is
    // ordinary - and naming only the last would be a quiet lie about the first
    // half of the transcript.
    render(<ConversationAgents agents={[agent("Support"), agent("Sales")]} />);

    expect(screen.getByText("2 agents")).toBeInTheDocument();
    expect(screen.queryByText("Support")).toBeNull();
  });

  it("puts the running order in the title, so nothing is actually lost", () => {
    render(<ConversationAgents agents={[agent("First"), agent("Second"), agent("Third")]} />);

    expect(screen.getByTitle("First → Second → Third")).toBeInTheDocument();
  });

  it("stops stacking pictures after three", () => {
    // Beyond that the stack is a smudge.
    const { container } = render(
      <ConversationAgents agents={[agent("A"), agent("B"), agent("C"), agent("D"), agent("E")]} />,
    );

    // Counted by the generated faces the avatars fall back to: these agents have
    // no uploaded picture, which is the ordinary case. The running order is not
    // lost - it is in the stack's own title, asserted above.
    expect(container.querySelectorAll("g.mo-root")).toHaveLength(3);
    expect(screen.getByText("5 agents")).toBeInTheDocument();
  });

  it("counts the overflow when the name is suppressed", () => {
    // Where the row is tight the pictures carry it, and `+2` is what replaces the
    // count that would otherwise have been spelled out.
    render(
      <ConversationAgents
        agents={[agent("A"), agent("B"), agent("C"), agent("D"), agent("E")]}
        showName={false}
      />,
    );

    expect(screen.getByText("+2")).toBeInTheDocument();
    expect(screen.queryByText("5 agents")).toBeNull();
  });

  it("says nothing about overflow when everybody fits", () => {
    render(<ConversationAgents agents={[agent("A"), agent("B")]} showName={false} />);

    expect(screen.queryByText(/^\+/)).toBeNull();
  });

  it("passes a caller's class through, because it is laid out by its parent", () => {
    const { container } = render(
      <ConversationAgents agents={[agent("Support")]} className="ml-auto" />,
    );

    expect(container.firstElementChild).toHaveClass("ml-auto");
  });

  it("tucks three faces closer than two, and spreads them when pointed at", () => {
    const { container, rerender } = render(
      <ConversationAgents agents={[agent("A"), agent("B")]} showName={false} />,
    );
    const second = () => container.querySelectorAll<HTMLElement>("[data-agent-avatar]")[1]!;
    expect(second().className).toContain("-ml-1.5");

    rerender(<ConversationAgents agents={[agent("A"), agent("B"), agent("C")]} showName={false} />);
    expect(second().className).toContain("-ml-3.5");
    expect(second().className).toContain("group-hover/stack:ml-0.5");
    // The first face never moves: the stack opens to the right of it.
    expect(
      container.querySelectorAll<HTMLElement>("[data-agent-avatar]")[0]!.className,
    ).not.toContain("-ml-");
  });
});

it("keeps full-size rail faces overlapping within 40px and hides older overflow", () => {
  const { container } = render(
    <ConversationAgents
      agents={[agent("Newest"), agent("Recent"), agent("Third"), agent("Old"), agent("Oldest")]}
      showName={false}
      compact
      size="md"
    />,
  );
  const faces = container.querySelectorAll<HTMLElement>("[data-agent-avatar]");
  expect(Array.from(faces, (face) => face.dataset.agentAvatar)).toEqual([
    "Newest-id",
    "Recent-id",
    "Third-id",
  ]);
  for (const face of faces) expect(face).toHaveClass("w-9");
  expect(faces[1]).toHaveClass("-ml-[34px]");
  expect(faces[2]).toHaveClass("-ml-[34px]");
  expect(faces[0]).toHaveClass("z-30");
  expect(faces[1]).not.toHaveClass("group-hover/stack:ml-0.5");
  // 3 * 36px - 2 * 34px = 40px, with the most recent face in front.
  expect(screen.queryByText(/^\+/)).toBeNull();
  expect(screen.getByTitle("Newest → Recent → Third → Old → Oldest")).toBeInTheDocument();
});

it("overlaps two full-size faces without shrinking either one", () => {
  const { container } = render(
    <ConversationAgents
      agents={[agent("Newest"), agent("Older")]}
      compact
      size="md"
      showName={false}
    />,
  );
  const faces = container.querySelectorAll<HTMLElement>("[data-agent-avatar]");
  expect(faces[0]).toHaveClass("w-9");
  expect(faces[1]).toHaveClass("w-9", "-ml-8");
});
