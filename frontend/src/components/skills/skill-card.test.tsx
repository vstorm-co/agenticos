import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { SkillCard } from "./skill-card";
import type { SkillSummary } from "@/types/providers";

// Its own spec covers the picker; a card only has to offer it for the right thing.
vi.mock("@/components/agents/add-to-agent", () => ({
  AddToAgent: ({ resource }: { resource: { kind: string; id: string } }) => (
    <span>{`add-to-agent ${resource.kind} ${resource.id}`}</span>
  ),
}));

const SKILL: SkillSummary = {
  id: "skill-1",
  name: "refund-policy",
  description: "How refunds and their exceptions are handled.",
  category: null,
  enabled: true,
  visibility: "org",
  file_count: 2,
  built_in: false,
  excerpt: "# Refunds\n\n1. Check the order\n- Use **the** `refund` tool",
};

function renderCard(props: Partial<React.ComponentProps<typeof SkillCard>> = {}) {
  const onOpen = vi.fn();
  const onDelete = vi.fn();
  render(<SkillCard skill={SKILL} canEdit onOpen={onOpen} onDelete={onDelete} {...props} />);
  return { onOpen, onDelete };
}

describe("SkillCard", () => {
  it("shows what the model would see of the skill", () => {
    renderCard();
    expect(screen.getByText("refund-policy")).toBeInTheDocument();
    expect(screen.getByText(SKILL.description)).toBeInTheDocument();
  });

  it("marks a skill agents are currently skipping", () => {
    renderCard({ skill: { ...SKILL, enabled: false } });
    expect(screen.getByText("disabled")).toBeInTheDocument();
  });

  it("stays quiet about a skill that is doing its job", () => {
    // Badging the ordinary case on every card would bury the exception.
    renderCard();
    expect(screen.queryByText("disabled")).not.toBeInTheDocument();
  });

  it("says how many files the skill carries", () => {
    renderCard();
    expect(screen.getByText("2 files")).toBeInTheDocument();
  });

  it("uses the singular for one file", () => {
    renderCard({ skill: { ...SKILL, file_count: 1 } });
    expect(screen.getByText("1 file")).toBeInTheDocument();
  });

  it("says in words that a skill has no files, rather than showing a bare zero", () => {
    renderCard({ skill: { ...SKILL, file_count: 0 } });
    expect(screen.getByText("No files")).toBeInTheDocument();
  });

  it("marks a skill that shipped with the deployment", () => {
    renderCard({ skill: { ...SKILL, built_in: true } });
    expect(screen.getByText("built-in")).toBeInTheDocument();
  });

  it("does not accuse a custom skill of being built-in", () => {
    renderCard();
    expect(screen.queryByText("built-in")).not.toBeInTheDocument();
  });

  it("names the shelf a categorized skill sits on, as a label rather than a slug", () => {
    renderCard({ skill: { ...SKILL, category: "customer-support" } });
    expect(screen.getByText("Customer support")).toBeInTheDocument();
  });

  it("opens the skill when its name is clicked", async () => {
    const { onOpen, onDelete } = renderCard();
    await userEvent.click(screen.getByText("refund-policy"));
    expect(onOpen).toHaveBeenCalled();
    expect(onDelete).not.toHaveBeenCalled();
  });

  it("keeps deleting separate from opening", async () => {
    const { onOpen, onDelete } = renderCard();
    await userEvent.click(screen.getByRole("button", { name: "Delete refund-policy" }));
    expect(onDelete).toHaveBeenCalled();
    expect(onOpen).not.toHaveBeenCalled();
  });

  it("offers a viewer no way to delete a skill they can still read", async () => {
    const { onOpen, onDelete } = renderCard({ canEdit: false });
    expect(screen.queryByRole("button", { name: "Delete refund-policy" })).not.toBeInTheDocument();
    await userEvent.click(screen.getByText("refund-policy"));
    expect(onOpen).toHaveBeenCalled();
    expect(onDelete).not.toHaveBeenCalled();
  });

  it("shows the body's opening on a page, with a sheet behind it per file", () => {
    const { container } = render(
      <SkillCard skill={SKILL} canEdit={false} onOpen={vi.fn()} onDelete={vi.fn()} />,
    );

    expect(screen.getByText("Refunds")).toBeInTheDocument();
    expect(screen.getByText("Use the refund tool")).toBeInTheDocument();
    expect(screen.getByText("+2 files")).toBeInTheDocument();
    expect(container.querySelectorAll(".peek-sheet")).toHaveLength(2);
  });

  it("draws a blank page, not the description twice, for a skill with no body", () => {
    const { container } = render(
      <SkillCard
        skill={{ ...SKILL, excerpt: "", file_count: 0 }}
        canEdit={false}
        onOpen={vi.fn()}
        onDelete={vi.fn()}
      />,
    );

    expect(screen.getAllByText(SKILL.description)).toHaveLength(1);
    expect(screen.queryByText("+2 files")).toBeNull();
    expect(container.querySelectorAll(".peek-sheet")).toHaveLength(0);
  });
  it("offers to give the skill to an agent, even to a reader who cannot edit it", () => {
    renderCard({ canEdit: false });
    expect(screen.getByText("add-to-agent skill skill-1")).toBeInTheDocument();
  });
});
