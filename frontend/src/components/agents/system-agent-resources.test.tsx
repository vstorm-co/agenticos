import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type { AgentResources } from "./capability-resources";
import { SystemAgentResources } from "./system-agent-resources";
import { withCapability } from "@/lib/agent-spec";
import type { KnowledgeBase } from "@/types";
import type { ContextFileSummary, SkillSummary } from "@/types/providers";

const FILE = {
  id: "f1",
  name: "grading-policy",
  description: "How strictly to grade.",
  format: "md",
  mode: "inject",
  enabled: true,
  size_bytes: 120,
} as ContextFileSummary;

const SKILL = {
  id: "s1",
  name: "rubric-writing",
  description: "How a rubric reads.",
  file_count: 1,
  category: null,
  enabled: true,
  built_in: false,
} as SkillSummary;

function mount(
  overrides: Partial<AgentResources> = {},
  { disabled = false, bound = [] as string[] } = {},
) {
  const resources: AgentResources = {
    contextFiles: [FILE],
    contextTotal: 1,
    contextIds: [],
    onContextToggle: vi.fn(),
    collections: [{ id: "k1", name: "Handbook" } as KnowledgeBase],
    collectionIds: [],
    onCollectionToggle: vi.fn(),
    skills: [SKILL],
    skillTotal: 1,
    skillIds: [],
    onSkillToggle: vi.fn(),
    ...overrides,
  };
  const capabilities = bound.reduce(
    (list, id) => withCapability(list, id, true),
    withCapability([], "thinking", true),
  );
  render(
    <SystemAgentResources capabilities={capabilities} resources={resources} disabled={disabled} />,
  );
  return resources;
}

describe("a system agent's context files and skills", () => {
  it("offers both on the Build tab, with nothing to switch on first", async () => {
    const resources = mount();

    expect(screen.getByRole("heading", { name: "Context files" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Skills" })).toBeInTheDocument();
    expect(screen.queryByText("Handbook")).toBeNull();

    await userEvent.click(screen.getByText("grading-policy"));
    await userEvent.click(screen.getByText("rubric-writing"));

    expect(resources.onContextToggle).toHaveBeenCalledWith("f1");
    expect(resources.onSkillToggle).toHaveBeenCalledWith("s1");
  });

  it("says nothing is off while the capability reading each is bound", () => {
    mount({ contextIds: ["f1"], skillIds: ["s1"] }, { bound: ["context", "skills"] });

    expect(screen.queryByText(/switched off/)).toBeNull();
  });

  it("says when a stored pick reaches nothing because its capability is not bound", () => {
    mount({ contextIds: ["f1"], skillIds: ["s1"] });

    expect(screen.getByText(/Context is switched off/)).toBeInTheDocument();
    expect(screen.getByText(/Skills is switched off/)).toBeInTheDocument();
  });

  it("takes no pick from somebody who may not change the agent", async () => {
    const resources = mount({}, { disabled: true });

    await userEvent.click(screen.getByText("grading-policy"));
    await userEvent.click(screen.getByText("rubric-writing"));

    expect(resources.onContextToggle).not.toHaveBeenCalled();
    expect(resources.onSkillToggle).not.toHaveBeenCalled();
  });
});
