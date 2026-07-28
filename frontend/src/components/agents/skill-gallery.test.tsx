import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { SkillGallery } from "./skill-gallery";
import type { SkillSummary } from "@/types/providers";

function skill(overrides: Partial<SkillSummary> = {}): SkillSummary {
  return {
    id: "s1",
    name: "refund-policy",
    description: "How refunds are handled.",
    enabled: true,
    ...overrides,
  };
}

describe("SkillGallery", () => {
  it("searches descriptions, because that is what a skill is chosen on", async () => {
    render(
      <SkillGallery
        skills={Array.from({ length: 9 }, (_, i) =>
          skill({ id: `s${i}`, name: `skill-${i}`, description: i === 3 ? "Refunds." : "Other." }),
        )}
        total={9}
        selectedIds={[]}
        onToggle={vi.fn()}
      />,
    );

    await userEvent.type(screen.getByLabelText("Search skills…"), "refunds");

    expect(screen.getByRole("checkbox", { name: "skill-3" })).toBeInTheDocument();
    expect(screen.queryByRole("checkbox", { name: "skill-0" })).toBeNull();
  });

  it("names a selected skill the organization no longer has", () => {
    // The warning exists because publishing is refused on a dangling id, and
    // the Builder is where that is fixable.
    render(
      <SkillGallery skills={[skill()]} total={1} selectedIds={["s1", "gone"]} onToggle={vi.fn()} />,
    );

    expect(screen.getByText(/no longer has/)).toBeInTheDocument();
  });

  it("says nothing about missing skills when it was only given a page of them", () => {
    // The bug this prevents: paging the list turns every skill the Builder did
    // not fetch into an accusation that publishing will be refused - about a
    // skill that is fine and still bound.
    render(
      <SkillGallery
        skills={[skill()]}
        total={80}
        selectedIds={["s1", "on-page-two"]}
        onToggle={vi.fn()}
      />,
    );

    expect(screen.queryByText(/no longer has/)).toBeNull();
  });
});
