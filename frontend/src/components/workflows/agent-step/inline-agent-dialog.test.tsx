import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type { AgentSpec, CapabilityBindingSpec } from "@/types/agents";

import { blankSpec } from "./agent-source-field";
import { InlineAgentDialog } from "./inline-agent-dialog";

type Resources = {
  onContextToggle: (id: string) => void;
  onCollectionToggle: (id: string) => void;
  onSkillToggle: (id: string) => void;
};

const seen = vi.hoisted(() => ({ catalog: [] as string[], agentId: undefined as unknown }));

vi.mock("@/hooks", () => ({
  useCapabilityCatalog: () => ({
    capabilities: [{ id: "clock" }, { id: "subagents" }, { id: "knowledge" }, { id: "workflows" }],
  }),
  useModelProviders: () => ({ profiles: [], profilesStatus: "loaded" }),
  useSkills: () => ({ skills: [], total: 0 }),
  useKnowledgeBases: () => ({ kbs: [] }),
}));
vi.mock("@/hooks/use-context", () => ({ useContextFiles: () => ({ files: [], total: 0 }) }));
vi.mock("@/components/agents/model-profile-picker", () => ({
  ModelProfilePicker: ({ onChange }: { onChange: (id: string | null) => void }) => (
    <button type="button" onClick={() => onChange("m1")}>
      pick-model
    </button>
  ),
}));
vi.mock("@/components/agents/mcp-bindings-editor", () => ({
  McpBindingsEditor: ({
    onChange,
  }: {
    onChange: (changes: { mcp_servers: unknown[] }) => void;
  }) => (
    <button
      type="button"
      onClick={() =>
        onChange({
          mcp_servers: [{ account: "organization", connection_id: "c1", allowed_tools: null }],
        })
      }
    >
      bind-server
    </button>
  ),
}));
vi.mock("@/components/agents/capability-workbench", () => ({
  CapabilityWorkbench: ({
    agentId,
    catalog,
    onToggle,
    onChange,
    onSubagentsChange,
    resources,
  }: {
    agentId: unknown;
    catalog: { id: string }[];
    onToggle: (id: string) => void;
    onChange: (binding: CapabilityBindingSpec) => void;
    onSubagentsChange: (next: unknown[]) => void;
    resources: Resources;
  }) => {
    seen.catalog = catalog.map((entry) => entry.id);
    seen.agentId = agentId;
    return (
      <div>
        <button type="button" onClick={() => onToggle("clock")}>
          toggle-clock
        </button>
        <button
          type="button"
          onClick={() =>
            onChange({ id: "clock", config: { tz: "UTC" } } as unknown as CapabilityBindingSpec)
          }
        >
          configure-clock
        </button>
        <button type="button" onClick={() => resources.onCollectionToggle("kb1")}>
          toggle-kb
        </button>
        <button type="button" onClick={() => resources.onSkillToggle("s1")}>
          toggle-skill
        </button>
        <button type="button" onClick={() => resources.onContextToggle("f1")}>
          toggle-context
        </button>
        <button type="button" onClick={() => onSubagentsChange([])}>
          subagents
        </button>
      </div>
    );
  },
}));

function renderDialog(spec: AgentSpec = blankSpec("Step agent")) {
  const onSave = vi.fn();
  const onOpenChange = vi.fn();
  render(<InlineAgentDialog open spec={spec} onOpenChange={onOpenChange} onSave={onSave} />);
  return { onSave, onOpenChange };
}

describe("InlineAgentDialog", () => {
  it("hands back the whole spec as edited, once, on apply", async () => {
    const { onSave } = renderDialog();

    const name = screen.getByLabelText("Name");
    await userEvent.clear(name);
    await userEvent.type(name, "Scorer");
    await userEvent.type(screen.getByLabelText("Instructions"), "Score it.");
    await userEvent.click(screen.getByRole("button", { name: "pick-model" }));
    await userEvent.click(screen.getByRole("tab", { name: "Capabilities and knowledge" }));
    await userEvent.click(screen.getByRole("button", { name: "toggle-clock" }));
    await userEvent.click(screen.getByRole("button", { name: "configure-clock" }));
    await userEvent.click(screen.getByRole("button", { name: "toggle-kb" }));
    await userEvent.click(screen.getByRole("button", { name: "toggle-kb" }));
    await userEvent.click(screen.getByRole("button", { name: "toggle-kb" }));
    await userEvent.click(screen.getByRole("button", { name: "toggle-skill" }));
    await userEvent.click(screen.getByRole("button", { name: "toggle-context" }));
    await userEvent.click(screen.getByRole("button", { name: "subagents" }));
    await userEvent.click(screen.getByRole("tab", { name: "MCP servers" }));
    await userEvent.click(screen.getByRole("button", { name: "bind-server" }));
    expect(onSave).not.toHaveBeenCalled();
    await userEvent.click(screen.getByRole("button", { name: "Use this configuration" }));

    const saved = onSave.mock.calls[0]?.[0] as AgentSpec;
    expect(saved.name).toBe("Scorer");
    expect(saved.instructions).toBe("Score it.");
    expect(saved.model_profile_id).toBe("m1");
    expect(saved.capabilities.find((binding) => binding.id === "clock")?.config).toEqual({
      tz: "UTC",
    });
    expect(saved.collection_ids).toEqual(["kb1"]);
    expect(saved.skill_ids).toEqual(["s1"]);
    expect(saved.context_ids).toEqual(["f1"]);
    expect(saved.mcp_servers).toHaveLength(1);
  });

  it("offers every capability but delegating and starting workflows, and no notes to clear", async () => {
    renderDialog();

    await userEvent.click(screen.getByRole("tab", { name: "Capabilities and knowledge" }));

    expect(seen.catalog).toEqual(["clock", "knowledge"]);
    expect(seen.agentId).toBeNull();
  });

  it("an agent with no name cannot be applied", async () => {
    renderDialog();

    await userEvent.clear(screen.getByLabelText("Name"));

    expect(screen.getByRole("button", { name: "Use this configuration" })).toBeDisabled();
  });

  it("cancelling closes without handing anything back", async () => {
    const { onSave, onOpenChange } = renderDialog();

    await userEvent.click(screen.getByRole("button", { name: "Cancel" }));

    expect(onOpenChange).toHaveBeenCalledWith(false);
    expect(onSave).not.toHaveBeenCalled();
  });

  it("renders nothing to edit while closed", () => {
    render(
      <InlineAgentDialog
        open={false}
        spec={blankSpec("x")}
        onOpenChange={vi.fn()}
        onSave={vi.fn()}
      />,
    );

    expect(screen.queryByLabelText("Name")).toBeNull();
  });
});
