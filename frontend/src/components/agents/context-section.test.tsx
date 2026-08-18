import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { ContextSection } from "./context-section";
import type { CapabilityBindingSpec, CapabilityCatalogEntry } from "@/types/agents";
import type { ContextFileSummary } from "@/types/providers";

/**
 * The Context capability, with the files it reads.
 *
 * The files used to be a card in the Skills tab, two tabs from the switch that
 * decides whether any of them reach the model. They are here now, and the
 * consequence worth pinning is the one neither control can state alone: bound
 * files with the capability off are not "injected anyway" - the injection happens
 * inside this capability, so they are nothing.
 */

const DEFINITION: CapabilityCatalogEntry = {
  id: "context",
  name: "Context",
  category: "knowledge",
  description: "Put the organization's standing context into the agent.",
  side_effecting: false,
  scopes: [],
  tools: [
    { id: "list_context", name: "list_context", description: "List the reference files." },
    { id: "read_context", name: "read_context", description: "Read one by name." },
  ],
  contracts: [],
  config_schema: {
    type: "object",
    properties: {
      expose_read_tool: {
        type: "boolean",
        title: "Expose Read Tool",
        description: "Whether link-mode files are reachable through a read tool.",
      },
    },
  },
  requires_secret: null,
};

function binding(overrides: Partial<CapabilityBindingSpec> = {}): CapabilityBindingSpec {
  return {
    id: "context",
    config: {},
    approval: "default",
    tool_approval: {},
    tool_overrides: {},
    secret_id: null,
    enabled: true,
    ...overrides,
  };
}

const FILES: ContextFileSummary[] = [
  {
    id: "f1",
    name: "glossary",
    description: "What the acronyms mean.",
    format: "md",
    mode: "inject",
    enabled: true,
    size_bytes: 120,
  } as ContextFileSummary,
  {
    id: "f2",
    name: "runbook",
    description: "What to do when it breaks.",
    format: "md",
    mode: "link",
    enabled: true,
    size_bytes: 400,
  } as ContextFileSummary,
];

function mount(props: Partial<Parameters<typeof ContextSection>[0]> = {}) {
  const onToggleFile = vi.fn();
  const onChange = vi.fn();
  render(
    <ContextSection
      definition={DEFINITION}
      binding={binding()}
      files={FILES}
      total={FILES.length}
      selectedIds={[]}
      onToggleFile={onToggleFile}
      onChange={onChange}
      {...props}
    />,
  );
  return { onToggleFile, onChange };
}

describe("the context capability's panel", () => {
  it("offers the organization's files, where the capability that reads them is", () => {
    mount();

    expect(screen.getByText("glossary")).toBeInTheDocument();
    expect(screen.getByText("runbook")).toBeInTheDocument();
  });

  it("reports a pick as a change to the bound files, not to the config", async () => {
    // `context_ids` is top level on the spec; the binding's config holds how the
    // files are reached, never which ones.
    const { onToggleFile, onChange } = mount();

    await userEvent.click(screen.getByText("glossary"));

    expect(onToggleFile).toHaveBeenCalledWith("f1");
    expect(onChange).not.toHaveBeenCalled();
  });

  it("keeps the capability's own generated form, which the files are not part of", () => {
    mount();

    expect(screen.getByLabelText("Expose Read Tool")).toBeInTheDocument();
  });

  it("says that files bound to a switched-off capability reach nothing", () => {
    mount({ binding: binding({ enabled: false }), selectedIds: ["f1"] });

    expect(screen.getByText(/Context is switched off/)).toBeInTheDocument();
  });

  it("says nothing about it while the capability is on", () => {
    mount({ selectedIds: ["f1"] });

    expect(screen.queryByText(/Context is switched off/)).not.toBeInTheDocument();
  });

  it("says nothing about it when the agent has no files bound either", () => {
    mount({ binding: binding({ enabled: false }) });

    expect(screen.queryByText(/Context is switched off/)).not.toBeInTheDocument();
  });

  it("renders nothing at all where the deployment never registered the capability", () => {
    // An empty section reads as something that failed to load.
    const { container } = render(
      <ContextSection
        definition={undefined}
        binding={binding()}
        files={FILES}
        total={FILES.length}
        selectedIds={[]}
        onToggleFile={vi.fn()}
        onChange={vi.fn()}
      />,
    );

    expect(container).toBeEmptyDOMElement();
  });
});
