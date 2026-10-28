import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ChatModelPicker } from "./chat-model-picker";
import type { ProviderModel, ProfilesStatus } from "@/hooks/use-model-providers";
import { Perm } from "@/types/permissions";
import type { Permission } from "@/types/permissions";
import type { SecretPurpose } from "@/types/secrets";
import type { ModelProfile } from "@/types/providers";
import { providerMarkIn } from "@/test-utils/brand-marks";

const listedProfiles = vi.fn<() => ModelProfile[]>(() => []);
const listedSecrets = vi.fn<() => { id: string; purpose: string }[]>(() => []);
const listedModels = vi.fn<() => ProviderModel[]>(() => []);
const refusedModels = vi.fn<() => string[]>(() => []);
const loadingModels = vi.fn(() => false);
const mutateAsync = vi.fn();
const refetchProfiles = vi.fn();
const profileRead: { isLoading: boolean; profilesStatus: ProfilesStatus } = {
  isLoading: false,
  profilesStatus: "loaded",
};
/**
 * Two permissions, and this picker needs both. Choosing a model creates an
 * organization-wide profile (`connections:manage`), which is the gate on the form
 * itself; the key it runs on is a vault write (`secrets:edit`), which is the gate
 * inside `InlineSecret`. Everything below describes the form, so it holds both.
 * `chat-model-picker.integration.test.tsx` covers the outer gate against the real
 * hook.
 */
const held: { permissions: Permission[] } = { permissions: [] };

vi.mock("@/hooks", () => ({
  useModelProviders: () => ({
    profiles: listedProfiles(),
    ...profileRead,
    refetchProfiles,
    createProfile: { mutateAsync, isPending: false },
  }),
  usePermissions: () => ({
    can: (permission: Permission) => held.permissions.includes(permission),
  }),
  useProviderModels: () => ({
    models: listedModels(),
    refused: refusedModels(),
    source: "curated",
    isLoading: loadingModels(),
  }),
  useSecretPurposes: () => ({ purposes: PURPOSES, isLoading: false }),
  useSecrets: () => ({ secrets: listedSecrets(), create: { mutate: vi.fn(), isPending: false } }),
}));

// The real one signs in with ChatGPT through the vault. What is asserted here is
// only that the picker renders it in place of a key field.
vi.mock("@/components/vault/chatgpt-sign-in", () => ({
  InlineChatGPTSignIn: () => <p>ChatGPT sign-in form</p>,
}));

const purpose = (
  id: string,
  label: string,
  category: SecretPurpose["category"],
): SecretPurpose => ({
  id,
  label,
  category,
  kind: "api_key",
  help_url: null,
  description: "",
  icon: "",
});

const PURPOSES: SecretPurpose[] = [
  purpose("openai", "OpenAI", "model_provider"),
  purpose("openrouter", "OpenRouter", "model_provider"),
  purpose("tavily", "Tavily", "search"),
];

const profile = (id: string, provider: string, model: string): ModelProfile => ({
  id,
  label: `Team ${model}`,
  provider,
  model,
  secret_id: "s1",
  params: {},
  fallback_profile_ids: [],
});

function renderExpandedPicker(...args: Parameters<typeof render>) {
  const view = render(...args);
  const toggle = screen.queryByRole("button", { name: "Change model" });
  if (toggle) fireEvent.click(toggle);
  return view;
}

async function pickProvider(label: string) {
  await userEvent.click(screen.getByRole("combobox", { name: "Provider" }));
  await userEvent.click(screen.getByRole("option", { name: new RegExp(label) }));
}

/** An id the provider's catalog does not list, through the Builder's own picker. */
async function typeModel(id: string) {
  await userEvent.click(screen.getByLabelText("Model"));
  await userEvent.type(screen.getByPlaceholderText("Search models…"), id);
  await userEvent.click(screen.getByText("not in the list"));
}

