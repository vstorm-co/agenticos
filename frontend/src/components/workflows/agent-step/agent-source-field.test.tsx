import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { AgentSpec, CapabilityBindingSpec } from "@/types/agents";

import { AgentSourceField, blankSpec } from "./agent-source-field";

const state = vi.hoisted(() => ({
  version: undefined as { spec: Record<string, unknown> } | undefined,
  create: vi.fn(),
  pending: false,
}));
const toast = vi.hoisted(() => ({ success: vi.fn(), error: vi.fn() }));

vi.mock("sonner", () => ({ toast }));
vi.mock("@/hooks", () => ({
  useAgentVersion: () => ({ version: state.version }),
  useModelProviders: () => ({ profiles: [{ id: "m1", label: "Claude Sonnet" }] }),
  useAgents: () => ({ create: { mutateAsync: state.create, isPending: state.pending } }),
}));
vi.mock("@/components/workflows/pickers/agent-version-picker", () => ({
  AgentVersionPicker: ({
    value,
    error,
    onChange,
  }: {
    value: { agent_id: string | null };
    error?: string;
    onChange: (next: unknown) => void;
  }) => (
    <div>
      <span>{`picker:${value.agent_id}:${error ?? ""}`}</span>
      <button
        type="button"
        aria-label="pin"
        onClick={() => onChange({ agent_id: "a1", version_id: "v1" })}
      />
    </div>
  ),
}));
vi.mock("./inline-agent-dialog", () => ({
  InlineAgentDialog: ({
    open,
    onSave,
    onOpenChange,
  }: {
    open: boolean;
    onSave: (spec: AgentSpec) => void;
    onOpenChange: (open: boolean) => void;
  }) =>
    open ? (
      <div role="dialog">
        <button type="button" onClick={() => onSave({ ...blankSpec("Edited") })}>
          apply
        </button>
        <button type="button" onClick={() => onOpenChange(false)}>
          close
        </button>
      </div>
    ) : null,
}));

const scorer: AgentSpec = {
  ...blankSpec("Lead scorer"),
  model_profile_id: "m1",
  instructions: "Score the lead.",
  capabilities: [{ id: "clock" } as CapabilityBindingSpec],
};

function renderField(config: Record<string, unknown>, error?: string) {
  const onChange = vi.fn();
  render(
    <AgentSourceField config={config} stepName="Score lead" error={error} onChange={onChange} />,
  );
  return onChange;
}

beforeEach(() => {
  state.version = undefined;
  state.create.mockReset();
  state.pending = false;
  toast.success.mockReset();
  toast.error.mockReset();
});

describe("AgentSourceField", () => {
  it("pins a catalog agent and keeps the step's other settings", async () => {
    const onChange = renderField({ agent: null, max_cost_usd: 1 }, "Pick an agent");

    expect(screen.getByText("picker:null:Pick an agent")).toBeVisible();
    await userEvent.click(screen.getByRole("button", { name: "pin" }));

    expect(onChange).toHaveBeenLastCalledWith({
      max_cost_usd: 1,
      agent: { agent_id: "a1", version_id: "v1" },
    });
  });

  it("switching to configure here starts a blank agent named for the step", async () => {
    const onChange = renderField({ agent: { agent_id: "a1", version_id: "v1" } });

    await userEvent.click(screen.getByRole("tab", { name: "Configure here" }));

    expect(onChange).toHaveBeenLastCalledWith({ inline: blankSpec("Score lead") });
  });

  it("switching back to the catalog drops the configured agent", async () => {
    const onChange = renderField({ inline: scorer });

    await userEvent.click(screen.getByRole("tab", { name: "Agent from the catalog" }));

    expect(onChange).toHaveBeenLastCalledWith({ agent: { agent_id: null, version_id: null } });
  });

  it("copies a pinned agent's configuration into the step to adjust it", async () => {
    state.version = { spec: { ...scorer } };
    const onChange = renderField({ agent: { agent_id: "a1", version_id: "v1" } });

    await userEvent.click(
      screen.getByRole("button", { name: "Copy its configuration into this step" }),
    );

    expect(onChange).toHaveBeenLastCalledWith({ inline: scorer });
  });

  it("shows an agent configured here at a glance, with what stops it publishing", () => {
    renderField({ inline: scorer }, "No model selected");

    expect(screen.getByText("Lead scorer")).toBeVisible();
    expect(screen.getByText(/Claude Sonnet · 1 capability, no MCP servers/)).toBeVisible();
    expect(screen.getByText("Score the lead.")).toBeVisible();
    expect(screen.getByText("No model selected")).toBeVisible();
  });

  it("an agent with no model or instructions says so rather than showing blanks", () => {
    renderField({ inline: blankSpec("Fresh") });

    expect(screen.getByText(/No model chosen · no capabilities, no MCP servers/)).toBeVisible();
    expect(screen.queryByText("Score the lead.")).toBeNull();
  });

  it("configures the agent in its dialog and writes what was applied", async () => {
    const onChange = renderField({ inline: scorer, max_cost_usd: 2 });

    await userEvent.click(screen.getByRole("button", { name: "Configure" }));
    await userEvent.click(screen.getByRole("button", { name: "apply" }));

    expect(onChange).toHaveBeenLastCalledWith({ max_cost_usd: 2, inline: blankSpec("Edited") });
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("closing the dialog changes nothing", async () => {
    const onChange = renderField({ inline: scorer });

    await userEvent.click(screen.getByRole("button", { name: "Configure" }));
    await userEvent.click(screen.getByRole("button", { name: "close" }));

    expect(onChange).not.toHaveBeenCalled();
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("saves an agent configured here to the catalog as a draft", async () => {
    state.create.mockResolvedValue({ id: "new", name: "Lead scorer" });
    renderField({ inline: scorer });

    await userEvent.click(screen.getByRole("button", { name: "Save as an agent" }));

    expect(state.create).toHaveBeenCalledWith({ spec: scorer });
    expect(toast.success).toHaveBeenCalledWith(
      "Lead scorer is a draft in Agents. Publish it to pick it in a step.",
      expect.anything(),
    );
  });

  it("a save the server refuses is said, not swallowed", async () => {
    state.create.mockRejectedValue(new Error("boom"));
    renderField({ inline: scorer });

    await userEvent.click(screen.getByRole("button", { name: "Save as an agent" }));

    expect(toast.error).toHaveBeenCalled();
  });
});
