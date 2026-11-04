import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { BlobbyFace } from "./blobby-face";

describe("BlobbyFace", () => {
  it("draws a living blobatar in each expression it can wear", () => {
    for (const expression of [
      "idle",
      "happy",
      "love",
      "sleepy",
      "thinking",
      "surprised",
    ] as const) {
      const { container, unmount } = render(
        <BlobbyFace
          face={{ seed: "pebble", hue: 215, traits: { shape: 0.11 } }}
          expression={expression}
          gaze={{ x: 1, y: 2 }}
          size={112}
        />,
      );
      expect(container.querySelector("svg")).not.toBeNull();
      unmount();
    }
  });
});
