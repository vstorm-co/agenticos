import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { CapabilityResources, type AgentResources } from "./capability-resources";
import type { KnowledgeBase } from "@/types";
import type { ContextFileSummary, SkillSummary } from "@/types/providers";

/**
 * What an agent is given, picked in the panel of the capability that reads it.
 *
 * Collections had a tab, skills had a tab, context shared the skills one - all
 * two clicks from the switch that decides whether any of it reaches the model.
 * The panel for "Knowledge search" offered a `top_k` field and a tool
 * description, and the collections it searches were somewhere else entirely.
 *
 * The consequence worth pinning is the one no control here states alone: with the
 * capability off, the spec still carries the selection, publish still checks it,
 * and not one of them reaches a run.
 */

const FILE = {
  id: "f1",
  name: "glossary",
  description: "What the acronyms mean.",
  format: "md",
  mode: "inject",
  enabled: true,
  size_bytes: 120,
} as ContextFileSummary;

const COLLECTION = {
  id: "k1",
  name: "Handbook",
  description: "Everything HR has written down.",
  document_count: 4,
} as KnowledgeBase;

const SKILL = {
  id: "s1",
  name: "refund-policy",
  description: "How refunds work.",
  file_count: 2,
  category: null,
  enabled: true,
  built_in: false,
} as SkillSummary;

const RESOURCES: AgentResources = {
  contextFiles: [FILE],
  contextTotal: 1,
  contextIds: [],
  onContextToggle: vi.fn(),
  collections: [COLLECTION],
  collectionIds: [],
  onCollectionToggle: vi.fn(),
  skills: [SKILL],
  skillTotal: 1,
  skillIds: [],
  onSkillToggle: vi.fn(),
};

function mount(capabilityId: string, overrides: Partial<AgentResources> = {}, enabled = true) {
  const resources = { ...RESOURCES, ...overrides };
  render(
    <CapabilityResources capabilityId={capabilityId} enabled={enabled} resources={resources} />,
  );
  return resources;
}

describe("what a capability reads of the organization's", () => {
  it("offers the context files in the capability that injects them", () => {
    mount("context");

    expect(screen.getByText("glossary")).toBeInTheDocument();
  });

  it("offers the collections in the capability that searches them", () => {
    mount("knowledge");

    expect(screen.getByText("Handbook")).toBeInTheDocument();
  });

  it("offers the skills in the capability that loads them", () => {
    mount("skills");

    expect(screen.getByText("refund-policy")).toBeInTheDocument();
  });

  it("renders nothing for a capability that reads nothing of the organization's", () => {
    const { container } = render(
      <CapabilityResources capabilityId="charts" enabled resources={RESOURCES} />,
    );

    expect(container).toBeEmptyDOMElement();
  });

  it("reports a pick against the spec's own list, not the capability's config", async () => {
    // `collection_ids` is top level; a binding's config holds how the capability
    // behaves, never what it was given.
    const resources = mount("knowledge");

    await userEvent.click(screen.getByText("Handbook"));

    expect(resources.onCollectionToggle).toHaveBeenCalledWith("k1");
  });

  it.each([
    ["context", { contextIds: ["f1"] }, /Context is switched off/],
    ["knowledge", { collectionIds: ["k1"] }, /Knowledge search is switched off/],
    ["skills", { skillIds: ["s1"] }, /Skills is switched off/],
  ])("says that %s bound to a switched-off capability reaches nothing", (id, bound, said) => {
    mount(id, bound, false);

    expect(screen.getByText(said)).toBeInTheDocument();
  });

  it("says nothing about it while the capability is on", () => {
    mount("knowledge", { collectionIds: ["k1"] }, true);

    expect(screen.queryByText(/switched off/)).not.toBeInTheDocument();
  });

  it("says nothing about it when the capability is off and nothing is bound", () => {
    mount("knowledge", {}, false);

    expect(screen.queryByText(/switched off/)).not.toBeInTheDocument();
  });
});
