import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type { AgentResources } from "./capability-resources";
import { SystemAgentResources } from "./system-agent-resources";
import { withCapability } from "@/lib/agent-spec";
import type { KnowledgeBase } from "@/types";
import type { SystemAgentKind } from "@/types/agents";
import type { ContextFileSummary, SkillSummary } from "@/types/providers";

const FILE = {
  id: "f1",
  name: "grading-policy",
  description: "How strictly to grade.",
  format: "md",
  mode: "inject",
  enabled: true,
  visibility: "org",
  size_bytes: 120,
} as ContextFileSummary;

const SKILL = {
  id: "s1",
  name: "rubric-writing",
  description: "How a rubric reads.",
  file_count: 1,
  category: null,
  enabled: true,
  visibility: "org",
  built_in: false,
} as SkillSummary;

/** Shared with a group, not the whole organization: a system agent's publish refuses it. */
const PRIVATE_FILE = { ...FILE, id: "f2", name: "team-notes", visibility: "private" };
const PRIVATE_SKILL = { ...SKILL, id: "s2", name: "team-style", visibility: "private" };

function mount(
  overrides: Partial<AgentResources> = {},
  { disabled = false, bound = [] as string[], kind = "judge" as SystemAgentKind } = {},
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
    <SystemAgentResources
      kind={kind}
      capabilities={capabilities}
      resources={resources}
      disabled={disabled}
    />,
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

describe("what a system agent is offered", () => {
  it("offers only what the whole organization shares, since the platform runs it for everyone", () => {
    mount({
      contextFiles: [FILE, PRIVATE_FILE],
      contextTotal: 2,
      skills: [SKILL, PRIVATE_SKILL],
      skillTotal: 2,
    });

    expect(screen.getByText("grading-policy")).toBeInTheDocument();
    expect(screen.getByText("rubric-writing")).toBeInTheDocument();
    expect(screen.queryByText("team-notes")).toBeNull();
    expect(screen.queryByText("team-style")).toBeNull();
  });

  it("still shows a narrower pick it already holds, so it can be taken off", async () => {
    const resources = mount({
      contextFiles: [FILE, PRIVATE_FILE],
      contextTotal: 2,
      contextIds: ["f2"],
      skills: [SKILL, PRIVATE_SKILL],
      skillTotal: 2,
      skillIds: ["s2"],
    });

    expect(screen.getByRole("checkbox", { name: "team-notes" })).toBeChecked();
    expect(screen.getByRole("checkbox", { name: "team-style" })).toBeChecked();
    // Listed, so not reported as a file or skill that no longer exists.
    expect(screen.queryByText(/no longer has/)).toBeNull();

    await userEvent.click(screen.getByRole("checkbox", { name: "team-notes" }));
    await userEvent.click(screen.getByRole("checkbox", { name: "team-style" }));
    expect(resources.onContextToggle).toHaveBeenCalledWith("f2");
    expect(resources.onSkillToggle).toHaveBeenCalledWith("s2");
  });

  it("names a pick that is gone once it holds every file the organization has", () => {
    mount({ contextFiles: [FILE, PRIVATE_FILE], contextTotal: 2, contextIds: ["gone"] });

    expect(screen.getByText(/1 context file this organization no longer has/)).toBeInTheDocument();
    expect(screen.getByText("gone")).toBeInTheDocument();
  });

  it("names none while part of the organization's files were never fetched", () => {
    mount({ contextFiles: [FILE, PRIVATE_FILE], contextTotal: 40, contextIds: ["elsewhere"] });

    expect(screen.queryByText(/no longer has/)).toBeNull();
  });

  it("offers a classifier no skills, only context files", () => {
    mount({}, { kind: "classifier" });

    // The card's title and its one section's heading.
    expect(screen.getAllByText("Context files")).toHaveLength(2);
    expect(screen.queryByRole("heading", { name: "Skills" })).toBeNull();
    expect(screen.queryByText("rubric-writing")).toBeNull();
    expect(screen.queryByText("Context files and skills")).toBeNull();
  });

  it("titles the card for both where the kind takes skills", () => {
    mount();

    expect(screen.getByText("Context files and skills")).toBeInTheDocument();
  });
});
