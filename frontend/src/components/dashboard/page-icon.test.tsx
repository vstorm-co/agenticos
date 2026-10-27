import { render } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { SectionGlyph } from "@/components/states/section-glyph";
import { Bot } from "lucide-react";

let pathname = "/agents";
vi.mock("next/navigation", () => ({ usePathname: () => pathname }));

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
