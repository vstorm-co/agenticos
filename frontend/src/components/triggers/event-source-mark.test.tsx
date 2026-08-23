import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { EventSourceMark } from "./event-source-mark";
import type { EventSource } from "@/types/triggers";

/**
 * One mark per event source, drawn wherever a source is shown so the picker and
 * the trigger rows never disagree. GitHub gets a brand mark, an inbound email
 * and the API source a plain glyph; all are decorative, named by the label
 * beside them.
 */
describe("EventSourceMark", () => {
  it.each(["github", "email", "webhook"] as EventSource[])(
    "draws a decorative mark for %s",
    (source) => {
      const { container } = render(<EventSourceMark source={source} />);
      const mark = container.querySelector("svg");
      expect(mark).not.toBeNull();
      expect(mark).toHaveAttribute("aria-hidden", "true");
    },
  );

  it("passes its className through to the mark", () => {
    const { container } = render(<EventSourceMark source="github" className="h-4 w-4" />);
    expect(container.querySelector("svg")).toHaveClass("h-4", "w-4");
  });
});
