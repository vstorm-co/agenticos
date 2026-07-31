import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AddModel } from "./add-model";
import type { SecretPurpose } from "@/types/secrets";

/**
 * Adding a model: a provider, a model id, and which stored key pays for it.
 *
 * The pure helpers - `modelPlaceholder`, `modelHint`, `modelIdIsWellFormed` -
 * already have unit tests in `add-model.test.tsx`. What is asserted here is the
 * form around them, where the rules that matter live: no key means no model, one
 * key needs no question, and the key is chosen from the vault rather than typed.
 */

interface Secret {
  id: string;
  name: string;
  hint: string;
  purpose: string | null;
  kind: string;
}

/** One entry of the provider catalog, which is where the two capability flags live. */
interface ProviderCapabilities {
  id: string;
  name: string;
  secret_kind: string;
  supports_base_url: boolean;
  keyless: boolean;
}

const state = {
  purposes: [] as SecretPurpose[],
  catalog: [] as ProviderCapabilities[],
  secrets: [] as Secret[],
  models: [] as { id: string; name: string; context_length?: number | null }[],
  source: "live" as "live" | "curated" | null,
  loadingModels: false,
  createProfile: { mutateAsync: vi.fn(), isPending: false },
};

const onCreatedSecret = { handler: undefined as ((id: string) => void) | undefined };

vi.mock("@/hooks", () => ({
  useModelProviders: () => ({ createProfile: state.createProfile, catalog: state.catalog }),
  useSecretPurposes: () => ({ purposes: state.purposes }),
  useSecrets: () => ({ secrets: state.secrets }),
  useProviderModels: () => ({
    models: state.models,
    source: state.source,
    isLoading: state.loadingModels,
  }),
}));

// The real one posts to the vault. What this form needs from it is the callback
// that hands back a new secret id.
vi.mock("@/components/vault/inline-secret", () => ({
  InlineSecret: ({ onCreated }: { onCreated: (id: string) => void }) => {
    onCreatedSecret.handler = onCreated;
    return (
      <button type="button" onClick={() => onCreated("s-new")}>
        Store a key
      </button>
    );
  },
}));

function purpose(id: string, label: string): SecretPurpose {
  return {
    id,
    label,
    category: "model_provider",
    kind: "api_key",
    help_url: null,
    description: `${label} keys`,
  };
}

function secret(overrides: Partial<Secret> = {}): Secret {
  return {
    id: "s-1",
    name: "OpenAI prod",
    hint: "3123",
    purpose: "openai",
    kind: "api_key",
    ...overrides,
  };
}

function capabilities(
  id: string,
  name: string,
  overrides: Partial<ProviderCapabilities> = {},
): ProviderCapabilities {
  return {
    id,
    name,
    secret_kind: "api_key",
    supports_base_url: false,
    keyless: false,
    ...overrides,
  };
}

beforeEach(() => {
  state.purposes = [purpose("openai", "OpenAI"), purpose("openrouter", "OpenRouter")];
  // What each provider's SDK actually reads. `openai` takes an endpoint and is
  // keyless, because OpenAI-compatible servers exist; `openrouter` takes neither.
  state.catalog = [
    capabilities("openai", "OpenAI", { supports_base_url: true, keyless: true }),
    capabilities("openrouter", "OpenRouter"),
  ];
  state.secrets = [];
  state.models = [{ id: "gpt-5", name: "GPT-5", context_length: 400_000 }];
  state.source = "live";
  state.loadingModels = false;
  state.createProfile = { mutateAsync: vi.fn().mockResolvedValue({ id: "p-1" }), isPending: false };
  onCreatedSecret.handler = undefined;
});

function mount(props: Partial<Parameters<typeof AddModel>[0]> = {}) {
  const onCreated = vi.fn();
  render(<AddModel onCreated={onCreated} {...props} />);
  return { onCreated };
}

async function pickProvider(label: string) {
  await userEvent.click(screen.getByLabelText("Provider"));
  await userEvent.click(screen.getByRole("option", { name: new RegExp(label) }));
}

