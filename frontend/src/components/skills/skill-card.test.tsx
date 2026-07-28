import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { SkillCard } from "./skill-card";
import type { SkillSummary } from "@/types/providers";

const SKILL: SkillSummary = {
  id: "skill-1",
  name: "refund-policy",
  description: "How refunds and their exceptions are handled.",
  enabled: true,
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
});
