import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { toast } from "sonner";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { OrgVoiceSettings } from "./org-voice-settings";
import { apiClient } from "@/lib/api-client";
import { ApiError } from "@/lib/api-error";
import { useOrgStore } from "@/stores";
import type { Organization } from "@/types";
import type { ModelProfile } from "@/types/providers";

vi.mock("@/lib/api-client", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api-client")>("@/lib/api-client");
  return {
    ...actual,
    apiClient: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() },
  };
});
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

const ORG_ID = "org-1";

/** `backend/app/core/catalog/speech_to_text_models.json`, as the route serves it. */
const CATALOG = {
  items: [
    {
      provider: "openai",
      name: "OpenAI",
      models: [
        { id: "gpt-4o-transcribe", name: "GPT-4o Transcribe", description: "Most accurate." },
        { id: "gpt-4o-mini-transcribe", name: "GPT-4o mini Transcribe", description: "Cheaper." },
        { id: "whisper-1", name: "Whisper", description: "The original endpoint." },
      ],
    },
    {
      provider: "groq",
      name: "Groq",
      models: [
        { id: "whisper-large-v3-turbo", name: "Whisper large v3 turbo", description: "Fastest." },
        { id: "whisper-large-v3", name: "Whisper large v3", description: "The accurate one." },
      ],
    },
    {
      provider: "mistral",
      name: "Mistral",
      models: [{ id: "voxtral-mini-latest", name: "Voxtral Mini", description: "Mistral's." }],
    },
  ],
  total: 3,
  languages: ["en", "pl", "de"],
};

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

function org(overrides: Partial<Organization> = {}): Organization {
  return {
    id: ORG_ID,
    name: "Acme",
    slug: "acme",
    avatar_url: null,
    avatar_color: null,
    is_personal: false,
    owner_id: "u1",
    stripe_customer_id: null,
    chat_may_waive_approvals: false,
    subscription_tier: "free",
    seats_limit: null,
    monthly_budget_usd: null,
    chat_dictation: "browser",
    speech_to_text_provider: null,
    speech_to_text_model: null,
    speech_to_text_language: null,
    dictation_max_seconds: 300,
    chat_dictation_ready: false,
    created_at: "2026-07-01T00:00:00Z",
    updated_at: null,
    ...overrides,
  };
}

function profile(overrides: Partial<ModelProfile> = {}): ModelProfile {
  return {
    id: "p-openai",
    label: "openai-prod",
    provider: "openai",
    model: "gpt-4o",
    secret_id: "s-1",
    base_url: null,
    params: {},
    fallback_profile_ids: [],
    ...overrides,
  } as ModelProfile;
}

const KEYED = [profile(), profile({ id: "p-groq", label: "groq", provider: "groq" })];

interface Served {
  settings?: boolean;
  profiles?: ModelProfile[] | "fail";
  catalog?: "fail";
}

function serve({ settings = true, profiles = KEYED, catalog }: Served = {}) {
  vi.mocked(apiClient.get).mockImplementation(async (path: string) => {
    if (path === "/me/permissions") {
      return {
        organization_id: ORG_ID,
        role: settings ? "owner" : "member",
        is_app_admin: false,
        permissions: settings ? [{ permission: "org:settings", scope: "all" }] : [],
      };
    }
    if (path === "/providers/speech-to-text-models") {
      if (catalog === "fail") throw new Error("403");
      return CATALOG;
    }
    if (path === "/providers/catalog") return { items: [], total: 0 };
    if (path === "/providers/model-profiles") {
      if (profiles === "fail") throw new Error("502");
      return { items: profiles, total: profiles.length };
    }
    if (path === "/orgs") return { items: [org()], total: 1 };
    throw new Error(`unexpected GET ${path}`);
  });
}

async function mount(stored: Partial<Organization> = {}, served: Served = {}) {
  serve(served);
  render(<OrgVoiceSettings org={org(stored)} />, { wrapper });
  await screen.findByRole("heading", { name: "Voice" });
  // The profiles decide which providers are offered; wait for them to arrive.
  await waitFor(() => expect(apiClient.get).toHaveBeenCalledWith("/providers/model-profiles"));
}

async function choose(field: string | RegExp, option: string | RegExp) {
  await userEvent.click(screen.getByRole("combobox", { name: field }));
  await userEvent.click(await screen.findByRole("option", { name: option }));
}

