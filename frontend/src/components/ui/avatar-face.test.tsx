import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { AvatarFace } from "./avatar-face";
import { AVATAR_HUES } from "@/lib/avatar-color";

/**
 * The generated face itself.
 *
 * Inline SVG rather than an image, and that is the whole cost of animating one:
 * a document inside an `<img>` is isolated, so no stylesheet reaches the shapes
 * and a face rendered that way can only hold still.
 */
describe("AvatarFace", () => {
  const svg = (container: HTMLElement) => container.querySelector("svg");
  /** The figure, without the `<title>` and the backdrop drawn beside it. */
  const figure = (container: HTMLElement) => container.querySelector("g.mo-root")!.innerHTML;

  it("renders as inline SVG that is always moving", () => {
    const { container } = render(<AvatarFace seed="u-1" />);

    expect(container.querySelector("g.mo-always")).not.toBeNull();
    expect(container.querySelector("img")).toBeNull();
  });

  it("is decorative", () => {
    // Every one of these is drawn beside the name it stands for. A `<title>`
    // would be those words read twice, and it would put them in the DOM as text
    // where a list that already renders the name suddenly holds it twice.
    const { container } = render(<AvatarFace seed="u-1" />);

    expect(svg(container)).toHaveAttribute("aria-hidden", "true");
  });

  it("draws the same seed the same face", () => {
    const { container: a } = render(<AvatarFace seed="u-1" />);
    const { container: b } = render(<AvatarFace seed="u-1" />);

    expect(figure(a)).toBe(figure(b));
  });

  it("draws two seeds two faces", () => {
    const { container: a } = render(<AvatarFace seed="u-1" />);
    const { container: b } = render(<AvatarFace seed="u-2" />);

    expect(figure(a)).not.toBe(figure(b));
  });

  it("draws a chosen slot at that swatch's hue", () => {
    // The picker shows ten fills; picking one has to move the face's colour to
    // the same place, which the palette's `oklch` hue is what decides.
    const { container } = render(<AvatarFace seed="u-1" colorSlot={6} />);
    const { container: other } = render(<AvatarFace seed="u-1" colorSlot={1} />);

    expect(AVATAR_HUES[5]).not.toBe(AVATAR_HUES[0]);
    expect(figure(container)).not.toBe(figure(other));
  });

  it("puts on an expression while it is thinking", () => {
    // A change of pose on a creature already moving, which is what makes it read
    // as thought rather than as the one thing on screen that moves.
    const { container } = render(<AvatarFace seed="u-1" thinking />);
    const { container: idle } = render(<AvatarFace seed="u-1" />);

    expect(container.querySelector("g.mo-expr")).not.toBeNull();
    expect(idle.querySelector("g.mo-expr")).toBeNull();
  });

  it("fills the circle it is put in", () => {
    const { container } = render(<AvatarFace seed="u-1" />);

    expect(svg(container)).toHaveClass("h-full", "w-full");
  });
});
