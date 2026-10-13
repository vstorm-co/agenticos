import { render } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { PageIcon } from "./page-icon";
import { SectionGlyph } from "@/components/states/section-glyph";
import { Bot } from "lucide-react";

let pathname = "/agents";
vi.mock("next/navigation", () => ({ usePathname: () => pathname }));

describe("PageIcon", () => {
  beforeEach(() => {
    pathname = "/agents";
  });

  it("draws the section's glyph in its hue on the section's own page", () => {
    const { container } = render(<PageIcon />);

    expect(container.firstElementChild).toHaveClass("domain-build");
    expect(container.querySelector("svg")).not.toBeNull();
  });

  it("draws nothing below the section page, or outside the nav", () => {
    pathname = "/agents/abc";
    const { container, rerender } = render(<PageIcon />);
    expect(container.firstElementChild).toBeNull();

    pathname = "/settings";
    rerender(<PageIcon />);
    expect(container.firstElementChild).toBeNull();
  });
});

describe("SectionGlyph", () => {
  it("takes the current section's hue, and the neutral one outside the nav", () => {
    pathname = "/rag/xyz";
    const { container, rerender } = render(<SectionGlyph icon={Bot} />);
    expect(container.firstElementChild).toHaveClass("domain-knowledge");

    pathname = "/profile";
    rerender(<SectionGlyph icon={Bot} />);
    expect(container.firstElementChild).toHaveClass("domain-use");
  });
});
