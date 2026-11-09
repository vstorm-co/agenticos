import type { ComponentProps } from "react";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type { ModelProfilePicker } from "@/components/agents/model-profile-picker";
import type { ModelProfile } from "@/types/providers";
import { PipelineModelPicker } from "./pipeline-model-picker";

vi.mock("@/components/agents/model-profile-picker", () => ({
  ModelProfilePicker: ({
    allowAdd,
    disabled,
    onChange,
  }: ComponentProps<typeof ModelProfilePicker>) => (
    <button disabled={disabled} onClick={() => onChange(allowAdd ? "created" : "saved")}>
      {allowAdd ? "Create model" : "Choose saved model"}
    </button>
  ),
}));

const profile: ModelProfile = {
  id: "saved",
  label: "Support model",
  provider: "anthropic",
  model: "claude-sonnet-4-6",
  secret_id: "key",
  params: {},
  fallback_profile_ids: [],
};

describe("PipelineModelPicker", () => {
  it("offers saved models first, and closes creation after selecting the new model", async () => {
    const onChange = vi.fn();
    render(
      <PipelineModelPicker
        profiles={[profile]}
        profilesStatus="loaded"
        value={null}
        onChange={onChange}
        allowAdd
      />,
    );
    expect(screen.queryByRole("button", { name: "Create model" })).toBeNull();
    await userEvent.click(screen.getByRole("combobox", { name: "Model" }));
    await userEvent.click(screen.getByRole("option", { name: /Support model/ }));
    expect(onChange).toHaveBeenLastCalledWith("saved");
    await userEvent.click(screen.getByRole("button", { name: "Add model" }));
    await userEvent.click(screen.getByRole("button", { name: "Create model" }));
    expect(onChange).toHaveBeenLastCalledWith("created");
    expect(screen.queryByRole("button", { name: "Create model" })).toBeNull();
  });

  it("opens creation immediately on a fresh deployment", () => {
    render(
      <PipelineModelPicker
        profiles={[]}
        profilesStatus="loaded"
        value={null}
        onChange={vi.fn()}
        allowAdd
      />,
    );
    expect(screen.getByRole("button", { name: "Create model" })).toBeEnabled();
    expect(screen.queryByRole("button", { name: "Choose saved model" })).toBeNull();
  });

  it("keeps first-model creation mounted while the saved list refreshes", async () => {
    const onChange = vi.fn();
    const { rerender } = render(
      <PipelineModelPicker
        profiles={[]}
        profilesStatus="pending"
        value={null}
        onChange={onChange}
        allowAdd
      />,
    );
    rerender(
      <PipelineModelPicker
        profiles={[]}
        profilesStatus="loaded"
        value={null}
        onChange={onChange}
        allowAdd
      />,
    );
    expect(screen.getByRole("button", { name: "Create model" })).toBeEnabled();
    rerender(
      <PipelineModelPicker
        profiles={[profile]}
        profilesStatus="loaded"
        value={null}
        onChange={onChange}
        allowAdd
      />,
    );
    await userEvent.click(screen.getByRole("button", { name: "Create model" }));
    expect(onChange).toHaveBeenCalledWith("created");
    expect(screen.queryByRole("button", { name: "Create model" })).toBeNull();
  });

  it("removes model creation if permission is revoked while it is open", () => {
    const { rerender } = render(
      <PipelineModelPicker
        profiles={[]}
        profilesStatus="loaded"
        value={null}
        onChange={vi.fn()}
        allowAdd
      />,
    );
    expect(screen.getByRole("button", { name: "Create model" })).toBeEnabled();
    rerender(
      <PipelineModelPicker profiles={[]} profilesStatus="loaded" value={null} onChange={vi.fn()} />,
    );
    expect(screen.queryByRole("button", { name: "Create model" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Add model" })).toBeNull();
  });

  it("keeps failed and pending reads in the existing picker and respects disabled selection", () => {
    const { rerender } = render(
      <PipelineModelPicker
        profiles={[]}
        profilesStatus="failed"
        value={null}
        onChange={vi.fn()}
        disabled
      />,
    );
    expect(screen.getByRole("button", { name: "Choose saved model" })).toBeDisabled();
    expect(screen.queryByRole("button", { name: "Add model" })).toBeNull();
    rerender(
      <PipelineModelPicker
        profiles={[]}
        profilesStatus="pending"
        value={null}
        onChange={vi.fn()}
        allowAdd
      />,
    );
    expect(screen.queryByRole("button", { name: "Create model" })).toBeNull();
  });
});
