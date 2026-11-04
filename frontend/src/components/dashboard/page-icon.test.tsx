import { render } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { SectionGlyph } from "@/components/states/section-glyph";
import { Bot } from "lucide-react";

let pathname = "/agents";
vi.mock("next/navigation", () => ({ usePathname: () => pathname }));

describe("SectionGlyph", () => {
  it("uses the same neutral surface across sections", () => {
    pathname = "/rag/xyz";
    const { container, rerender } = render(<SectionGlyph icon={Bot} />);
    expect(container.firstElementChild).toHaveClass("bg-muted/70", "text-muted-foreground");

    pathname = "/profile";
    rerender(<SectionGlyph icon={Bot} />);
    expect(container.firstElementChild).toHaveClass("bg-muted/70", "text-muted-foreground");
  });
});
