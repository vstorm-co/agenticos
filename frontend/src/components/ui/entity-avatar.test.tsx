import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { EntityAvatar } from "./entity-avatar";
import { avatarPalette } from "@/lib/avatar-color";

/**
 * The face a person, org or agent wears when nobody uploaded one. jsdom never
 * loads an image, so Radix keeps the avatar in its fallback state - which is
 * exactly the state these tests are about.
 */
describe("EntityAvatar", () => {
  it("draws the initials on the colour its seed selects", () => {
    render(<EntityAvatar seed="org-1" name="Vstorm Org" />);

    const fallback = screen.getByText("VO");
    expect(fallback).toHaveClass(avatarPalette("org-1").bg);
  });

  it("gives the same seed the same colour", () => {
    const { rerender } = render(<EntityAvatar seed="u-9" name="Anna Nowak" />);
    const first = screen.getByText("AN").className;

    rerender(<EntityAvatar seed="u-9" name="Anna Nowak" />);
    expect(screen.getByText("AN").className).toBe(first);
  });

  it("draws a glyph when the name yields no initials", () => {
    const { container } = render(
      <EntityAvatar seed="a-1" name="   " fallbackIcon={<svg data-testid="glyph" />} />,
    );

    expect(container.querySelector("[data-testid='glyph']")).not.toBeNull();
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
    // fetched, and Radix falls through to these initials if it 404s.
    render(<EntityAvatar seed="u-1" name="Kacper" imageSrc="/api/users/avatar/u-1" />);

    expect(screen.getByText("K")).toBeInTheDocument();
  });

  it("renders at the size it was asked for", () => {
    const { container } = render(<EntityAvatar seed="u-1" name="Kacper" size="xl" />);

    expect(container.firstElementChild).toHaveClass("h-20");
  });
});
