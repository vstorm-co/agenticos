import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";
import { ChatComposerControls } from "./chat-layout";

const state = vi.hoisted(() => ({
  override: "chosen" as string | null,
  hasDefault: true,
  update: vi.fn(),
}));
vi.mock("@/hooks/use-saved-chat-controls", () => ({
  useSavedChatControls: () => ({ modelProfileId: state.override, update: state.update }),
}));
vi.mock("@/hooks", () => ({
  usePermissions: () => ({ can: () => true, isLoading: false }),
  useModelProviders: () => ({
    profiles: [{ id: "chosen", provider: "openai", model: "gpt-test" }],
  }),
  useProviderModels: () => ({ models: [] }),
}));
vi.mock("@/hooks/use-agents", () => ({
  useAgents: () => ({
    agents: [
      {
        id: "agent",
        published_model: state.hasDefault ? { provider: "anthropic", model: "claude-test" } : null,
      },
    ],
  }),
}));
vi.mock("@/stores", () => ({
  useAgentSelectionStore: (select: (value: { selectedAgentId: string }) => unknown) =>
    select({ selectedAgentId: "agent" }),
}));
vi.mock("./chat-model-picker", () => ({ ChatModelPicker: () => <p>Model catalog</p> }));
vi.mock("@/components/icons/model-icon", () => ({ ModelIcon: () => null }));
beforeEach(() => {
  state.override = "chosen";
  state.hasDefault = true;
  vi.clearAllMocks();
});
it("restores the agent model, persists the cleared override and closes the picker", async () => {
  const onChange = vi.fn();
  render(<ChatComposerControls desktop={false} harnesses={[]} onModelProfileChange={onChange} />);
  await userEvent.click(screen.getByRole("button", { name: "Model" }));
  const restore = screen.getByRole("button", { name: "Back to the agent's own model" });
  expect(
    restore.compareDocumentPosition(screen.getByText("Model catalog")) &
      Node.DOCUMENT_POSITION_FOLLOWING,
  ).toBeTruthy();
  await userEvent.click(restore);
  expect(state.update).toHaveBeenCalledWith({ modelProfileId: null });
  expect(onChange).toHaveBeenCalledWith(null);
  expect(screen.queryByText("Model catalog")).not.toBeInTheDocument();
});
it.each(["no override", "no agent model"])(
  "does not offer an ineffective restore: %s",
  async (reason) => {
    if (reason === "no override") state.override = null;
    else state.hasDefault = false;
    render(<ChatComposerControls desktop={false} harnesses={[]} />);
    await userEvent.click(screen.getByRole("button", { name: "Model" }));
    expect(
      screen.queryByRole("button", { name: "Back to the agent's own model" }),
    ).not.toBeInTheDocument();
  },
);