beforeEach(() => {
  profileRead.isLoading = false;
  profileRead.profilesStatus = "loaded";
  refetchProfiles.mockReset();
  vi.clearAllMocks();
  listedProfiles.mockReturnValue([]);
  listedSecrets.mockReturnValue([]);
  listedModels.mockReturnValue([]);
  refusedModels.mockReturnValue([]);
  loadingModels.mockReturnValue(false);
  held.permissions = [Perm.connectionsManage, Perm.secretsEdit];
});

describe("the chat's two-step model picker", () => {
  it("offers only model providers in step one, not every vault purpose", async () => {
    renderExpandedPicker(<ChatModelPicker value={null} agentModel={null} onChange={vi.fn()} />);

    await userEvent.click(screen.getByRole("combobox", { name: "Provider" }));

    expect(screen.getByRole("option", { name: /OpenAI/ })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: /OpenRouter/ })).toBeInTheDocument();
    expect(screen.queryByRole("option", { name: /Tavily/ })).not.toBeInTheDocument();
  });

  it("draws every provider's brand mark, and carries the chosen one's into the trigger", async () => {
    // The same row the Builder draws. Radix mirrors the selected item's text
    // into the trigger, which is what makes the second half free.
    listedSecrets.mockReturnValue([{ id: "s1", purpose: "openai" }]);
    renderExpandedPicker(<ChatModelPicker value={null} agentModel={null} onChange={vi.fn()} />);

    await pickProvider("OpenRouter");

    const trigger = screen.getByRole("combobox", { name: "Provider" });
    expect(providerMarkIn(trigger)).toBe("openrouter");
    // The tick means "this provider already has a key". Mirrored into the
    // trigger it would read as "selected", so it is not part of the row.
    expect(trigger.querySelector(".lucide-check")).toBeNull();
  });

  it("prefills the agent's provider and model without creating an override", async () => {
    const onChange = vi.fn();
    renderExpandedPicker(
      <ChatModelPicker
        value={null}
        agentModel={{
          profile_id: "agent-profile",
          label: "OpenRouter · demo/model",
          provider: "openrouter",
          model: "demo/model",
        }}
        onChange={onChange}
      />,
    );
    expect(screen.getByRole("combobox", { name: "Provider" })).toHaveTextContent("OpenRouter");
    expect(screen.getByLabelText("Model")).toHaveTextContent("demo/model");
    await userEvent.click(screen.getByRole("button", { name: "Run on this model" }));
    expect(onChange).toHaveBeenCalledWith(null);
    expect(mutateAsync).not.toHaveBeenCalled();
  });

  it("prefills a conversation override that arrives after the panel mounts", () => {
    const props = { value: "selected", agentModel: null, onChange: vi.fn() };
    const { rerender } = renderExpandedPicker(<ChatModelPicker {...props} />);
    listedProfiles.mockReturnValue([profile("selected", "openai", "gpt-demo")]);
    rerender(<ChatModelPicker {...props} />);
    expect(screen.getByRole("combobox", { name: "Provider" })).toHaveTextContent("OpenAI");
    expect(screen.getByLabelText("Model")).toHaveTextContent("gpt-demo");
  });

  it("keeps a manually selected provider when the agent model arrives late", async () => {
    const { rerender } = renderExpandedPicker(
      <ChatModelPicker value={null} agentModel={null} onChange={vi.fn()} />,
    );
    await pickProvider("OpenAI");
    rerender(
      <ChatModelPicker
        value={null}
        agentModel={{
          profile_id: "agent-profile",
          label: "Agent",
          provider: "openrouter",
          model: "demo/model",
        }}
        onChange={vi.fn()}
      />,
    );
    expect(screen.getByRole("combobox", { name: "Provider" })).toHaveTextContent("OpenAI");
    expect(screen.getByLabelText("Model")).not.toHaveTextContent("demo/model");
  });

  it("keeps the model field closed until a provider is chosen", () => {
    // Step two depends on step one: a model id means nothing without knowing
    // whose catalog it names.
    renderExpandedPicker(<ChatModelPicker value={null} agentModel={null} onChange={vi.fn()} />);

    expect(screen.getByLabelText("Model")).toBeDisabled();
  });

  it("reuses the organization's existing profile for the same provider and model", async () => {
    // The backend runs a model profile; minting a duplicate row per
    // conversation would fill the vault with copies of one fact.
    listedProfiles.mockReturnValue([profile("p1", "openai", "gpt-5")]);
    const onChange = vi.fn();
    renderExpandedPicker(<ChatModelPicker value={null} agentModel={null} onChange={onChange} />);

    await pickProvider("OpenAI");
    await typeModel("gpt-5");
    await userEvent.click(screen.getByRole("button", { name: "Run on this model" }));

    expect(onChange).toHaveBeenCalledWith("p1");
    expect(mutateAsync).not.toHaveBeenCalled();
  });

  it("will not run the conversation on a saved model whose key was deleted", async () => {
    // A second profile under the same name is refused, and reusing this one
    // fails on the first turn - the answer is a key for it (#2478).
    listedProfiles.mockReturnValue([
      { ...profile("p1", "openai", "gpt-5"), secret_id: null, missing_key: true },
    ]);
    const onChange = vi.fn();
    renderExpandedPicker(<ChatModelPicker value={null} agentModel={null} onChange={onChange} />);

    await pickProvider("OpenAI");
    await typeModel("gpt-5");
    await userEvent.click(screen.getByRole("button", { name: "Run on this model" }));

    expect(screen.getByText(/gpt-5 is saved without a key/)).toBeInTheDocument();
    expect(onChange).not.toHaveBeenCalled();
    expect(mutateAsync).not.toHaveBeenCalled();
  });

  it("waits for provider metadata before reusing an unknown native profile", async () => {
    listedProfiles.mockReturnValue([profile("saved", "openrouter", "acme/painter")]);
    loadingModels.mockReturnValue(true);
    const onChange = vi.fn();
    const { rerender } = renderExpandedPicker(
      <ChatModelPicker value={null} agentModel={null} onChange={onChange} />,
    );
    await pickProvider("OpenRouter");
    await typeModel("acme/painter");
    expect(screen.getByRole("button", { name: "Run on this model" })).toBeDisabled();
    loadingModels.mockReturnValue(false);
    refusedModels.mockReturnValue(["acme/painter"]);
    rerender(<ChatModelPicker value={null} agentModel={null} onChange={onChange} />);
    await userEvent.click(screen.getByRole("button", { name: "Run on this model" }));
    expect(onChange).not.toHaveBeenCalled();
    expect(screen.getByText(/acme\/painter is not a chat model/)).toBeInTheDocument();
  });

  it("does not wait for vendor metadata for an existing custom endpoint", async () => {
    listedProfiles.mockReturnValue([
      { ...profile("local", "openai", "whisper-1"), base_url: "http://local/v1" },
    ]);
    loadingModels.mockReturnValue(true);
    const onChange = vi.fn();
    renderExpandedPicker(<ChatModelPicker value={null} agentModel={null} onChange={onChange} />);
    await pickProvider("OpenAI");
    await typeModel("whisper-1");
    await userEvent.click(screen.getByRole("button", { name: "Run on this model" }));
    expect(onChange).toHaveBeenCalledWith("local");
  });

  it.each([true, false])(
    "reuses only a custom duplicate while provider metadata is pending: native first %s",
    async (nativeFirst) => {
      const native = profile("native", "openrouter", "acme/painter");
      const custom = {
        ...profile("custom", "openrouter", "acme/painter"),
        base_url: "http://local/v1",
      };
      listedProfiles.mockReturnValue(nativeFirst ? [native, custom] : [custom, native]);
      loadingModels.mockReturnValue(true);
      const onChange = vi.fn();
      renderExpandedPicker(<ChatModelPicker value={null} agentModel={null} onChange={onChange} />);
      await pickProvider("OpenRouter");
      await typeModel("acme/painter");
      await userEvent.click(screen.getByRole("button", { name: "Run on this model" }));
      expect(onChange).toHaveBeenCalledWith("custom");
      expect(mutateAsync).not.toHaveBeenCalled();
    },
  );

  it("will not run the conversation on a speech model the organization keeps", async () => {
    // The profile exists for text to speech; reusing it would point the chat at a
    // model that cannot answer, and minting another collides on its label (#2487).
    listedProfiles.mockReturnValue([
      { ...profile("tts", "openai", "gpt-4o-mini-tts"), chat_capable: false },
    ]);
    listedSecrets.mockReturnValue([{ id: "s1", purpose: "openai" }]);
    const onChange = vi.fn();
    renderExpandedPicker(<ChatModelPicker value={null} agentModel={null} onChange={onChange} />);

    await pickProvider("OpenAI");
    await typeModel("gpt-4o-mini-tts");
    await userEvent.click(screen.getByRole("button", { name: "Run on this model" }));

    expect(
      screen.getByText(
        "gpt-4o-mini-tts is not a chat model, so this conversation cannot run on it. Choose another model.",
      ),
    ).toBeInTheDocument();
    expect(onChange).not.toHaveBeenCalled();
    expect(mutateAsync).not.toHaveBeenCalled();
  });

  it("refuses a saved profile the listing marks after the profiles loaded", async () => {
    // The profiles can arrive before the provider listing, and a profile the
    // server marked then reads as unknown; the listing that follows decides.
    listedProfiles.mockReturnValue([profile("painter", "openrouter", "acme/painter")]);
    refusedModels.mockReturnValue(["acme/painter"]);
    const onChange = vi.fn();
    renderExpandedPicker(<ChatModelPicker value={null} agentModel={null} onChange={onChange} />);

    await pickProvider("OpenRouter");
    await typeModel("acme/painter");
    await userEvent.click(screen.getByRole("button", { name: "Run on this model" }));

    expect(
      screen.getByText(
        "acme/painter is not a chat model, so this conversation cannot run on it. Choose another model.",
      ),
    ).toBeInTheDocument();
    expect(onChange).not.toHaveBeenCalled();
  });

  it("reuses a saved profile on a custom endpoint whatever the vendor listing says", async () => {
    // The listing is the provider's own API; somebody's own server is not it.
    listedProfiles.mockReturnValue([
      { ...profile("local", "openai", "whisper-1"), base_url: "http://vllm:8000/v1" },
    ]);
    refusedModels.mockReturnValue(["whisper-1"]);
    const onChange = vi.fn();
    renderExpandedPicker(<ChatModelPicker value={null} agentModel={null} onChange={onChange} />);

    await pickProvider("OpenAI");
    await typeModel("whisper-1");
    await userEvent.click(screen.getByRole("button", { name: "Run on this model" }));

    expect(onChange).toHaveBeenCalledWith("local");
  });

  it.each([false, true])(
    "prefers a compatible duplicate regardless of label order: %s",
    async (localFirst) => {
      const publicProfile = { ...profile("public", "openai", "whisper-1"), chat_capable: false };
      const local = { ...profile("local", "openai", "whisper-1"), base_url: "http://vllm:8000/v1" };
      listedProfiles.mockReturnValue(localFirst ? [local, publicProfile] : [publicProfile, local]);
      refusedModels.mockReturnValue(["whisper-1"]);
      const onChange = vi.fn();
      renderExpandedPicker(<ChatModelPicker value={null} agentModel={null} onChange={onChange} />);
      await pickProvider("OpenAI");
      await typeModel("whisper-1");
      await userEvent.click(screen.getByRole("button", { name: "Run on this model" }));
      expect(onChange).toHaveBeenCalledWith("local");
      expect(mutateAsync).not.toHaveBeenCalled();
    },
  );

  it("refuses a speech model the listing names before creating a profile for it", async () => {
    refusedModels.mockReturnValue(["gpt-4o-mini-tts"]);
    listedSecrets.mockReturnValue([{ id: "s1", purpose: "openai" }]);
    const onChange = vi.fn();
    renderExpandedPicker(<ChatModelPicker value={null} agentModel={null} onChange={onChange} />);

    await pickProvider("OpenAI");
    await typeModel("gpt-4o-mini-tts");
    await userEvent.click(screen.getByRole("button", { name: "Run on this model" }));

    expect(
      screen.getByText(
        "gpt-4o-mini-tts is not a chat model, so this conversation cannot run on it. Choose another model.",
      ),
    ).toBeInTheDocument();
    expect(mutateAsync).not.toHaveBeenCalled();
    expect(onChange).not.toHaveBeenCalled();
  });

  it("will not run the conversation on a speech model it has just added either", async () => {
    // The suggestions leave it out, but the field is free text: the server
    // classifies the profile it creates, and that answer is checked too.
    listedSecrets.mockReturnValue([{ id: "s1", purpose: "openai" }]);
    mutateAsync.mockResolvedValue({
      ...profile("tts", "openai", "gpt-4o-mini-tts"),
      chat_capable: false,
    });
    const onChange = vi.fn();
    renderExpandedPicker(<ChatModelPicker value={null} agentModel={null} onChange={onChange} />);

    await pickProvider("OpenAI");
    await typeModel("gpt-4o-mini-tts");
    await userEvent.click(screen.getByRole("button", { name: "Run on this model" }));

    expect(
      await screen.findByText(
        "gpt-4o-mini-tts is not a chat model, so this conversation cannot run on it. Choose another model.",
      ),
    ).toBeInTheDocument();
    expect(onChange).not.toHaveBeenCalled();
  });

  it("creates a profile on the provider's vault key for a new model id", async () => {
    listedSecrets.mockReturnValue([{ id: "s-openai", purpose: "openai" }]);
    mutateAsync.mockResolvedValue(profile("p-new", "openai", "gpt-6"));
    const onChange = vi.fn();
    renderExpandedPicker(<ChatModelPicker value={null} agentModel={null} onChange={onChange} />);

    await pickProvider("OpenAI");
    await typeModel("gpt-6");
    await userEvent.click(screen.getByRole("button", { name: "Run on this model" }));

    expect(mutateAsync).toHaveBeenCalledWith({
      label: "OpenAI · gpt-6",
      provider: "openai",
      model: "gpt-6",
      secret_id: "s-openai",
    });
    expect(onChange).toHaveBeenCalledWith("p-new");
  });

  it("refuses a provider with no key in the vault, and says where to add one", async () => {
    // A model with no key is a model that cannot answer; the refusal belongs
    // here, not after the first message fails.
    const onChange = vi.fn();
    renderExpandedPicker(<ChatModelPicker value={null} agentModel={null} onChange={onChange} />);

    await pickProvider("OpenAI");
    await typeModel("gpt-6");
    await userEvent.click(screen.getByRole("button", { name: "Run on this model" }));

    expect(screen.getByText(/No OpenAI key in the vault yet/)).toBeInTheDocument();
    expect(mutateAsync).not.toHaveBeenCalled();
    expect(onChange).not.toHaveBeenCalled();
  });

  it("offers to add the missing key here rather than on another page", async () => {
    // A picker that can only offer what is already stored, and answers "add one in
    // the Vault" when nothing is, is a dead end - and the provider is chosen, so the
    // purpose the key needs is known.
    listedSecrets.mockReturnValue([]);
    renderExpandedPicker(<ChatModelPicker value={null} agentModel={null} onChange={vi.fn()} />);

    await pickProvider("OpenAI");

    expect(screen.getByRole("button", { name: "Add a key: OpenAI" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Open the Vault/ })).toBeInTheDocument();
  });

  it("offers a ChatGPT sign-in, not a key field, for a subscription", async () => {
    // There is no key to paste: the credential is an OAuth grant.
    PURPOSES.push({
      ...purpose("openai_codex", "ChatGPT (Codex subscription)", "model_provider"),
      kind: "openai_codex",
    });
    try {
      renderExpandedPicker(<ChatModelPicker value={null} agentModel={null} onChange={vi.fn()} />);

      await pickProvider("ChatGPT");

      expect(screen.getByText("ChatGPT sign-in form")).toBeInTheDocument();
      expect(screen.queryByRole("button", { name: /Add a key/ })).toBeNull();
    } finally {
      PURPOSES.pop();
    }
  });

  it("offers nothing once the provider has a key", async () => {
    listedSecrets.mockReturnValue([{ id: "s-1", purpose: "openai" }]);
    renderExpandedPicker(<ChatModelPicker value={null} agentModel={null} onChange={vi.fn()} />);

    await pickProvider("OpenAI");

    expect(screen.queryByRole("button", { name: "Add a key: OpenAI" })).toBeNull();
  });

  it("will not apply a bare OpenRouter id, same rule as the Builder", async () => {
    // OpenRouter ids carry the origin - openai/gpt-5 - and the backend refuses
    // a bare one; the button says no before the server does.
    renderExpandedPicker(<ChatModelPicker value={null} agentModel={null} onChange={vi.fn()} />);

    await pickProvider("OpenRouter");
    await typeModel("gpt-5");

    expect(screen.getByRole("button", { name: "Run on this model" })).toBeDisabled();
  });

  it("offers the provider's published models, and still takes one it does not list", async () => {
    listedModels.mockReturnValue([{ id: "gpt-5", name: "GPT-5" }]);
    renderExpandedPicker(<ChatModelPicker value={null} agentModel={null} onChange={vi.fn()} />);

    await pickProvider("OpenAI");
    await userEvent.click(screen.getByLabelText("Model"));
    expect(screen.getByText("GPT-5")).toBeInTheDocument();

    // Free text still allowed - the list is suggestions, not a constraint.
    await userEvent.type(screen.getByPlaceholderText("Search models…"), "gpt-6-preview");
    await userEvent.click(screen.getByText("not in the list"));
    expect(screen.getByLabelText("Model")).toHaveTextContent("gpt-6-preview");
  });

  it("names the profile the conversation currently runs on", () => {
    listedProfiles.mockReturnValue([profile("p1", "openai", "gpt-5")]);
    renderExpandedPicker(
      <ChatModelPicker
        value="p1"
        agentModel={{ profile_id: "ap", provider: "anthropic", model: "claude", label: "Agent" }}
        onChange={vi.fn()}
      />,
    );

    expect(screen.getByText("Team gpt-5")).toBeInTheDocument();
    expect(screen.getByText("openai · gpt-5")).toBeInTheDocument();
    expect(screen.getByText("Just this chat")).toBeInTheDocument();
    expect(screen.queryByText("Agent")).not.toBeInTheDocument();
  });

  it("shows the agent's own model when there is no override", () => {
    renderExpandedPicker(
      <ChatModelPicker
        value={null}
        agentModel={{
          profile_id: "ap",
          provider: "anthropic",
          model: "claude-sonnet-4-5",
          label: "Claude Sonnet",
        }}
        onChange={vi.fn()}
      />,
    );

    expect(screen.getByText("Claude Sonnet")).toBeInTheDocument();
    expect(screen.getByText("anthropic · claude-sonnet-4-5")).toBeInTheDocument();
    expect(screen.getByText("Agent's model")).toBeInTheDocument();
  });

  it("shows the model to a caller who may not change it, and withholds only the fields", () => {
    // Reading which model the conversation runs on is agents:view, not
    // connections:manage - the person who may not change it most wants to know.
    held.permissions = [];
    renderExpandedPicker(
      <ChatModelPicker
        value={null}
        agentModel={{
          profile_id: "ap",
          provider: "anthropic",
          model: "claude-sonnet-4-5",
          label: "Claude Sonnet",
        }}
        onChange={vi.fn()}
      />,
    );

    expect(screen.getByText("Claude Sonnet")).toBeInTheDocument();
    expect(screen.getByText(/permission you do not hold/)).toBeInTheDocument();
    expect(screen.queryByRole("combobox", { name: "Provider" })).toBeNull();
  });
});