describe("the add-model form", () => {
  it("offers only providers, not every purpose in the vault", () => {
    // A Tavily key is a key, but it is not a model provider and picking it here
    // would produce a profile that cannot answer.
    state.purposes = [
      purpose("openai", "OpenAI"),
      { ...purpose("tavily", "Tavily"), category: "search" },
    ];
    mount();

    return userEvent.click(screen.getByLabelText("Provider")).then(() => {
      expect(screen.getByRole("option", { name: /OpenAI/ })).toBeInTheDocument();
      expect(screen.queryByRole("option", { name: /Tavily/ })).toBeNull();
    });
  });

  it("offers every provider, including ones with no key yet", () => {
    // Being told "no key yet" and handed a field is the answer to "can we use
    // OpenRouter?" - sending somebody to another page is the flow this replaces.
    mount();

    return userEvent.click(screen.getByLabelText("Provider")).then(() => {
      expect(screen.getByRole("option", { name: /OpenRouter/ })).toBeInTheDocument();
    });
  });

  it("marks the providers a key is already stored for", async () => {
    state.secrets = [secret()];
    mount();

    await userEvent.click(screen.getByLabelText("Provider"));

    // The tick is decorative; what matters is that both are offered and the
    // keyed one is distinguishable at all.
    expect(screen.getByRole("option", { name: /OpenAI/ })).toBeInTheDocument();
  });

  it("cannot be submitted before a provider is chosen", () => {
    mount();

    expect(screen.getByRole("button", { name: "Add model" })).toBeDisabled();
    expect(screen.getByLabelText("Model")).toBeDisabled();
  });

  it("cannot be submitted with no key stored for the provider", async () => {
    mount();
    await pickProvider("OpenAI");

    await userEvent.click(screen.getByLabelText("Model"));
    await userEvent.click(screen.getByRole("option", { name: /gpt-5/ }));

    expect(screen.getByRole("button", { name: "Add model" })).toBeDisabled();
    expect(screen.getByText(/No OpenAI key in the vault yet/)).toBeInTheDocument();
  });

  it("asks no question when there is exactly one key", async () => {
    // A select with a single option is a decision about nothing.
    state.secrets = [secret()];
    mount();
    await pickProvider("OpenAI");

    expect(screen.queryByLabelText("Key")).toBeNull();
    expect(screen.getByText(/Using/)).toBeInTheDocument();
    expect(screen.getByText("OpenAI prod")).toBeInTheDocument();
  });

  it("asks which key once there is more than one", async () => {
    state.secrets = [secret(), secret({ id: "s-2", name: "OpenAI staging", hint: "9999" })];
    mount();
    await pickProvider("OpenAI");

    expect(screen.getByLabelText("Key")).toBeInTheDocument();
  });

  it("uses the first key by default and the chosen one after that", async () => {
    state.secrets = [secret(), secret({ id: "s-2", name: "OpenAI staging", hint: "9999" })];
    mount();
    await pickProvider("OpenAI");

    await userEvent.click(screen.getByLabelText("Model"));
    await userEvent.click(screen.getByRole("option", { name: /gpt-5/ }));
    await userEvent.click(screen.getByLabelText("Key"));
    await userEvent.click(screen.getByRole("option", { name: /OpenAI staging/ }));
    await userEvent.click(screen.getByRole("button", { name: "Add model" }));

    expect(state.createProfile.mutateAsync).toHaveBeenCalledWith(
      expect.objectContaining({ secret_id: "s-2" }),
    );
  });

  it("only counts keys stored for the provider that was chosen", async () => {
    // A secret's purpose *is* the provider id, which is what makes this a lookup
    // rather than a convention.
    state.secrets = [secret({ purpose: "openrouter", name: "OpenRouter prod" })];
    mount();
    await pickProvider("OpenAI");

    expect(screen.getByText(/No OpenAI key in the vault yet/)).toBeInTheDocument();
  });

  it("takes a key stored inline and uses it", async () => {
    mount();
    await pickProvider("OpenAI");

    await userEvent.click(screen.getByRole("button", { name: "Store a key" }));
    await userEvent.click(screen.getByLabelText("Model"));
    await userEvent.click(screen.getByRole("option", { name: /gpt-5/ }));

    expect(screen.getByRole("button", { name: "Add model" })).toBeEnabled();
  });

  it("refuses a bare model id for a provider that namespaces them", async () => {
    // OpenRouter routes to other people's models, so its ids carry the origin.
    // The backend refuses a bare one; saying so before the request is the point.
    state.secrets = [secret({ purpose: "openrouter" })];
    state.models = [];
    mount();
    await pickProvider("OpenRouter");

    await userEvent.click(screen.getByLabelText("Model"));
    await userEvent.type(screen.getByPlaceholderText("Search models…"), "gpt-5");
    await userEvent.click(screen.getByText("not in the list"));

    expect(screen.getByRole("button", { name: "Add model" })).toBeDisabled();
  });

  it("accepts a namespaced id for that provider", async () => {
    state.secrets = [secret({ purpose: "openrouter" })];
    state.models = [];
    mount();
    await pickProvider("OpenRouter");

    await userEvent.click(screen.getByLabelText("Model"));
    await userEvent.type(screen.getByPlaceholderText("Search models…"), "openai/gpt-5");
    await userEvent.click(screen.getByText("not in the list"));

    expect(screen.getByRole("button", { name: "Add model" })).toBeEnabled();
  });

  it("derives a name so nobody has to invent one", async () => {
    state.secrets = [secret()];
    mount();
    await pickProvider("OpenAI");
    await userEvent.click(screen.getByLabelText("Model"));
    await userEvent.click(screen.getByRole("option", { name: /gpt-5/ }));

    await userEvent.click(screen.getByRole("button", { name: "Add model" }));

    expect(state.createProfile.mutateAsync).toHaveBeenCalledWith(
      expect.objectContaining({ label: "OpenAI · gpt-5", provider: "openai", model: "gpt-5" }),
    );
  });

  it("takes a name somebody typed instead", async () => {
    // What lets an organization run the same model twice under two keys and tell
    // them apart.
    state.secrets = [secret()];
    mount();
    await pickProvider("OpenAI");
    await userEvent.click(screen.getByLabelText("Model"));
    await userEvent.click(screen.getByRole("option", { name: /gpt-5/ }));

    await userEvent.click(screen.getByRole("button", { name: "Name it something else" }));
    await userEvent.type(screen.getByLabelText("Name"), "Cheap tier");
    await userEvent.click(screen.getByRole("button", { name: "Add model" }));

    expect(state.createProfile.mutateAsync).toHaveBeenCalledWith(
      expect.objectContaining({ label: "Cheap tier" }),
    );
  });

  it("hands the new profile to the caller so it can be selected", async () => {
    state.secrets = [secret()];
    const { onCreated } = mount();
    await pickProvider("OpenAI");
    await userEvent.click(screen.getByLabelText("Model"));
    await userEvent.click(screen.getByRole("option", { name: /gpt-5/ }));

    await userEvent.click(screen.getByRole("button", { name: "Add model" }));

    expect(onCreated).toHaveBeenCalledWith({ id: "p-1" });
  });

  it("puts a refusal under the field that caused it", async () => {
    // Every refusal this endpoint gives is about the model id, and an unhandled
    // rejection here is Next's full-screen overlay for what is a typo.
    state.secrets = [secret()];
    state.createProfile = {
      mutateAsync: vi.fn().mockRejectedValue(new Error("model not found")),
      isPending: false,
    };
    const { onCreated } = mount();
    await pickProvider("OpenAI");
    await userEvent.click(screen.getByLabelText("Model"));
    await userEvent.click(screen.getByRole("option", { name: /gpt-5/ }));

    await userEvent.click(screen.getByRole("button", { name: "Add model" }));

    expect(screen.getByText("model not found")).toBeInTheDocument();
    expect(onCreated).not.toHaveBeenCalled();
  });

  it("clears the model and key when the provider changes", async () => {
    // A model id from another provider is a profile that cannot run.
    state.secrets = [secret(), secret({ id: "s-2", purpose: "openrouter" })];
    mount();
    await pickProvider("OpenAI");
    await userEvent.click(screen.getByLabelText("Model"));
    await userEvent.click(screen.getByRole("option", { name: /gpt-5/ }));

    await pickProvider("OpenRouter");

    expect(screen.getByRole("button", { name: "Add model" })).toBeDisabled();
  });

  it("stops a second submission while one is in flight", async () => {
    state.secrets = [secret()];
    state.createProfile = { mutateAsync: vi.fn(), isPending: true };
    mount();
    await pickProvider("OpenAI");

    expect(screen.getByRole("button", { name: "Add model" })).toBeDisabled();
  });

  it("offers a way out only when the caller gives one", async () => {
    const onCancel = vi.fn();
    mount({ onCancel });

    await userEvent.click(screen.getByRole("button", { name: "Cancel" }));

    expect(onCancel).toHaveBeenCalled();
  });

  it("shows no Cancel when the form is the panel rather than a state of it", () => {
    mount();

    expect(screen.queryByRole("button", { name: "Cancel" })).toBeNull();
  });

  it("cannot be used at all when the caller disables it", async () => {
    state.secrets = [secret()];
    mount({ disabled: true });
    await pickProvider("OpenAI");
    await userEvent.click(screen.getByLabelText("Model"));
    await userEvent.click(screen.getByRole("option", { name: /gpt-5/ }));

    expect(screen.getByRole("button", { name: "Add model" })).toBeDisabled();
  });
});

