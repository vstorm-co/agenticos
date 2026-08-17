import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ChatModelPicker } from "./chat-model-picker";
import type { ProviderModel } from "@/hooks/use-model-providers";
import { Perm } from "@/types/permissions";
import type { Permission } from "@/types/permissions";
import type { SecretPurpose } from "@/types/secrets";
import type { ModelProfile } from "@/types/providers";
import { providerMarkIn } from "@/test-utils/brand-marks";

const listedProfiles = vi.fn<() => ModelProfile[]>(() => []);
const listedSecrets = vi.fn<() => { id: string; purpose: string }[]>(() => []);
const listedModels = vi.fn<() => ProviderModel[]>(() => []);
const mutateAsync = vi.fn();
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
    createProfile: { mutateAsync, isPending: false },
  }),
  usePermissions: () => ({
    can: (permission: Permission) => held.permissions.includes(permission),
  }),
  useProviderModels: () => ({ models: listedModels(), source: "curated", isLoading: false }),
  useSecretPurposes: () => ({ purposes: PURPOSES, isLoading: false }),
  useSecrets: () => ({ secrets: listedSecrets(), create: { mutate: vi.fn(), isPending: false } }),
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
  held.permissions = [Perm.connectionsManage, Perm.secretsEdit];
});

describe("the chat's two-step model picker", () => {
  it("offers only model providers in step one, not every vault purpose", async () => {
    render(<ChatModelPicker value={null} onChange={vi.fn()} />);

    await userEvent.click(screen.getByRole("combobox", { name: "Provider" }));

    expect(screen.getByRole("option", { name: /OpenAI/ })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: /OpenRouter/ })).toBeInTheDocument();
    expect(screen.queryByRole("option", { name: /Tavily/ })).not.toBeInTheDocument();
  });

  it("draws every provider's brand mark, and carries the chosen one's into the trigger", async () => {
    // The same row the Builder draws. Radix mirrors the selected item's text
    // into the trigger, which is what makes the second half free.
    listedSecrets.mockReturnValue([{ id: "s1", purpose: "openai" }]);
    render(<ChatModelPicker value={null} onChange={vi.fn()} />);

    await pickProvider("OpenRouter");

    const trigger = screen.getByRole("combobox", { name: "Provider" });
    expect(providerMarkIn(trigger)).toBe("openrouter");
    // The tick means "this provider already has a key". Mirrored into the
    // trigger it would read as "selected", so it is not part of the row.
    expect(trigger.querySelector(".lucide-check")).toBeNull();
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

    expect(screen.getByText(/No OpenAI key in the vault yet/)).toBeInTheDocument();
    expect(mutateAsync).not.toHaveBeenCalled();
    expect(onChange).not.toHaveBeenCalled();
  });

  it("offers to add the missing key here rather than on another page", async () => {
    // A picker that can only offer what is already stored, and answers "add one in
    // the Vault" when nothing is, is a dead end - and the provider is chosen, so the
    // purpose the key needs is known.
    listedSecrets.mockReturnValue([]);
    render(<ChatModelPicker value={null} onChange={vi.fn()} />);

    await pickProvider("OpenAI");

    expect(screen.getByRole("button", { name: "Add a key: OpenAI" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Open the Vault/ })).toBeInTheDocument();
  });

  it("offers nothing once the provider has a key", async () => {
    listedSecrets.mockReturnValue([{ id: "s-1", purpose: "openai" }]);
    render(<ChatModelPicker value={null} onChange={vi.fn()} />);

    await pickProvider("OpenAI");

    expect(screen.queryByRole("button", { name: "Add a key: OpenAI" })).toBeNull();
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

describe("storing the key the chosen model runs on", () => {
  /**
   * `POST /secrets` is `secrets:edit`, which is not what lets somebody open this
   * popover - so a member who may run an agent was offered the form and refused
   * after pasting a key in (#361).
   */

  it("offers the key form to a caller who may write to the vault", async () => {
    render(<ChatModelPicker value={null} onChange={vi.fn()} />);
    await pickProvider("OpenAI");

    expect(screen.getByRole("button", { name: "Add a key: OpenAI" })).toBeInTheDocument();
  });

  it("keeps the model form and drops only the key form without secrets:edit", async () => {
    // The two are separable: `connections:manage` really does allow defining a
    // profile on a key somebody else stored, and taking the whole picker away
    // for want of `secrets:edit` would refuse something they hold.
    held.permissions = [Perm.connectionsManage];
    render(<ChatModelPicker value={null} onChange={vi.fn()} />);
    await pickProvider("OpenAI");

    expect(screen.getByRole("button", { name: "Run on this model" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Add a key: OpenAI" })).toBeNull();
    expect(screen.getByText(/permission you do not hold/)).toBeInTheDocument();
  });
});
