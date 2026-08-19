import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { SurfaceIcon, surfaceLabel } from "./surface-icon";

/**
 * One mark per surface, decorative beside its own name.
 *
 * The mark must be hidden from assistive tech - the caller renders the surface
 * name next to it - and an unknown surface must render nothing rather than a
 * wrong brand: a new backend surface arriving before its mark does should
 * degrade to the plain name, not borrow somebody else's logo.
 *
 * `schedule` used to be this file's example of that unknown, which is precisely
 * the hole: it reached the run table as a bare word with a blank where every
 * other row has a face. It and `trigger` have marks now, ahead of the branch
 * that makes the backend write them - a mark with no runs is invisible, and a
 * run with no mark is not.
 */
describe("SurfaceIcon", () => {
  it.each(["web", "embed", "api", "slack", "telegram", "mattermost", "schedule", "trigger"])(
    "draws a decorative mark for %s",
    (surface) => {
      const { container } = render(<SurfaceIcon surface={surface} />);
      const mark = container.querySelector("svg");
      expect(mark).not.toBeNull();
      expect(mark).toHaveAttribute("aria-hidden", "true");
    },
  );

  it("renders nothing for a surface it has no mark for", () => {
    const { container } = render(<SurfaceIcon surface="carrier-pigeon" />);
    expect(container).toBeEmptyDOMElement();
  });
});

describe("surfaceLabel", () => {
  it("names the unattended surfaces rather than printing their raw value", () => {
    const t = (key: string) => ({ surfaceSchedule: "Schedule", surfaceTrigger: "Trigger" })[key]!;

    expect(surfaceLabel("schedule", t)).toBe("Schedule");
    expect(surfaceLabel("trigger", t)).toBe("Trigger");
  });

  it("falls back to the raw value for a surface this build has no name for", () => {
    expect(surfaceLabel("carrier-pigeon", () => "unused")).toBe("carrier-pigeon");
  });
});
