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
    speech_to_text_provider: null,
    speech_to_text_model: null,
    speech_to_text_secret_id: null,
    speech_to_text_language: null,
    dictation_max_seconds: 300,
    created_at: "2026-07-01T00:00:00Z",
    updated_at: null,
    ...overrides,
  };
}

interface Key {
  id: string;
  name: string;
  kind: string;
  hint: string;
  purpose: string;
  visibility: "org" | "team" | "private";
}

function key(id: string, purpose: string, visibility: Key["visibility"] = "org"): Key {
  return { id, name: id, kind: "api_key", hint: "abcd", purpose, visibility };
}

/** One organization-wide key each for OpenAI and Groq, and a private Mistral one. */
const VAULT = [
  key("team-openai", "openai"),
  key("team-groq", "groq"),
  key("my-mistral", "mistral", "private"),
];

/** `GET /ml/calls/summary` for an organization that has transcribed. */
const USAGE = {
  service: "speech_to_text",
  days: 30,
  seconds: 2520,
  count: 118,
  count_unknown_length: 30,
  by_agent: [{ agent_id: "a-1", name: "Support", seconds: 1800, count: 80 }],
  by_channel: [{ channel_bot_id: "b-1", name: "Front desk", seconds: 20, count: 38 }],
  by_surface: [],
};

interface Served {
  settings?: boolean;
  /** `runs:view` as well, which the usage line needs. */
  runsView?: boolean;
  /** What `GET /ml/calls/summary` answers. */
  usage?: Record<string, unknown> | "forbidden";
  catalog?: "fail";
  /** What `GET /secrets` lists, or a refusal. */
  vault?: Key[] | "fail";
}

function serve({
  settings = true,
  runsView = false,
  usage = USAGE,
  catalog,
  vault = VAULT,
}: Served = {}) {
  vi.mocked(apiClient.get).mockImplementation(async (path: string) => {
    if (path === "/me/permissions") {
      const granted = [...(settings ? ["org:settings"] : []), ...(runsView ? ["runs:view"] : [])];
      return {
        organization_id: ORG_ID,
        role: settings ? "owner" : "member",
        is_app_admin: false,
        permissions: granted.map((permission) => ({ permission, scope: "all" })),
      };
    }
    if (path === "/ml/calls/summary") {
      if (usage === "forbidden") throw new ApiError(403, "Forbidden", null);
      return usage;
    }
    if (path === "/providers/speech-to-text-models") {
      if (catalog === "fail") throw new Error("403");
      return CATALOG;
    }
    if (path === "/secrets") {
      if (vault === "fail") throw new ApiError(403, "Forbidden", null);
      return { items: vault, total: vault.length };
    }
    if (path === "/secrets/kinds") return { items: [] };
    if (path === "/orgs") return { items: [org()], total: 1 };
    throw new Error(`unexpected GET ${path}`);
  });
}

