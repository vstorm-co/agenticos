import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { AgentAvatar } from "./agent-avatar";

/**
 * The picture that stands in for an agent everywhere one is named.
 *
 * A face generated from the agent's id rather than a generic robot: a wall of
 * identical robot glyphs tells a reader nothing, and telling two agents apart at
 * a glance is the whole point of having a picture. jsdom never loads an image,
 * so Radix keeps the avatar in its fallback state - which is the state under
 * test.
 */
describe("AgentAvatar", () => {
  const face = (container: HTMLElement) => container.querySelector("g.mo-root");
  /** The figure itself, for comparing one agent's face against another's. */
  const drawing = (container: HTMLElement) => face(container)!.innerHTML;

  it("draws a face generated from the agent's handle", () => {
    const { container } = render(<AgentAvatar agentId="a1" slug="support" />);

    expect(face(container)).not.toBeNull();
  });

  it("draws two agents two different faces", () => {
    const { container: a } = render(<AgentAvatar agentId="a1" slug="support" />);
    const { container: b } = render(<AgentAvatar agentId="a2" slug="refunds" />);

    expect(drawing(a)).not.toBe(drawing(b));
  });

  it("draws the handle rather than the id, so a moved row keeps its face", () => {
    // The handle is what a name derives into and then never changes again, which
    // is what lets the creation dialog show the face before the agent exists.
    const { container: a } = render(<AgentAvatar agentId="a1" slug="support" />);
    const { container: b } = render(<AgentAvatar agentId="somewhere-else" slug="support" />);

    expect(drawing(a)).toBe(drawing(b));
  });

  it("wears the chosen colour rather than the one the handle hashes to", () => {
    const { container: auto } = render(<AgentAvatar agentId="a1" slug="support" />);
    const { container: picked } = render(<AgentAvatar agentId="a1" slug="support" colorSlot={4} />);

    expect(drawing(picked)).not.toBe(drawing(auto));
  });

  it("stays out of the accessible tree", () => {
    // Every one of these is drawn beside the agent's name, so a name on the
    // picture too is the same words read twice.
    const { container } = render(<AgentAvatar agentId="a1" slug="support" />);

    expect(container.querySelector("svg")).toHaveAttribute("aria-hidden", "true");
  });

  it("still shows the face while a stored picture is being fetched", () => {
    // The fallback is what a reader sees until the request answers - Radix only
    // puts the picture in the DOM once it has loaded, which in jsdom is never.
    // The request itself goes through the API, so it carries the same access
    // check as reading the agent.
    const { container } = render(<AgentAvatar agentId="a1" slug="support" hasAvatar />);

    expect(face(container)).not.toBeNull();
  });

  it("takes a version, which is what defeats the cache after an upload", () => {
    // Without it a replaced picture keeps rendering as the old one until a hard
    // reload, because the URL did not change.
    const { container } = render(<AgentAvatar agentId="a1" slug="support" hasAvatar version={2} />);

    expect(face(container)).not.toBeNull();
  });

  it("draws the face mid-thought while the agent is answering", () => {
    // A change of pose on a face already blinking and breathing, which is what
    // makes it read as thought rather than as decoration.
    const { container } = render(<AgentAvatar agentId="a1" slug="support" thinking />);
    const { container: idle } = render(<AgentAvatar agentId="a1" slug="support" />);

    expect(container.querySelector("g.mo-expr")).not.toBeNull();
    expect(idle.querySelector("g.mo-expr")).toBeNull();
  });

  it("renders at the size it was asked for", () => {
    const { container } = render(<AgentAvatar agentId="a1" slug="support" size="xl" />);

    expect(container.firstElementChild).toHaveClass("h-20");
  });
});
