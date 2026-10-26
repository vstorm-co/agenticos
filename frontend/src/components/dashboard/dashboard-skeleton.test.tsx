import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { DashboardSkeleton } from "./dashboard-skeleton";
import { ROW_CLASS, SPAN_CLASS, viewLayout } from "@/lib/dashboard/layouts";

// Loading uses placements, including saved widths, heights and collapsed sections.
describe("dashboard loading placements", () => {
  it("fills the personal dashboard grid instead of promising four separate stats cards", () => {
    const sections = viewLayout("me", "member");
    const { container } = render(<DashboardSkeleton sections={sections} />);
    const cells = container.querySelectorAll("section > .grid > div");
    const entries = sections.flatMap((section) => section.entries);
    expect(cells).toHaveLength(entries.length);
    entries.forEach((entry, index) => {
      expect(cells[index]).toHaveClass(SPAN_CLASS[entry.span]);
      expect(cells[index]).toHaveClass(ROW_CLASS[entry.rows ?? "r3"]);
    });
  });

  it("honours saved placements, title overrides and folding", () => {
    const { container } = render(
      <DashboardSkeleton
        sections={[
          {
            id: "folded",
            titleKey: null,
            title: "Folded",
            collapsed: true,
            entries: [{ widget: "projects", span: "s12" }],
          },
          {
            id: "custom",
            titleKey: null,
            title: "Custom",
            entries: [{ widget: "my-agents", span: "s6", titleKey: "widgets.my-agents.title" }],
          },
        ]}
      />,
    );
    expect(container.querySelector("section:first-of-type .grid")).toBeNull();
    expect(screen.getAllByRole("status")).toHaveLength(1);
    expect(container.querySelector("section:last-of-type .grid > div")).toHaveClass(SPAN_CLASS.s6);
  });
});
