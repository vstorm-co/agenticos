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
  visibility: "org",
  file_count: 2,
  built_in: false,
  excerpt: "# Refunds\n\n1. Check the order\n- Use **the** `refund` tool",
};

function renderCard(props: Partial<React.ComponentProps<typeof SkillCard>> = {}) {
  const onOpen = vi.fn();
  render(<SkillCard skill={SKILL} onOpen={onOpen} {...props} />);
  return { onOpen };
}

describe("SkillCard", () => {
  it("shows what the model would see of the skill", () => {
    renderCard();
    expect(screen.getByText("refund-policy")).toBeInTheDocument();
    expect(screen.getByText(SKILL.description)).toBeInTheDocument();
  });

  it("stays quiet about a skill that is doing its job", () => {
    // Badging the ordinary case on every card would bury the exception.
    renderCard();
    expect(screen.queryByText("disabled")).not.toBeInTheDocument();
  });

  it("says how many files the skill carries", () => {
    renderCard();
    expect(screen.queryByText("2 files")).toBeNull();
  });

  it("keeps a single file count in the preview only", () => {
    renderCard({ skill: { ...SKILL, file_count: 1 } });
    expect(screen.queryByText("1 file")).toBeNull();
    expect(screen.getByText("+1 file")).toBeInTheDocument();
  });

  it("says in words that a skill has no files, rather than showing a bare zero", () => {
    renderCard({ skill: { ...SKILL, file_count: 0 } });
    expect(screen.queryByText("No files")).toBeNull();
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
    const { onOpen } = renderCard();
    await userEvent.click(screen.getByText("refund-policy"));
    expect(onOpen).toHaveBeenCalled();
  });

  it("keeps destructive actions out of the preview card", () => {
    renderCard();
    expect(screen.queryByRole("button", { name: "Delete refund-policy" })).toBeNull();
    expect(screen.queryByText("Details")).toBeNull();
  });

  it("shows the body's opening on a page, with a sheet behind it per file", () => {
    const { container } = render(<SkillCard skill={SKILL} onOpen={vi.fn()} />);

    expect(screen.getByText("Refunds")).toBeInTheDocument();
    expect(screen.getByText("Use the refund tool")).toBeInTheDocument();
    expect(screen.getByText("+2 files")).toBeInTheDocument();
    expect(container.querySelectorAll(".peek-sheet")).toHaveLength(2);
  });

  it("draws a blank page, not the description twice, for a skill with no body", () => {
    const { container } = render(
      <SkillCard
        skill={{ ...SKILL, excerpt: "", file_count: 0 }}

        onOpen={vi.fn()}
      />,
    );

    expect(screen.getAllByText(SKILL.description)).toHaveLength(1);
    expect(screen.queryByText("+2 files")).toBeNull();
    expect(container.querySelectorAll(".peek-sheet")).toHaveLength(0);
  });
  it("offers to give the skill to an agent, even to a reader who cannot edit it", () => {
    renderCard();
    expect(screen.getByText("add-to-agent skill skill-1")).toBeVisible();
  });
});

it("keeps preview and audience metadata visible without an expansion step", () => {
  renderCard();
  expect(screen.getByText("Refunds")).toBeVisible();
  expect(screen.getByText("Everyone")).toBeVisible();
  expect(screen.queryByText("Details")).toBeNull();
});

it("shows agent usage immediately alongside concise metadata", () => {
  renderCard({
    skill: {
      ...SKILL,
      used_by: [
        { id: "billing", name: "Billing" },
        { id: "support", name: "Support" },
      ],
    },
  });
  const usage = screen.getByText("Used by Billing, Support");
  expect(usage).toBeVisible();
  expect(usage.closest("details")).toBeNull();
  expect(screen.queryByText("Details")).toBeNull();
});

it("shows an unused resource's next step without opening Details", () => {
  renderCard({ skill: { ...SKILL, used_by: [] } });
  expect(screen.getByText("Not used by any agent yet")).toBeVisible();
});
