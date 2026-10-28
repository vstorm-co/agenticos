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
  it("draws readable initials for a person without a photo", () => {
    const { container } = render(<EntityAvatar seed="u-1" name="Anna Nowak" />);
    expect(screen.getByText("AN")).toHaveClass(avatarPalette("u-1").bg);
    expect(container.querySelector("g.mo-root")).toBeNull();
  });

  it("keeps the colour after a rename while updating the initials", () => {
    const { rerender } = render(<EntityAvatar seed="u-9" name="Anna Nowak" />);
    const palette = avatarPalette("u-9");
    expect(screen.getByText("AN")).toHaveClass(palette.bg);
    rerender(<EntityAvatar seed="u-9" name="Renamed Person" />);
    expect(screen.getByText("RP")).toHaveClass(palette.bg);
  });

  it("honours a chosen colour", () => {
    render(<EntityAvatar seed="u-1" name="Anna" colorSlot={4} />);
    expect(screen.getByText("A")).toHaveClass(avatarPalette("u-1", 4).bg);
  });

  it("keeps avatars round despite a caller's square styling", () => {
    const { container } = render(
      <EntityAvatar seed="org-1" name="Vstorm" className="rounded-xl" />,
    );
    expect(container.firstElementChild).toHaveClass("rounded-full");
    expect(container.firstElementChild).not.toHaveClass("rounded-xl");
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
    // fetched, and Radix falls through to the initials if it 404s.
    render(<EntityAvatar seed="u-1" name="Kacper" imageSrc="/api/users/avatar/u-1" />);

    expect(screen.getByText("K")).toBeInTheDocument();
  });

  it("renders at the size it was asked for", () => {
    const { container } = render(<EntityAvatar seed="u-1" name="Kacper" size="xl" />);

    expect(container.firstElementChild).toHaveClass("h-20");
  });

  it("scales an organization's initials with the circle rather than against it", () => {
    render(<EntityAvatar seed="o-1" name="Anna Nowak" size="xl" />);

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