async function mount(stored: Partial<Organization> = {}, served: Served = {}) {
  serve(served);
  render(<OrgVoiceSettings org={org(stored)} />, { wrapper });
  await screen.findByRole("heading", { name: "Voice" });
  // The vault decides which providers have a key; wait for it to arrive.
  await waitFor(() => expect(apiClient.get).toHaveBeenCalledWith("/secrets"));
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

  it("shows the default provider and the longest recording, with no engine to choose", async () => {
    await mount();

    expect(screen.queryByRole("radiogroup")).not.toBeInTheDocument();
    expect(screen.getByRole("combobox", { name: "Provider" })).toHaveTextContent("None");
    expect(screen.getByLabelText("Max recording length")).toHaveValue("5");
    expect(screen.getByRole("combobox", { name: "Unit" })).toHaveTextContent("minutes");
    // No provider, so no path for a recording to take.
    expect(screen.queryByText(/^Sent with/)).not.toBeInTheDocument();
  });

  it("offers a provider with no key yet, and says how to add one", async () => {
    await mount({}, { vault: [] });

    await choose("Provider", "OpenAI (no usable key)");
    expect(
      await screen.findByText(/No organization-wide OpenAI keys in the vault yet/),
    ).toBeInTheDocument();
  });

  it("names an existing private OpenAI key and explains its required access", async () => {
    await mount({}, { vault: [key("Private OpenAI", "openai", "private")] });
    await choose("Provider", "OpenAI (no usable key)");
    expect(
      await screen.findByText(/Private OpenAI.*shared with the whole organization/),
    ).toBeVisible();
    expect(
      screen.queryByText(/No organization-wide OpenAI keys in the vault yet/),
    ).not.toBeInTheDocument();
  });

  it("shows the provider's fields, marking providers with no organization-wide key", async () => {
    await mount();

    await choose("Provider", "OpenAI");

    expect(screen.getByRole("combobox", { name: "Model" })).toHaveTextContent("GPT-4o Transcribe");
    // The only organization-wide OpenAI key, chosen by itself.
    expect(screen.getByRole("combobox", { name: "Key" })).toHaveTextContent("team-openai");
    expect(screen.getByText("OpenAI models in the speech-to-text catalog.")).toBeInTheDocument();
    expect(
      screen.getByText(/^Sent with the organization's OpenAI key chosen below\./),
    ).toBeInTheDocument();
    expect(screen.getByText(/only the text is kept/)).toBeInTheDocument();

    // A private Mistral key does not count: this one is spent for everybody.
    await userEvent.click(screen.getByRole("combobox", { name: "Provider" }));
    expect(
      await screen.findByRole("option", { name: "Mistral (no usable key)" }),
    ).not.toHaveAttribute("aria-disabled");
    expect(screen.getByRole("option", { name: "Groq" })).toBeInTheDocument();
  });

  it("starts the language list on Auto-detect, then names each language", async () => {
    await mount({
      speech_to_text_provider: "openai",
      speech_to_text_model: "whisper-1",
      speech_to_text_secret_id: "team-openai",
    });

    expect(screen.getByRole("combobox", { name: "Language" })).toHaveTextContent("Auto-detect");
    await userEvent.click(screen.getByRole("combobox", { name: "Language" }));
    const options = (await screen.findAllByRole("option")).map((option) => option.textContent);
    expect(options).toEqual(["Auto-detect", "English (en)", "German (de)", "Polish (pl)"]);
  });

  it("warns that Mistral may not take every language or the recording format", async () => {
    await mount(
      {
        speech_to_text_provider: "openai",
        speech_to_text_model: "whisper-1",
        speech_to_text_secret_id: "team-openai",
      },
      { vault: [...VAULT, key("team-mistral", "mistral")] },
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

  it("resets the model and the key to the new provider's", async () => {
    vi.mocked(apiClient.patch).mockResolvedValue(org());
    await mount(
      {
        speech_to_text_provider: "openai",
        speech_to_text_model: "whisper-1",
        speech_to_text_secret_id: "team-openai",
      },
      { vault: [...VAULT, key("team-groq-2", "groq")] },
    );

    await choose("Provider", "Groq");

    expect(screen.getByRole("combobox", { name: "Model" })).toHaveTextContent(
      "Whisper large v3 turbo",
    );
    // Two Groq keys: the OpenAI one is gone and neither is chosen for anyone.
    expect(screen.getByRole("combobox", { name: "Key" })).toHaveTextContent("Choose a key");
    // The hint and the path follow the provider.
    expect(screen.getByText("Groq models in the speech-to-text catalog.")).toBeInTheDocument();
    expect(
      screen.getByText(/^Sent with the organization's Groq key chosen below\./),
    ).toBeInTheDocument();

    await choose("Key", /^team-groq-2.*abcd$/);
    await userEvent.click(screen.getByRole("button", { name: "Save changes" }));
    await waitFor(() =>
      expect(apiClient.patch).toHaveBeenCalledWith(`/orgs/${ORG_ID}`, {
        speech_to_text_provider: "groq",
        speech_to_text_model: "whisper-large-v3-turbo",
        speech_to_text_secret_id: "team-groq-2",
        speech_to_text_language: null,
        dictation_max_seconds: 300,
      }),
    );
  });

  it("saves every setting in one request, the key explicitly, the length in seconds", async () => {
    vi.mocked(apiClient.patch).mockImplementation(async (_path, body) =>
      org(body as Partial<Organization>),
    );
    await mount();

    await choose("Provider", "OpenAI");
    await choose("Model", "Whisper");
    await choose("Language", "Polish (pl)");
    const length = screen.getByLabelText("Max recording length");
    await userEvent.clear(length);
    await userEvent.type(length, "2");
    await userEvent.click(screen.getByRole("button", { name: "Save changes" }));

    await waitFor(() =>
      expect(apiClient.patch).toHaveBeenCalledWith(`/orgs/${ORG_ID}`, {
        speech_to_text_provider: "openai",
        speech_to_text_model: "whisper-1",
        speech_to_text_secret_id: "team-openai",
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
      speech_to_text_provider: "openai",
      speech_to_text_model: "whisper-1",
      speech_to_text_secret_id: "team-openai",
      speech_to_text_language: "de",
      dictation_max_seconds: 90,
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
        speech_to_text_language: null,
        dictation_max_seconds: 90,
      }),
    );
  });

  it("refuses a length under ten seconds without asking the server", async () => {
    await mount();
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

  it("warns of a withdrawn model, and saves the language without naming the stale pair", async () => {
    // Naming the pair asks the server to check it against the catalog; a model
    // withdrawn since must not stop somebody changing the language.
    vi.mocked(apiClient.patch).mockResolvedValue(org());
    await mount({
      speech_to_text_provider: "openai",
      speech_to_text_model: "whisper-0",
      speech_to_text_secret_id: "team-openai",
      dictation_max_seconds: 45,
    });

    const alert = await screen.findByRole("alert");
    expect(within(alert).getByText("The default provider can't transcribe")).toBeInTheDocument();
    expect(alert).toHaveTextContent("The chosen model, whisper-0, is no longer offered.");
    expect(within(alert).queryByRole("link")).not.toBeInTheDocument();

    await choose("Language", "Polish (pl)");
    await userEvent.click(screen.getByRole("button", { name: "Save changes" }));

    await waitFor(() =>
      expect(apiClient.patch).toHaveBeenCalledWith(`/orgs/${ORG_ID}`, {
        speech_to_text_language: "pl",
        dictation_max_seconds: 45,
      }),
    );
  });

  it("puts the server's refusal of the model under the model field", async () => {
    vi.mocked(apiClient.patch).mockRejectedValue(
      new ApiError(422, "Invalid request", {
        error: {
          code: "VALIDATION_ERROR",
          message: "Invalid request",
          details: {
            fields: [{ field: "speech_to_text_model", message: "Not in the catalog." }],
          },
        },
      }),
    );
    await mount();

    await choose("Provider", "OpenAI");
    await userEvent.click(screen.getByRole("button", { name: "Save changes" }));

    expect(await screen.findByText("Not in the catalog.")).toBeInTheDocument();
    expect(toast.error).not.toHaveBeenCalled();
  });

  it("toasts a failure that names no field", async () => {
    vi.mocked(apiClient.patch).mockRejectedValue(new ApiError(500, "Server exploded"));
    await mount();

    await choose("Language", "Polish (pl)");
    await userEvent.click(screen.getByRole("button", { name: "Save changes" }));

    await waitFor(() => expect(toast.error).toHaveBeenCalled());
  });

  it("puts Cancel back to what is stored, and saves nothing unchanged", async () => {
    await mount();
    const save = screen.getByRole("button", { name: "Save changes" });
    const cancel = screen.getByRole("button", { name: "Cancel" });
    expect(save).toBeDisabled();
    expect(cancel).toBeDisabled();

    await choose("Provider", "OpenAI");
    expect(save).toBeEnabled();
    await userEvent.click(cancel);

    expect(screen.getByRole("combobox", { name: "Provider" })).toHaveTextContent("None");
    expect(save).toBeDisabled();
  });

  it("says to choose a key when the stored pair has none - deleted since", async () => {
    vi.mocked(apiClient.patch).mockResolvedValue(org());
    await mount(
      {
        speech_to_text_provider: "groq",
        speech_to_text_model: "whisper-large-v3",
      },
      { vault: [key("a", "groq"), key("b", "groq")] },
    );

    const alert = await screen.findByRole("alert");
    expect(within(alert).getByText("The default provider can't transcribe")).toBeInTheDocument();
    expect(alert).toHaveTextContent("No key is chosen for Groq.");
    expect(within(alert).queryByRole("link")).not.toBeInTheDocument();
    expect(screen.getByRole("combobox", { name: "Key" })).toHaveTextContent("Choose a key");

    await choose("Key", /^b.*abcd$/);
    await userEvent.click(screen.getByRole("button", { name: "Save changes" }));
    await waitFor(() =>
      expect(apiClient.patch).toHaveBeenCalledWith(`/orgs/${ORG_ID}`, {
        speech_to_text_provider: "groq",
        speech_to_text_model: "whisper-large-v3",
        speech_to_text_secret_id: "b",
        speech_to_text_language: null,
        dictation_max_seconds: 300,
      }),
    );
  });

  it("names a stored provider the catalog no longer lists by its id", async () => {
    await mount({
      speech_to_text_provider: "deepgram",
      speech_to_text_model: "nova",
    });

    expect(await screen.findByRole("alert")).toHaveTextContent("No key is chosen for deepgram.");
  });

  it("puts the server's refusal of the key under the key field", async () => {
    vi.mocked(apiClient.patch).mockRejectedValue(
      new ApiError(400, "Refused", {
        error: {
          code: "BAD_REQUEST",
          message: "Refused",
          details: {
            fields: [{ field: "speech_to_text_secret_id", message: "'x' is a key for groq" }],
          },
        },
      }),
    );
    await mount();

    await choose("Provider", "OpenAI");
    await userEvent.click(screen.getByRole("button", { name: "Save changes" }));

    expect(await screen.findByText("'x' is a key for groq")).toBeInTheDocument();
  });

  it("does not warn when no default provider is chosen: agents choose their own", async () => {
    await mount();

    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("does not warn while server dictation is configured with a key", async () => {
    await mount({
      speech_to_text_provider: "openai",
      speech_to_text_model: "whisper-1",
      speech_to_text_secret_id: "team-openai",
    });

    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Save changes" })).toBeDisabled();
  });

  it("marks no provider when the vault cannot be listed, and says why no key is offered", async () => {
    await mount({}, { vault: "fail" });

    await choose("Provider", "OpenAI");

    expect(await screen.findByText(/You cannot list the vault's keys/)).toBeInTheDocument();
  });

  it("saves the default provider with its only organization-wide key", async () => {
    // A bot inheriting sends its voice notes to this pair, and agents dictate to it.
    vi.mocked(apiClient.patch).mockResolvedValue(org());
    await mount();

    await choose("Provider", "Groq");
    expect(screen.getByRole("combobox", { name: "Model" })).toHaveTextContent(
      "Whisper large v3 turbo",
    );
    await userEvent.click(screen.getByRole("button", { name: "Save changes" }));

    await waitFor(() =>
      expect(apiClient.patch).toHaveBeenCalledWith(`/orgs/${ORG_ID}`, {
        speech_to_text_language: null,
        dictation_max_seconds: 300,
        speech_to_text_provider: "groq",
        speech_to_text_model: "whisper-large-v3-turbo",
        speech_to_text_secret_id: "team-groq",
      }),
    );
  });

  it("clears the default provider with None", async () => {
    vi.mocked(apiClient.patch).mockResolvedValue(org());
    await mount({
      speech_to_text_provider: "openai",
      speech_to_text_model: "whisper-1",
      speech_to_text_secret_id: "team-openai",
    });

    await choose("Provider", "None");
    expect(screen.queryByRole("combobox", { name: "Model" })).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Save changes" }));

    await waitFor(() =>
      expect(apiClient.patch).toHaveBeenCalledWith(`/orgs/${ORG_ID}`, {
        speech_to_text_language: null,
        dictation_max_seconds: 300,
        speech_to_text_provider: null,
        speech_to_text_model: null,
        speech_to_text_secret_id: null,
      }),
    );
  });

  it("offers no provider when the catalog cannot be read, and draws no path", async () => {
    // Gated on agents:view, which a custom role holding org:settings may lack.
    await mount({}, { catalog: "fail" });
    await waitFor(() =>
      expect(apiClient.get).toHaveBeenCalledWith("/providers/speech-to-text-models"),
    );

    expect(screen.getByRole("combobox", { name: "Provider" })).toHaveTextContent("None");
    expect(screen.queryByText(/^Sent with/)).not.toBeInTheDocument();
  });

  describe("transcription usage", () => {
    it("says how much was transcribed and how much of it has no length", async () => {
      await mount({}, { runsView: true });

      const usage = await screen.findByRole("region", { name: "Transcription usage" });
      expect(usage).toHaveTextContent(
        "Last 30 days: 42 min · 118 recordings (30 without a length)",
      );
      expect(apiClient.get).toHaveBeenCalledWith("/ml/calls/summary", {
        params: { ml_service: "speech_to_text", days: "30" },
      });
      // The breakdown waits for a click.
      expect(within(usage).queryByText("Support")).not.toBeInTheDocument();
    });

    it("opens a breakdown by agent and by channel bot, and closes it again", async () => {
      await mount({}, { runsView: true });
      const usage = await screen.findByRole("region", { name: "Transcription usage" });

      await userEvent.click(within(usage).getByRole("button", { name: "Show breakdown" }));

      const agents = within(usage).getByRole("heading", { name: "By agent" }).parentElement!;
      expect(within(agents).getByText("Support")).toBeInTheDocument();
      expect(within(agents).getByText("30 min · 80 recordings")).toBeInTheDocument();
      const bots = within(usage).getByRole("heading", { name: "By channel bot" }).parentElement!;
      expect(within(bots).getByText("Front desk")).toBeInTheDocument();
      // A few seconds is "under 1 min", never "0 min".
      expect(within(bots).getByText("under 1 min · 38 recordings")).toBeInTheDocument();
      expect(usage).toHaveTextContent("Minutes count only recordings with a known length.");

      await userEvent.click(within(usage).getByRole("button", { name: "Hide breakdown" }));
      expect(within(usage).queryByText("Support")).not.toBeInTheDocument();
    });

    it("leaves out what it has nothing for: no unmeasured note, no empty list", async () => {
      await mount(
        {},
        {
          runsView: true,
          usage: { ...USAGE, seconds: 0, count: 1, count_unknown_length: 0, by_channel: [] },
        },
      );
      const usage = await screen.findByRole("region", { name: "Transcription usage" });
      expect(usage).toHaveTextContent("Last 30 days: 0 min · 1 recording");
      expect(usage).not.toHaveTextContent("without a length");

      await userEvent.click(within(usage).getByRole("button", { name: "Show breakdown" }));

      expect(within(usage).getByRole("heading", { name: "By agent" })).toBeInTheDocument();
      expect(within(usage).queryByRole("heading", { name: "By channel bot" })).toBeNull();
      expect(usage).not.toHaveTextContent("Minutes count only");
    });

    it("is hidden when nothing was transcribed", async () => {
      await mount({}, { runsView: true, usage: { ...USAGE, count: 0 } });

      await waitFor(() =>
        expect(apiClient.get).toHaveBeenCalledWith("/ml/calls/summary", expect.anything()),
      );
      expect(screen.queryByRole("region", { name: "Transcription usage" })).toBeNull();
    });

    it("is hidden, not an error, when the summary is refused", async () => {
      await mount({}, { runsView: true, usage: "forbidden" });

      await waitFor(() =>
        expect(apiClient.get).toHaveBeenCalledWith("/ml/calls/summary", expect.anything()),
      );
      expect(screen.queryByRole("region", { name: "Transcription usage" })).toBeNull();
      expect(screen.getByRole("heading", { name: "Voice" })).toBeInTheDocument();
    });

    it("is never asked for without runs:view, because it names agents and bots", async () => {
      await mount();

      expect(apiClient.get).not.toHaveBeenCalledWith("/ml/calls/summary", expect.anything());
      expect(screen.queryByRole("region", { name: "Transcription usage" })).toBeNull();
    });
  });
});
