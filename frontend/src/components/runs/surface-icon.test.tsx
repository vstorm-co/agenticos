import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { SurfaceIcon } from "./surface-icon";

/**
 * One mark per surface, decorative beside its own name.
 *
 * The mark must be hidden from assistive tech - the caller renders the surface
 * name next to it - and an unknown surface must render nothing rather than a
 * wrong brand: a new backend surface arriving before its mark does should
 * degrade to the plain name, not borrow somebody else's logo.
 */
describe("SurfaceIcon", () => {
  it.each(["web", "embed", "api", "slack", "telegram", "mattermost"])(
    "draws a decorative mark for %s",
    (surface) => {
      const { container } = render(<SurfaceIcon surface={surface} />);
      const mark = container.querySelector("svg");
      expect(mark).not.toBeNull();
      expect(mark).toHaveAttribute("aria-hidden", "true");
    },
  );

  it("renders nothing for a surface it has no mark for", () => {
    const { container } = render(<SurfaceIcon surface="schedule" />);
    expect(container).toBeEmptyDOMElement();
  });
});
