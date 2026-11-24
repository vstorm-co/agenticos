import { render } from "@testing-library/react";
import { Landmark, Library } from "lucide-react";
import { describe, expect, it } from "vitest";

import { IndustryIcon, industryIcon } from "./industry-icon";

describe("industry icons", () => {
  it("draws the industry's own icon", () => {
    expect(industryIcon("finance")).toBe(Landmark);
    const { container } = render(<IndustryIcon id="finance" data-testid="icon" />);
    expect(container.querySelector("svg")).toHaveClass("lucide-landmark");
  });

  it("falls back to the library icon for an industry the console does not know", () => {
    expect(industryIcon("space")).toBe(Library);
    const { container } = render(<IndustryIcon id="space" />);
    expect(container.querySelector("svg")).toHaveClass("lucide-library");
  });
});
