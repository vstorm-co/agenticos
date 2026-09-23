import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { EntityAvatar } from "./entity-avatar";
import { avatarPalette } from "@/lib/avatar-color";

/**
 * The face a person or an organization wears when nobody uploaded one. jsdom
 * never loads an image, so Radix keeps the avatar in its fallback state - which
 * is exactly the state these tests are about.
 */
describe("EntityAvatar", () => {
  /** The generated face, which renders as inline SVG so that it can move. */
  const face = (container: HTMLElement) => container.querySelector("g.mo-root");
  /** The figure itself, for comparing one face against another. */
  const figure = (container: HTMLElement) => face(container)!.innerHTML;

  it("draws a person a face generated from their id", () => {
    const { container } = render(<EntityAvatar seed="u-1" name="Anna Nowak" />);

    expect(face(container)).not.toBeNull();
    expect(screen.queryByText("AN")).toBeNull();
  });

  it("gives the same seed the same face", () => {
    const { container, rerender } = render(<EntityAvatar seed="u-9" name="Anna Nowak" />);
    const first = figure(container);

    rerender(<EntityAvatar seed="u-9" name="Renamed Entirely" />);

    // The id is the seed, not the name: renaming somebody does not hand them
    // somebody else's face.
    expect(figure(container)).toBe(first);
  });

  it("draws two people two different faces", () => {
    const { container: a } = render(<EntityAvatar seed="u-1" name="Anna" />);
    const { container: b } = render(<EntityAvatar seed="u-2" name="Anna" />);

    expect(figure(a)).not.toBe(figure(b));
  });

  it("draws the chosen colour rather than the one the seed hashes to", () => {
    const { container: auto } = render(<EntityAvatar seed="u-1" name="Anna" />);
    const { container: picked } = render(<EntityAvatar seed="u-1" name="Anna" colorSlot={4} />);

    expect(figure(picked)).not.toBe(figure(auto));
  });

  it("draws an organization its initials on the colour its seed selects", () => {
    // A company is not somebody, and a face on one reads as a person who works
    // there.
    const { container } = render(<EntityAvatar seed="org-1" name="Vstorm Org" kind="org" />);

    expect(screen.getByText("VO")).toHaveClass(avatarPalette("org-1").bg);
    expect(face(container)).toBeNull();
  });

  it("does not draw an image when told the row has none", () => {
    // The row's picture is absent, so no request is worth making for it.
    const { container } = render(
      <EntityAvatar seed="u-1" name="Kacper" imageSrc="/api/users/avatar/u-1" hasImage={false} />,
    );

    expect(container.querySelector("img")).toBeNull();
  });

  it("attempts the image when one is given and presence is unknown", () => {
    // No `hasImage`: an id-only caller keeps today's behaviour - the picture is
    // fetched, and Radix falls through to the generated face if it 404s.
    const { container } = render(
      <EntityAvatar seed="u-1" name="Kacper" imageSrc="/api/users/avatar/u-1" />,
    );

    expect(face(container)).not.toBeNull();
  });

  it("renders at the size it was asked for", () => {
    const { container } = render(<EntityAvatar seed="u-1" name="Kacper" size="xl" />);

    expect(container.firstElementChild).toHaveClass("h-20");
  });

  it("scales an organization's initials with the circle rather than against it", () => {
    render(<EntityAvatar seed="o-1" name="Anna Nowak" kind="org" size="xl" />);

    // The scale sits on the root, beside the diameter the same token sets. A
    // font-size of the fallback's own would win over the inherited one, which
    // is how every avatar in the product drew 12px initials whatever its size:
    // two letters overflowing a 20px circle, and two small ones lost in an 80px.
    const fallback = screen.getByText("AN");
    expect(fallback.className).not.toMatch(/(^|\s)text-(xs|sm|base|lg|xl|\[\d)/);
    expect(fallback.parentElement).toHaveClass("text-lg");
  });

  it("hides itself from assistive tech when asked", () => {
    const { container } = render(<EntityAvatar seed="u-1" name="Kacper" ariaHidden />);

    expect(container.firstElementChild).toHaveAttribute("aria-hidden", "true");
  });
});
