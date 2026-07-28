import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ChatModelPicker } from "./chat-model-picker";
import type { ProviderModel } from "@/hooks/use-model-providers";
import type { SecretPurpose } from "@/types/secrets";
import type { ModelProfile } from "@/types/providers";

const listedProfiles = vi.fn<() => ModelProfile[]>(() => []);
const listedSecrets = vi.fn<() => { id: string; purpose: string }[]>(() => []);
const listedModels = vi.fn<() => ProviderModel[]>(() => []);
const mutateAsync = vi.fn();

vi.mock("@/hooks", () => ({
  useModelProviders: () => ({
    profiles: listedProfiles(),
    createProfile: { mutateAsync, isPending: false },
  }),
  useProviderModels: () => ({ models: listedModels(), source: "curated", isLoading: false }),
  useSecretPurposes: () => ({ purposes: PURPOSES, isLoading: false }),
  useSecrets: () => ({ secrets: listedSecrets() }),
}));

const purpose = (id: string, label: string, category: SecretPurpose["category"]): SecretPurpose => ({
  id,
  label,
  category,
  kind: "api_key",
  help_url: null,
  description: "",
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
  credential_id: null,
  secret_id: "s1",
  params: {},
  allow_byo: false,
  fallback_profile_ids: [],
});

async function pickProvider(label: string) {
  await userEvent.click(screen.getByRole("combobox", { name: "Provider" }));
  await userEvent.click(screen.getByRole("option", { name: new RegExp(label) }));
}

beforeEach(() => {
  vi.clearAllMocks();
  listedProfiles.mockReturnValue([]);
  listedSecrets.mockReturnValue([]);
  listedModels.mockReturnValue([]);
});

describe("the chat's two-step model picker", () => {
  it("offers only model providers in step one, not every vault purpose", async () => {
    render(<ChatModelPicker value={null} onChange={vi.fn()} />);

    await userEvent.click(screen.getByRole("combobox", { name: "Provider" }));

    expect(screen.getByRole("option", { name: /OpenAI/ })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: /OpenRouter/ })).toBeInTheDocument();
    expect(screen.queryByRole("option", { name: /Tavily/ })).not.toBeInTheDocument();
  });

  it("keeps the model field closed until a provider is chosen", () => {
    // Step two depends on step one: a model id means nothing without knowing
    // whose catalog it names.
    render(<ChatModelPicker value={null} onChange={vi.fn()} />);

    expect(screen.getByLabelText("Model")).toBeDisabled();
  });

  it("reuses the organization's existing profile for the same provider and model", async () => {
    // The backend runs a model profile; minting a duplicate row per
    // conversation would fill the vault with copies of one fact.
    listedProfiles.mockReturnValue([profile("p1", "openai", "gpt-5")]);
    const onChange = vi.fn();
    render(<ChatModelPicker value={null} onChange={onChange} />);

    await pickProvider("OpenAI");
    await userEvent.type(screen.getByLabelText("Model"), "gpt-5");
    await userEvent.click(screen.getByRole("button", { name: "Run on this model" }));

    expect(onChange).toHaveBeenCalledWith("p1");
    expect(mutateAsync).not.toHaveBeenCalled();
  });

  it("creates a profile on the provider's vault key for a new model id", async () => {
    listedSecrets.mockReturnValue([{ id: "s-openai", purpose: "openai" }]);
    mutateAsync.mockResolvedValue(profile("p-new", "openai", "gpt-6"));
    const onChange = vi.fn();
    render(<ChatModelPicker value={null} onChange={onChange} />);

    await pickProvider("OpenAI");
    await userEvent.type(screen.getByLabelText("Model"), "gpt-6");
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
    render(<ChatModelPicker value={null} onChange={onChange} />);

    await pickProvider("OpenAI");
    await userEvent.type(screen.getByLabelText("Model"), "gpt-6");
    await userEvent.click(screen.getByRole("button", { name: "Run on this model" }));

    expect(screen.getByText(/No OpenAI key in the vault/)).toBeInTheDocument();
    expect(mutateAsync).not.toHaveBeenCalled();
    expect(onChange).not.toHaveBeenCalled();
  });

  it("will not apply a bare OpenRouter id, same rule as the Builder", async () => {
    // OpenRouter ids carry the origin - openai/gpt-5 - and the backend refuses
    // a bare one; the button says no before the server does.
    render(<ChatModelPicker value={null} onChange={vi.fn()} />);

    await pickProvider("OpenRouter");
    await userEvent.type(screen.getByLabelText("Model"), "gpt-5");

    expect(screen.getByRole("button", { name: "Run on this model" })).toBeDisabled();
  });

  it("suggests the provider's published models without constraining the field", async () => {
    listedModels.mockReturnValue([{ id: "gpt-5", name: "GPT-5" }]);
    render(<ChatModelPicker value={null} onChange={vi.fn()} />);

    await pickProvider("OpenAI");

    const input = screen.getByLabelText("Model");
    expect(input).toHaveAttribute("list", "chat-model-suggestions");
    // Free text still allowed - the list is suggestions, not a constraint.
    await userEvent.type(input, "gpt-6-preview");
    expect(input).toHaveValue("gpt-6-preview");
  });

  it("names the profile the conversation currently runs on", () => {
    listedProfiles.mockReturnValue([profile("p1", "openai", "gpt-5")]);
    render(<ChatModelPicker value="p1" onChange={vi.fn()} />);

    expect(screen.getByText("Team gpt-5")).toBeInTheDocument();
    expect(screen.getByText("openai · gpt-5")).toBeInTheDocument();
  });
});
