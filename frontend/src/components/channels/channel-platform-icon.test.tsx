import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { BRAND_GLYPHS } from "@/lib/brand-glyphs.generated";
import { SurfaceIcon } from "@/components/runs/surface-icon";
import { ChannelPlatformIcon } from "./channel-platform-icon";

describe("Matrix branding", () => {
  it.each(["light", "dark"])("draws the Matrix mark in channels and runs in %s mode", (theme) => {
    const { container } = render(
      <div className={theme}>
        <ChannelPlatformIcon platform="matrix" />
        <SurfaceIcon surface="matrix" />
      </div>,
    );
    const marks = container.querySelectorAll("svg");
    expect(marks).toHaveLength(2);
    for (const mark of marks) {
      expect(mark).toHaveAttribute("fill", "currentColor");
      expect(mark).toHaveAttribute("aria-hidden", "true");
      expect(mark.querySelector("path")).toHaveAttribute("d", BRAND_GLYPHS.matrix.paths[0]?.d);
    }
  });
});