describe("pointing a model somewhere other than the provider's own API", () => {
  /**
   * The feature existed in pieces and was reachable from nowhere: the catalog said
   * which providers accept an endpoint, the service validated one, the resolver
   * knew how to pass one to the SDK - and this form never asked. So Ollama and a
   * LiteLLM proxy were documented providers nobody could configure.
   *
   * Both rules below are the API's. A form that guesses differently offers a
   * submit the API refuses, which is the worst of both.
   */

  it("offers an endpoint only where the SDK reads one", async () => {
    mount();
    await pickProvider("OpenAI");
    expect(screen.getByLabelText("Endpoint")).toBeInTheDocument();
  });

  it("offers none for a provider that would ignore it", async () => {
    // Storing one would look configured and change nothing about where the
    // request went, which is worse than not offering it at all.
    mount();
    await pickProvider("OpenRouter");
    expect(screen.queryByLabelText("Endpoint")).toBeNull();
  });

  it("sends the endpoint with the profile", async () => {
    state.secrets = [secret()];
    mount();
    await pickProvider("OpenAI");
    await userEvent.click(screen.getByLabelText("Model"));
    await userEvent.click(screen.getByRole("option", { name: /gpt-5/ }));
    await userEvent.type(screen.getByLabelText("Endpoint"), "https://gateway.acme/v1");
    await userEvent.click(screen.getByRole("button", { name: "Add model" }));

    expect(state.createProfile.mutateAsync).toHaveBeenCalledWith(
      expect.objectContaining({ base_url: "https://gateway.acme/v1" }),
    );
  });

  it("sends null when it was left empty, not an empty string", async () => {
    // The API distinguishes "the provider's own API" from a field somebody
    // cleared, and "" is neither of those things.
    state.secrets = [secret()];
    mount();
    await pickProvider("OpenAI");
    await userEvent.click(screen.getByLabelText("Model"));
    await userEvent.click(screen.getByRole("option", { name: /gpt-5/ }));
    await userEvent.click(screen.getByRole("button", { name: "Add model" }));

    expect(state.createProfile.mutateAsync).toHaveBeenCalledWith(
      expect.objectContaining({ base_url: null }),
    );
  });

  it("lets a keyless provider be submitted with an endpoint and no key", async () => {
    // The case the whole feature is for. There is no Ollama key in the vault and
    // there should not need to be: a model server on this network authenticates
    // nothing.
    state.purposes = [...state.purposes, purpose("ollama", "Ollama")];
    state.catalog = [
      ...state.catalog,
      capabilities("ollama", "Ollama", { supports_base_url: true, keyless: true }),
    ];
    mount();
    await pickProvider("Ollama");
    await userEvent.click(screen.getByLabelText("Model"));
    await userEvent.click(screen.getByRole("option", { name: /gpt-5/ }));
    await userEvent.type(screen.getByLabelText("Endpoint"), "http://localhost:11434/v1");
    await userEvent.click(screen.getByRole("button", { name: "Add model" }));

    expect(state.createProfile.mutateAsync).toHaveBeenCalledWith(
      expect.objectContaining({ secret_id: null, base_url: "http://localhost:11434/v1" }),
    );
  });

  it("refuses to submit a keyless provider with neither a key nor an endpoint", async () => {
    // `keyless` alone does not make a model runnable: without an endpoint there is
    // nowhere to send the request. The service refuses this, so the form must not
    // offer it.
    state.purposes = [...state.purposes, purpose("ollama", "Ollama")];
    state.catalog = [
      ...state.catalog,
      capabilities("ollama", "Ollama", { supports_base_url: true, keyless: true }),
    ];
    mount();
    await pickProvider("Ollama");
    await userEvent.click(screen.getByLabelText("Model"));
    await userEvent.click(screen.getByRole("option", { name: /gpt-5/ }));

    expect(screen.getByRole("button", { name: "Add model" })).toBeDisabled();
  });
});
