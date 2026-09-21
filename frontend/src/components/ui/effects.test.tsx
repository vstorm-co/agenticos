import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { GeneratedImage } from "./generated-image";
import { VoiceGlow } from "./voice-glow";

/**
 * The decorative layer, which has one rule in common: it wraps something and
 * must never be the reason that something is not there. jsdom has no WebGL, no
 * Web Audio and no canvas, which is the same position as a browser that has
 * turned them off - so these tests are the fallback path as much as they are
 * the happy one.
 */
describe("the effect wrappers", () => {
  it("VoiceGlow leaves what it wraps alone where there is no Web Audio", () => {
    render(
      <VoiceGlow>
        <textarea aria-label="Message" />
      </VoiceGlow>,
    );

    expect(screen.getByLabelText("Message")).toBeInTheDocument();
  });

  it("GeneratedImage draws the plain picture where the shader cannot run", () => {
    // jsdom has no WebGL, which is the same position as a browser that refuses
    // one: the image is what matters and it is still there.
    render(<GeneratedImage src="/api/files/f-1" alt="chart.png" />);

    expect(screen.getByAltText("chart.png")).toBeInTheDocument();
  });
});
