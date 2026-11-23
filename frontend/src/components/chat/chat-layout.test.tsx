import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";
import type { SubscriptionAccount } from "@/lib/subscription-accounts-api";
import { ChatComposerControls } from "./chat-layout";

const state = vi.hoisted(() => ({
  override: "chosen" as string | null,
  hasDefault: true,
  provider: "openai",
  model: "gpt-test",
  accounts: [] as SubscriptionAccount[],
  subscriptions: vi.fn(),
  update: vi.fn(),
}));
vi.mock("@/hooks/use-saved-chat-controls", () => ({
  useSavedChatControls: () => ({ modelProfileId: state.override, update: state.update }),
}));
vi.mock("@/hooks", () => ({
  usePermissions: () => ({ can: () => true, isLoading: false }),
  useModelProviders: () => ({
    profiles: [{ id: "chosen", provider: state.provider, model: state.model }],
    catalog: [{ id: "openai", name: "OpenAI" }],
  }),
  useProviderModels: () => ({ models: [] }),
}));
vi.mock("@/hooks/use-subscription-accounts", () => ({
  useSubscriptionAccounts: (options: { enabled: boolean }) => {
    state.subscriptions(options);
    return { accounts: { data: { items: state.accounts } } };
  },
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
vi.mock("./chat-model-picker", () => ({
  ChatModelPicker: () => (
    <>
      <p>Model catalog</p>
      <div data-model-search>
        <input aria-label="Fixture model search" />
      </div>
    </>
  ),
}));
vi.mock("@/components/icons/model-icon", () => ({ ModelIcon: () => null }));
beforeEach(() => {
  state.override = "chosen";
  state.hasDefault = true;
  state.provider = "openai";
  state.model = "gpt-test";
  state.accounts = [];
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
it("lets inline model search handle Escape before the parent picker closes", async () => {
  render(<ChatComposerControls desktop={false} harnesses={[]} />);
  await userEvent.click(screen.getByRole("button", { name: "Model" }));
  await userEvent.click(screen.getByRole("textbox", { name: "Fixture model search" }));
  await userEvent.keyboard("{Escape}");
  expect(screen.getByText("Model catalog")).toBeVisible();
  screen.getByRole("button", { name: "Close" }).focus();
  await userEvent.keyboard("{Escape}");
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

it("shows the provider alongside the model without loading personal accounts for an API model", () => {
  render(<ChatComposerControls desktop={false} harnesses={[]} />);
  expect(screen.getByRole("button", { name: "Model" })).toHaveAccessibleDescription(
    "gpt-test OpenAI",
  );
  expect(state.subscriptions).toHaveBeenCalledWith({ enabled: false });
});
it("identifies the selected subscription account without exposing its routing id", () => {
  state.provider = "subscription_accounts";
  state.model = "account-0123456789abcdef01234567/claude-sonnet-test";
  state.accounts = [
    {
      name: "other",
      model_prefix: "account-other",
      provider: "claude",
      email: "other@example.com",
      label: null,
      status: null,
      disabled: false,
      unavailable: false,
    },
    {
      name: "internal-account-name",
      model_prefix: "account-0123456789abcdef01234567",
      provider: "claude",
      email: "selected@example.com",
      label: null,
      status: null,
      disabled: false,
      unavailable: false,
    },
  ];
  render(<ChatComposerControls desktop={false} harnesses={[]} />);
  const trigger = screen.getByRole("button", { name: "Model" });
  expect(trigger).toHaveAccessibleDescription("claude-sonnet-test selected@example.com");
  expect(trigger).not.toHaveTextContent("account-");
  expect(trigger).not.toHaveTextContent("other@example.com");
  expect(state.update).not.toHaveBeenCalled();
});
it("uses a readable subscription description while account details are unavailable", () => {
  state.provider = "subscription_accounts";
  state.model = "account-0123456789abcdef01234567/gpt-test";
  render(<ChatComposerControls desktop={false} harnesses={[]} />);
  expect(screen.getByRole("button", { name: "Model" })).toHaveAccessibleDescription(
    "gpt-test Your subscriptions",
  );
});