describe("OrgVoiceSettings", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useOrgStore.setState({ activeOrgId: ORG_ID });
  });

  it("shows nothing to somebody who may not change organization settings", async () => {
    serve({ settings: false });
    render(<OrgVoiceSettings org={org()} />, { wrapper });

    await waitFor(() => expect(apiClient.get).toHaveBeenCalledWith("/me/permissions"));
    expect(screen.queryByRole("heading", { name: "Voice" })).not.toBeInTheDocument();
    // Never issued, not merely ignored.
    expect(apiClient.get).not.toHaveBeenCalledWith("/providers/speech-to-text-models");
  });

  it("offers three engines, each saying where the audio goes", async () => {
    await mount();

    expect(screen.getByRole("radio", { name: /^Off/ })).toHaveAccessibleName(
      /No microphone in chat\./,
    );
    expect(screen.getByRole("radio", { name: /^Browser/ })).toHaveAccessibleName(
      /Audio goes to the browser vendor \(Google, Apple\)\. Not in Firefox\./,
    );
    expect(screen.getByRole("radio", { name: /^Server/ })).toHaveAccessibleName(
      /Audio goes through this deployment to the provider you pick\. Every browser\./,
    );
    expect(screen.getByRole("radio", { name: /^Browser/ })).toBeChecked();
    // Browser needs no provider, so none of the server fields are drawn.
    expect(screen.queryByRole("combobox", { name: "Provider" })).not.toBeInTheDocument();
    // Its path says the organization's provider is not involved.
    expect(screen.getByText("Browser vendor's speech service")).toBeInTheDocument();
    expect(
      screen.getByText("The organization's provider is not used. Firefox shows no microphone."),
    ).toBeInTheDocument();

    await userEvent.click(screen.getByRole("radio", { name: /^Off/ }));
    expect(screen.queryByText("Browser vendor's speech service")).not.toBeInTheDocument();
  });

  it("disables Server and says why when no catalog provider has credentials", async () => {
    // A profile whose key was deleted (no secret, no endpoint) cannot send.
    await mount({}, { profiles: [profile({ secret_id: null })] });

    await waitFor(() => expect(screen.getByRole("radio", { name: /^Server/ })).toBeDisabled());
    expect(screen.getByText("Server needs provider credentials")).toBeInTheDocument();
    expect(screen.getByText(/Add one for OpenAI, Groq, or Mistral/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Add a model profile" })).toHaveAttribute(
      "href",
      "/agents",
    );
  });

  it("counts a keyless profile that names an endpoint as credentials", async () => {
    await mount(
      {},
      { profiles: [profile({ secret_id: null, base_url: "http://whisper.internal:8000/v1" })] },
    );

    await userEvent.click(screen.getByRole("radio", { name: /^Server/ }));

    // Its host is where the audio goes, so the path line names it.
    expect(screen.getByText("OpenAI · whisper.internal:8000")).toBeInTheDocument();
    expect(screen.queryByText("Server needs provider credentials")).not.toBeInTheDocument();
  });

  it("sends with the keyed profile when a keyless one sorts before it", async () => {
    // The server's rule: a keyless endpoint is only the fallback. Were it
    // picked here by label, the path would name a host the audio never visits.
    await mount(
      {},
      {
        profiles: [
          profile({ id: "p-prod", label: "openai-prod" }),
          profile({
            id: "p-local",
            label: "a-local-vllm",
            secret_id: null,
            base_url: "http://vllm.local:8000/v1",
          }),
        ],
      },
    );

    await userEvent.click(screen.getByRole("radio", { name: /^Server/ }));

    expect(screen.queryByText("OpenAI · vllm.local:8000")).not.toBeInTheDocument();
    expect(screen.getByText(/only the text is kept/)).toBeInTheDocument();
  });

  it("shows the server fields, with providers lacking credentials disabled", async () => {
    await mount();

    await userEvent.click(screen.getByRole("radio", { name: /^Server/ }));

    expect(screen.getByRole("combobox", { name: "Provider" })).toHaveTextContent("OpenAI");
    expect(screen.getByRole("combobox", { name: "Model" })).toHaveTextContent("GPT-4o Transcribe");
    expect(screen.getByText("OpenAI models in the speech-to-text catalog.")).toBeInTheDocument();
    expect(
      screen.getByText(/^Sent with this organization's OpenAI credentials\./),
    ).toBeInTheDocument();
    expect(screen.queryByText("Browser vendor's speech service")).not.toBeInTheDocument();
    expect(screen.getByLabelText("Max recording length")).toHaveValue("5");
    expect(screen.getByRole("combobox", { name: "Unit" })).toHaveTextContent("minutes");
    expect(screen.getByText(/only the text is kept/)).toBeInTheDocument();

    await userEvent.click(screen.getByRole("combobox", { name: "Provider" }));
    expect(await screen.findByRole("option", { name: "Mistral (no credentials)" })).toHaveAttribute(
      "aria-disabled",
      "true",
    );
    expect(screen.getByRole("option", { name: "Groq" })).not.toHaveAttribute(
      "aria-disabled",
      "true",
    );
  });

  it("starts the language list on Auto-detect, then names each language", async () => {
    await mount({
      chat_dictation: "server",
      speech_to_text_provider: "openai",
      speech_to_text_model: "whisper-1",
      chat_dictation_ready: true,
    });

    expect(screen.getByRole("combobox", { name: "Language" })).toHaveTextContent("Auto-detect");
    await userEvent.click(screen.getByRole("combobox", { name: "Language" }));
    const options = (await screen.findAllByRole("option")).map((option) => option.textContent);
    expect(options).toEqual(["Auto-detect", "English (en)", "German (de)", "Polish (pl)"]);
  });

  it("warns that Mistral may not take every language or the recording format", async () => {
    await mount(
      {
        chat_dictation: "server",
        speech_to_text_provider: "openai",
        speech_to_text_model: "whisper-1",
        chat_dictation_ready: true,
      },
      { profiles: [...KEYED, profile({ id: "p-mistral", label: "mistral", provider: "mistral" })] },
    );
    expect(
      screen.getByText("Auto-detect suits mixed teams. A fixed language is more accurate."),
    ).toBeInTheDocument();

    await choose("Provider", "Mistral");

    expect(
      screen.getByText(/^Mistral transcribes fewer languages than this list offers/),
    ).toHaveTextContent("does not say which recording formats it accepts");
    expect(screen.queryByText(/^Auto-detect suits mixed teams/)).not.toBeInTheDocument();
  });

  it("resets the model to the new provider's first one", async () => {
    await mount({
      chat_dictation: "server",
      speech_to_text_provider: "openai",
      speech_to_text_model: "whisper-1",
      chat_dictation_ready: true,
    });

    await choose("Provider", "Groq");

    expect(screen.getByRole("combobox", { name: "Model" })).toHaveTextContent(
      "Whisper large v3 turbo",
    );
    // The hint and the path follow the provider.
    expect(screen.getByText("Groq models in the speech-to-text catalog.")).toBeInTheDocument();
    expect(
      screen.getByText(/^Sent with this organization's Groq credentials\./),
    ).toBeInTheDocument();
  });

  it("saves all five settings in one request, the length in seconds", async () => {
    vi.mocked(apiClient.patch).mockImplementation(async (_path, body) =>
      org(body as Partial<Organization>),
    );
    await mount();

    await userEvent.click(screen.getByRole("radio", { name: /^Server/ }));
    await choose("Model", "Whisper");
    await choose("Language", "Polish (pl)");
    const length = screen.getByLabelText("Max recording length");
    await userEvent.clear(length);
    await userEvent.type(length, "2");
    await userEvent.click(screen.getByRole("button", { name: "Save changes" }));

    await waitFor(() =>
      expect(apiClient.patch).toHaveBeenCalledWith(`/orgs/${ORG_ID}`, {
        chat_dictation: "server",
        speech_to_text_provider: "openai",
        speech_to_text_model: "whisper-1",
        speech_to_text_language: "pl",
        dictation_max_seconds: 120,
      }),
    );
    expect(apiClient.patch).toHaveBeenCalledTimes(1);
    expect(toast.success).toHaveBeenCalledWith("Voice settings saved");
  });

  it("sends auto-detect as null and takes a length in seconds", async () => {
    vi.mocked(apiClient.patch).mockResolvedValue(org());
    await mount({
      chat_dictation: "server",
      speech_to_text_provider: "openai",
      speech_to_text_model: "whisper-1",
      speech_to_text_language: "de",
      dictation_max_seconds: 90,
      chat_dictation_ready: true,
    });

    expect(screen.getByLabelText("Max recording length")).toHaveValue("90");
    await choose("Language", "Auto-detect");
    await choose("Unit", "minutes");
    await userEvent.click(screen.getByRole("button", { name: "Save changes" }));

    // 90 minutes is past the ceiling, so nothing is sent until it is fixed.
    expect(
      await screen.findByText("Enter a length between 10 seconds and 10 minutes."),
    ).toBeInTheDocument();
    await choose("Unit", "seconds");
    await userEvent.click(screen.getByRole("button", { name: "Save changes" }));

    await waitFor(() =>
      expect(apiClient.patch).toHaveBeenCalledWith(`/orgs/${ORG_ID}`, {
        chat_dictation: "server",
        speech_to_text_language: null,
        dictation_max_seconds: 90,
      }),
    );
  });

  it("refuses a length under ten seconds without asking the server", async () => {
    await mount();
    await userEvent.click(screen.getByRole("radio", { name: /^Server/ }));
    await choose("Unit", "seconds");
    const length = screen.getByLabelText("Max recording length");
    await userEvent.clear(length);
    await userEvent.type(length, "5");

    await userEvent.click(screen.getByRole("button", { name: "Save changes" }));

    expect(
      await screen.findByText("Enter a length between 10 seconds and 10 minutes."),
    ).toBeInTheDocument();
    expect(length).toHaveAttribute("aria-invalid", "true");
    expect(apiClient.patch).not.toHaveBeenCalled();

    // An empty box is not a length either.
    await userEvent.clear(length);
    await userEvent.click(screen.getByRole("button", { name: "Save changes" }));
    expect(apiClient.patch).not.toHaveBeenCalled();
  });

  it("switches a broken server engine to the browser without naming the stale pair", async () => {
    // Naming the pair asks the server to check it against the catalog; a model
    // withdrawn since must not stop somebody turning server dictation off.
    vi.mocked(apiClient.patch).mockResolvedValue(org());
    // What the server reports for it: a stored pair, and not ready.
    await mount({
      chat_dictation: "server",
      speech_to_text_provider: "openai",
      speech_to_text_model: "whisper-0",
      dictation_max_seconds: 45,
      chat_dictation_ready: false,
    });

    // The pair is chosen, so the warning names the model rather than saying
    // nothing is; and it is fixed here, not with a new profile.
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("The chosen model, whisper-0, is no longer offered.");
    expect(alert).not.toHaveTextContent("No speech-to-text provider and model are chosen.");
    expect(within(alert).queryByRole("link")).not.toBeInTheDocument();

    await userEvent.click(screen.getByRole("radio", { name: /^Browser/ }));
    await userEvent.click(screen.getByRole("button", { name: "Save changes" }));

    await waitFor(() =>
      expect(apiClient.patch).toHaveBeenCalledWith(`/orgs/${ORG_ID}`, {
        chat_dictation: "browser",
        speech_to_text_language: null,
        dictation_max_seconds: 45,
      }),
    );
  });

  it("puts the server's refusal under the engine choice", async () => {
    vi.mocked(apiClient.patch).mockRejectedValue(
      new ApiError(422, "Invalid request", {
        error: {
          code: "VALIDATION_ERROR",
          message: "Invalid request",
          details: {
            fields: [
              {
                field: "chat_dictation",
                message: "Server dictation needs a speech-to-text provider and model first.",
              },
            ],
          },
        },
      }),
    );
    await mount();

    await userEvent.click(screen.getByRole("radio", { name: /^Server/ }));
    await userEvent.click(screen.getByRole("button", { name: "Save changes" }));

    const message = await screen.findByText(
      "Server dictation needs a speech-to-text provider and model first.",
    );
    expect(screen.getByRole("radiogroup", { name: "Dictation engine" })).toContainElement(message);
    expect(toast.error).not.toHaveBeenCalled();
  });

  it("toasts a failure that names no field", async () => {
    vi.mocked(apiClient.patch).mockRejectedValue(new ApiError(500, "Server exploded"));
    await mount();

    await userEvent.click(screen.getByRole("radio", { name: /^Off/ }));
    await userEvent.click(screen.getByRole("button", { name: "Save changes" }));

    await waitFor(() => expect(toast.error).toHaveBeenCalled());
  });

  it("puts Cancel back to what is stored, and saves nothing unchanged", async () => {
    await mount();
    const save = screen.getByRole("button", { name: "Save changes" });
    const cancel = screen.getByRole("button", { name: "Cancel" });
    expect(save).toBeDisabled();
    expect(cancel).toBeDisabled();

    await userEvent.click(screen.getByRole("radio", { name: /^Server/ }));
    expect(save).toBeEnabled();
    await userEvent.click(cancel);

    expect(screen.getByRole("radio", { name: /^Browser/ })).toBeChecked();
    expect(screen.queryByRole("combobox", { name: "Provider" })).not.toBeInTheDocument();
    expect(save).toBeDisabled();
  });

  it("warns when server dictation has no provider credentials left", async () => {
    await mount({
      chat_dictation: "server",
      speech_to_text_provider: "mistral",
      speech_to_text_model: "voxtral-mini-latest",
      chat_dictation_ready: true,
    });

    const alert = await screen.findByRole("alert");
    expect(within(alert).getByText("Dictation is unavailable in chat")).toBeInTheDocument();
    expect(alert).toHaveTextContent("This organization has no Mistral credentials.");
    expect(within(alert).getByRole("link", { name: "Add a model profile" })).toHaveAttribute(
      "href",
      "/agents",
    );
    // The stored provider stays selectable, so the form can still be saved.
    await userEvent.click(screen.getByRole("combobox", { name: "Provider" }));
    expect(
      await screen.findByRole("option", { name: "Mistral (no credentials)" }),
    ).not.toHaveAttribute("aria-disabled", "true");
  });

  it("warns when server dictation has no model chosen", async () => {
    await mount({ chat_dictation: "server", chat_dictation_ready: false });

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("No speech-to-text provider and model are chosen.");
  });

  it("does not warn while server dictation is configured and credentialed", async () => {
    await mount({
      chat_dictation: "server",
      speech_to_text_provider: "openai",
      speech_to_text_model: "whisper-1",
      chat_dictation_ready: true,
    });

    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    // A keyed profile on the provider's public API: the path names no host.
    expect(screen.queryByText(/OpenAI ·/)).not.toBeInTheDocument();
  });

  it("marks nothing as lacking credentials when the profiles cannot be read", async () => {
    await mount({}, { profiles: "fail" });

    await userEvent.click(screen.getByRole("radio", { name: /^Server/ }));
    await userEvent.click(screen.getByRole("combobox", { name: "Provider" }));

    expect(await screen.findByRole("option", { name: "Mistral" })).toBeInTheDocument();
    expect(screen.queryByText("Server needs provider credentials")).not.toBeInTheDocument();
  });

  it("marks nothing as lacking credentials when the catalog cannot be read", async () => {
    // Gated on agents:view, which a custom role holding org:settings may lack.
    await mount({}, { catalog: "fail" });
    await waitFor(() =>
      expect(apiClient.get).toHaveBeenCalledWith("/providers/speech-to-text-models"),
    );

    const server = screen.getByRole("radio", { name: /^Server/ });
    expect(server).toBeEnabled();
    expect(screen.queryByText("Server needs provider credentials")).not.toBeInTheDocument();

    // Nothing to preselect, so the pair stays empty for the server to name.
    await userEvent.click(server);
    expect(server).toBeChecked();
    expect(screen.getByRole("combobox", { name: "Provider" })).toBeInTheDocument();
    expect(screen.queryByText(/^Sent with/)).not.toBeInTheDocument();
  });

  it("names a provider without credentials by its id when the catalog cannot be read", async () => {
    await mount(
      {
        chat_dictation: "server",
        speech_to_text_provider: "mistral",
        speech_to_text_model: "voxtral-mini-latest",
        chat_dictation_ready: true,
      },
      { catalog: "fail" },
    );

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("This organization has no mistral credentials.");
  });

  it("ignores an endpoint it cannot parse when naming the host", async () => {
    await mount({}, { profiles: [profile({ secret_id: null, base_url: "not a url" })] });

    await userEvent.click(screen.getByRole("radio", { name: /^Server/ }));

    expect(screen.queryByText(/OpenAI ·/)).not.toBeInTheDocument();
    expect(screen.getByText(/only the text is kept/)).toBeInTheDocument();
  });

  it("lists voice conversations as coming soon, with nothing to set", async () => {
    await mount();

    const heading = screen.getByRole("heading", { name: /Voice conversations/ });
    expect(heading).toHaveTextContent("Coming soon");
    const section = heading.closest("[aria-disabled]");
    expect(section).toHaveAttribute("aria-disabled", "true");
    expect(section?.querySelector("input, select, button")).toBeNull();
  });
});
