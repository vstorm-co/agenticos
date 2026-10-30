import { render, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { useArchitectMarkStore } from "@/stores/architect-mark-store";

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
  afterEach(() => useArchitectMarkStore.setState({ agentId: null }));

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

  it("holds the face back while a stored picture loads, then shows it if none came", async () => {
    // Shown at once, the generated face flashed wherever a picture was about to
    // appear. Radix only puts the picture in the DOM once it has loaded, which in
    // jsdom is never - so here the face arrives after the delay, as it would for
    // a picture that failed. The request goes through the API, so it carries the
    // same access check as reading the agent.
    const { container } = render(<AgentAvatar agentId="a1" slug="support" hasAvatar />);

    expect(face(container)).toBeNull();
    await waitFor(() => expect(face(container)).not.toBeNull());
  });

  it("takes a version, which is what defeats the cache after an upload", async () => {
    // Without it a replaced picture keeps rendering as the old one until a hard
    // reload, because the URL did not change.
    const { container } = render(<AgentAvatar agentId="a1" slug="support" hasAvatar version={2} />);

    await waitFor(() => expect(face(container)).not.toBeNull());
  });

  it("draws the Architect's blueprint mark while it wears it", () => {
    // Its stored picture is one fixed image - dark on a dark page - so the mark is
    // drawn instead, for that agent only.
    useArchitectMarkStore.setState({ agentId: "architect-1" });

    const { container: architect } = render(
      <AgentAvatar agentId="architect-1" slug="architect" hasAvatar />,
    );
    const { container: other } = render(<AgentAvatar agentId="a1" slug="support" />);

    expect(architect.querySelector('svg rect[fill="#2557d6"]')).not.toBeNull();
    expect(architect.querySelector("span")).toHaveClass("rounded-[30%]");
    expect(face(other)).not.toBeNull();
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