describe("storing the key the chosen model runs on", () => {
  /**
   * `POST /secrets` is `secrets:edit`, which is not what lets somebody open this
   * popover - so a member who may run an agent was offered the form and refused
   * after pasting a key in (#361).
   */

  it("offers the key form to a caller who may write to the vault", async () => {
    renderExpandedPicker(<ChatModelPicker value={null} agentModel={null} onChange={vi.fn()} />);
    await pickProvider("OpenAI");

    expect(screen.getByRole("button", { name: "Add a key: OpenAI" })).toBeInTheDocument();
  });

  it("keeps the model form and drops only the key form without secrets:edit", async () => {
    // The two are separable: `connections:manage` really does allow defining a
    // profile on a key somebody else stored, and taking the whole picker away
    // for want of `secrets:edit` would refuse something they hold.
    held.permissions = [Perm.connectionsManage];
    renderExpandedPicker(<ChatModelPicker value={null} agentModel={null} onChange={vi.fn()} />);
    await pickProvider("OpenAI");

    expect(screen.getByRole("button", { name: "Run on this model" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Add a key: OpenAI" })).toBeNull();
    expect(screen.getByText(/permission you do not hold/)).toBeInTheDocument();
  });
});

it("shows the current model and keeps changes collapsed until requested", async () => {
  render(
    <ChatModelPicker
      value={null}
      agentModel={{
        profile_id: "agent-profile",
        label: "OpenRouter · demo/model",
        provider: "openrouter",
        model: "demo/model",
      }}
      onChange={vi.fn()}
    />,
  );
  expect(screen.getByText("OpenRouter · demo/model")).toBeInTheDocument();
  const toggle = screen.getByRole("button", { name: "Change model" });
  expect(toggle).toHaveAttribute("aria-expanded", "false");
  expect(screen.queryByRole("combobox", { name: "Provider" })).not.toBeInTheDocument();
  await userEvent.click(toggle);
  expect(screen.getByRole("combobox", { name: "Provider" })).toHaveTextContent("OpenRouter");
  await userEvent.click(toggle);
  expect(screen.queryByLabelText("Model")).not.toBeInTheDocument();
  expect(screen.getByText("OpenRouter · demo/model")).toBeInTheDocument();
});

it("keeps the current regional endpoint and key when another model is selected", async () => {
  const regional = {
    ...profile("regional", "openrouter", "vendor/original"),
    base_url: "https://eu.openrouter.ai/api/v1",
    secret_id: "eu-key",
  };
  listedProfiles.mockReturnValue([profile("global", "openrouter", "vendor/next"), regional]);
  listedSecrets.mockReturnValue([
    { id: "global-key", purpose: "openrouter" },
    { id: "eu-key", purpose: "openrouter" },
  ]);
  mutateAsync.mockResolvedValue({ ...regional, id: "regional-next", model: "vendor/next" });
  const onChange = vi.fn();
  renderExpandedPicker(<ChatModelPicker value="regional" agentModel={null} onChange={onChange} />);
  await typeModel("vendor/next");
  await userEvent.click(screen.getByRole("button", { name: "Run on this model" }));
  expect(mutateAsync).toHaveBeenCalledWith(
    expect.objectContaining({
      provider: "openrouter",
      model: "vendor/next",
      base_url: regional.base_url,
      secret_id: "eu-key",
    }),
  );
  expect(onChange).toHaveBeenCalledWith("regional-next");
});

it("requires a successful profile read before creating a replacement model", async () => {
  profileRead.profilesStatus = "failed";
  renderExpandedPicker(<ChatModelPicker value={null} agentModel={null} onChange={vi.fn()} />);
  expect(screen.getByRole("alert")).toHaveTextContent("Model settings could not be read");
  await userEvent.click(screen.getByRole("button", { name: "Retry" }));
  expect(refetchProfiles).toHaveBeenCalledOnce();
  expect(screen.getByRole("button", { name: "Run on this model" })).toBeDisabled();
});

it("does not bypass missing-key checks for the prefilled current model", async () => {
  listedProfiles.mockReturnValue([
    { ...profile("missing", "openrouter", "vendor/model"), secret_id: null, missing_key: true },
  ]);
  const onChange = vi.fn();
  renderExpandedPicker(<ChatModelPicker value="missing" agentModel={null} onChange={onChange} />);
  await userEvent.click(screen.getByRole("button", { name: "Run on this model" }));
  expect(screen.getByText(/vendor\/model is saved without a key/)).toBeInTheDocument();
  expect(onChange).not.toHaveBeenCalled();
});
