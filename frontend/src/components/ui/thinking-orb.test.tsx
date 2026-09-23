import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";

describe("ThinkingOrb", () => {
  it("renders a canvas", async () => {
    const { ThinkingOrb } = await import("./thinking-orb");
    const { container } = render(<ThinkingOrb state="searching" />);

    expect(container.querySelector("canvas")).not.toBeNull();
  });
});
