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
    category: null,
    enabled: true,
    file_count: 0,
    built_in: false,
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

  it("sends somebody to write one when the organization has no skills", () => {
    render(<SkillGallery skills={[]} total={0} selectedIds={[]} onToggle={vi.fn()} />);

    expect(screen.getByText("This organization has written no skills yet.")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Write one/ })).toBeInTheDocument();
  });

  it("says which skills are attached", () => {
    render(
      <SkillGallery
        skills={[skill(), skill({ id: "s2", name: "escalation" })]}
        total={2}
        selectedIds={["s2"]}
        onToggle={vi.fn()}
      />,
    );

    expect(screen.getByRole("checkbox", { name: "escalation" })).toBeChecked();
    expect(screen.getByRole("checkbox", { name: "refund-policy" })).not.toBeChecked();
  });

  it("attaches the skill that was pressed", async () => {
    const onToggle = vi.fn();
    render(<SkillGallery skills={[skill()]} total={1} selectedIds={[]} onToggle={onToggle} />);

    await userEvent.click(screen.getByRole("checkbox", { name: "refund-policy" }));

    expect(onToggle).toHaveBeenCalledWith("s1");
  });

  it("attaches nothing for somebody who may not edit the spec", async () => {
    const onToggle = vi.fn();
    render(
      <SkillGallery skills={[skill()]} total={1} selectedIds={[]} onToggle={onToggle} disabled />,
    );

    await userEvent.click(screen.getByRole("checkbox", { name: "refund-policy" }));

    expect(onToggle).not.toHaveBeenCalled();
  });

  it("marks a skill that is switched off, because attaching it changes nothing", () => {
    render(
      <SkillGallery
        skills={[skill({ enabled: false })]}
        total={1}
        selectedIds={[]}
        onToggle={vi.fn()}
      />,
    );

    expect(screen.getByText("disabled")).toBeInTheDocument();
  });

  it("shows the description, which is what the decision is made on", () => {
    render(<SkillGallery skills={[skill()]} total={1} selectedIds={[]} onToggle={vi.fn()} />);

    expect(screen.getByText("How refunds are handled.")).toBeInTheDocument();
  });

  it("counts more than one missing skill in the plural", () => {
    render(
      <SkillGallery
        skills={[skill()]}
        total={1}
        selectedIds={["gone-1", "gone-2"]}
        onToggle={vi.fn()}
      />,
    );

    expect(screen.getByText(/2 skills this organization no longer has/)).toBeInTheDocument();
  });

  it("uses the singular for a single missing skill", () => {
    render(<SkillGallery skills={[skill()]} total={1} selectedIds={["gone"]} onToggle={vi.fn()} />);

    expect(screen.getByText(/1 skill this organization no longer has/)).toBeInTheDocument();
  });

  it("offers no search for a list short enough to read", () => {
    render(<SkillGallery skills={[skill()]} total={1} selectedIds={[]} onToggle={vi.fn()} />);

    expect(screen.queryByLabelText("Search skills…")).toBeNull();
  });
});
