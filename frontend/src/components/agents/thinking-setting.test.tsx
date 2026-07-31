import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { ThinkingSetting } from "./thinking-setting";
import type { CapabilityBindingSpec, CapabilityCatalogEntry } from "@/types/agents";

const THINKING: CapabilityCatalogEntry = {
  id: "thinking",
  name: "Reasoning",
  category: "model",
  description: "How hard the model thinks before answering.",
  side_effecting: false,
  scopes: [],
  tools: [],
  contracts: [],
  config_schema: {
    type: "object",
    properties: {
      effort: { type: "string", enum: ["low", "medium", "high"], default: "medium" },
    },
  },
  requires_secret: null,
};

function binding(overrides: Partial<CapabilityBindingSpec> = {}): CapabilityBindingSpec {
  return {
    id: "thinking",
    config: {},
    approval: "default",
    tool_approval: {},
    tool_overrides: {},
    secret_id: null,
    enabled: true,
    ...overrides,
  };
}

function mount(props: Partial<Parameters<typeof ThinkingSetting>[0]> = {}) {
  const onToggle = vi.fn();
  const onChange = vi.fn();
  render(
    <ThinkingSetting
      definition={THINKING}
      binding={binding()}
      onToggle={onToggle}
      onChange={onChange}
      {...props}
    />,
  );
  return { onToggle, onChange };
}

describe("the reasoning setting", () => {
  it("renders nothing when the deployment does not register the capability", () => {
    // Say nothing rather than show an empty control: a switch for something the
    // backend cannot honour is a switch that lies.
    const { container } = render(
      <ThinkingSetting
        definition={undefined}
        binding={undefined}
        onToggle={vi.fn()}
        onChange={vi.fn()}
      />,
    );

    expect(container).toBeEmptyDOMElement();
  });

  it("names itself from the catalog rather than from hardcoded copy", () => {
    // It is the backend's capability; renaming it there must rename it here.
    mount();

    expect(screen.getByText("Reasoning")).toBeInTheDocument();
    expect(screen.getByText(/How hard the model thinks/)).toBeInTheDocument();
  });

  it("reads as off for an agent that never bound it", () => {
    mount({ binding: undefined });

    expect(screen.getByRole("switch", { name: "Reasoning" })).not.toBeChecked();
  });

  it("reads as off for a binding that is present but disabled", () => {
    // `enabled: false` is a real state - the capability is in the spec and
    // switched off - and it must not read the same as bound-and-on.
    mount({ binding: binding({ enabled: false }) });

    expect(screen.getByRole("switch", { name: "Reasoning" })).not.toBeChecked();
  });

  it("reads as on for an enabled binding", () => {
    mount();

    expect(screen.getByRole("switch", { name: "Reasoning" })).toBeChecked();
  });

  it("asks the caller to toggle rather than deciding itself", () => {
    // The spec edit belongs to `withCapability`, which is what three controls
    // share so a binding is never assembled two slightly different ways.
    const { onToggle } = mount();

    // The switch is the control; clicking it must not require a value argument.
    return userEvent.click(screen.getByRole("switch", { name: "Reasoning" })).then(() => {
      expect(onToggle).toHaveBeenCalledTimes(1);
    });
  });

  it("offers the effort settings only once it is on", () => {
    mount({ binding: binding({ enabled: false }) });

    expect(screen.queryByLabelText(/effort/i)).toBeNull();
  });

  it("shows the effort settings when it is on", () => {
    mount();

    expect(screen.getByLabelText(/effort/i)).toBeInTheDocument();
  });

  it("hides the settings when the capability declares no schema", () => {
    // Nothing to configure is not the same as a form with no fields.
    mount({ definition: { ...THINKING, config_schema: null } });

    expect(screen.queryByLabelText(/effort/i)).toBeNull();
  });

  it("carries a config edit back with the rest of the binding intact", async () => {
    // Replacing the whole binding is what the Builder's `updateCapability`
    // expects; dropping `approval` or `secret_id` here would silently reset them.
    const { onChange } = mount({ binding: binding({ secret_id: "s-1" }) });

    // A Radix select, so the trigger is opened and the option clicked - there is
    // no native <select> to set a value on.
    await userEvent.click(screen.getByLabelText(/effort/i));
    await userEvent.click(screen.getByRole("option", { name: "high" }));

    expect(onChange).toHaveBeenCalledWith(
      expect.objectContaining({ id: "thinking", secret_id: "s-1", config: { effort: "high" } }),
    );
  });

  it("cannot be switched by somebody without edit rights", () => {
    mount({ disabled: true });

    expect(screen.getByRole("switch", { name: "Reasoning" })).toBeDisabled();
  });
});
