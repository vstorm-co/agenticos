import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { CapabilitySettings } from "./capability-settings";
import { ApiError, apiClient } from "@/lib/api-client";
import type { CapabilityBindingSpec, CapabilityCatalogEntry } from "@/types/agents";
import type { Secret } from "@/types/secrets";

vi.mock("@/lib/api-client", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api-client")>("@/lib/api-client");
  return {
    ...actual,
    apiClient: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() },
  };
});
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

/**
 * The capability the secret picker exists for: one that cannot work without a
 * credential.
 *
 * No builtin declares a secret yet, which is exactly why the Builder had no way
 * to choose one - the gap was invisible until somebody wrote the first custom
 * capability, and that capability is a weather lookup behind an API key.
 */
const WEATHER: CapabilityCatalogEntry = {
  id: "weather",
  name: "Weather",
  category: "utility",
  description: "Read the forecast for a place.",
  side_effecting: false,
  scopes: [],
  tools: [{ id: "forecast", name: "forecast", description: "Read the forecast for a place." }],
  config_schema: null,
  contracts: [],
  requires_secret: {
    kind: "api_key",
    description: "The forecast service's API key. It refuses an unauthenticated request.",
    required_when: null,
  },
};

const API_KEY_SECRET: Secret = {
  id: "sec-1",
  name: "Weather API key",
  description: "Used by the forecast capability.",
  kind: "api_key",
  hint: "P7KD",
};

/** Web search, which needs a key for some methods and none for others. */
const SEARCH: CapabilityCatalogEntry = {
  ...WEATHER,
  requires_secret: {
    kind: "api_key",
    description: "The API key for the chosen search service",
    required_when: { field: "method", equals: ["tavily", "brave", "exa"] },
  },
};

const AWS_SECRET: Secret = {
  id: "sec-2",
  name: "Ingest role",
  description: null,
  kind: "aws_credentials",
  hint: "AKIA",
};

const binding = (overrides: Partial<CapabilityBindingSpec> = {}): CapabilityBindingSpec => ({
  id: "weather",
  config: {},
  approval: "default",
  tool_approval: {},
  tool_overrides: {},
  secret_id: null,
  enabled: true,
  ...overrides,
});

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

/** The vault answers with these. */
function serve(secrets: Secret[]) {
  vi.mocked(apiClient.get).mockImplementation(async (path: string) => {
    if (path === "/secrets") return { items: secrets, total: secrets.length };
    if (path === "/secrets/kinds") return { items: [], total: 0 };
    throw new Error(`unexpected GET ${path}`);
  });
}

/** The vault refuses, which is what a member editing their own agent gets. */
function refuse() {
  vi.mocked(apiClient.get).mockRejectedValue(
    new ApiError(403, "Missing required permission: connections:manage"),
  );
}

function mount(
  spec: CapabilityBindingSpec,
  {
    disabled = false,
    onChange = vi.fn(),
    definition = WEATHER,
  }: {
    disabled?: boolean;
    onChange?: (binding: CapabilityBindingSpec) => void;
    definition?: CapabilityCatalogEntry;
  } = {},
) {
  render(
    <CapabilitySettings
      catalog={[definition]}
      selected={[spec]}
      onChange={onChange}
      disabled={disabled}
    />,
    { wrapper },
  );
}

/** The control itself, named by its label like every other field on this card. */
const picker = () => screen.getByLabelText("Secret");

beforeEach(() => {
  vi.clearAllMocks();
});

/**
 * The secret picker, against a mocked vault.
 *
 * Mostly one direction: a spec arrives and the control shows what it says. The
 * two places where a choice writes back into the spec - picking a stored secret,
 * and storing one inline - are asserted here as well, because both are how a
 * capability that cannot run without a credential gets one.
 */
describe("CapabilitySettings secret picker", () => {
  it("shows the secret the spec stored, by name and by hint", async () => {
    serve([API_KEY_SECRET]);
    mount(binding({ secret_id: "sec-1" }));

    // The hint too: two keys for the same service are told apart by nothing
    // else, and the plaintext is not available to either of them.
    expect(await screen.findByText("Weather API key")).toBeInTheDocument();
    expect(picker()).toHaveTextContent("····P7KD");
  });

  it("shows what the capability's author said the secret is for", async () => {
    // Written in `register(...)` beside the code that reads it, and the only
    // explanation the person choosing a credential will ever get.
    serve([API_KEY_SECRET]);
    mount(binding({ secret_id: "sec-1" }));

    expect(
      await screen.findByText(/The forecast service's API key\. It refuses an unauthenticated/),
    ).toBeInTheDocument();
  });

  it("says an unselected secret is what stops the agent being published", async () => {
    // The refusal reached by doing nothing at all. Left to the publish attempt it
    // arrives as one line in a list of everything else wrong with the agent, on a
    // screen far from the capability that needs it.
    serve([API_KEY_SECRET]);
    mount(binding());

    // Waited for the vault to have arrived, so this is the state with a key
    // available and nobody having picked it - not the one before the list landed.
    expect(await screen.findByText("Choose a secret")).toBeInTheDocument();
    expect(screen.getByText(/cannot be published until it has one/)).toBeInTheDocument();
    expect(picker()).toBeInvalid();
  });

  it("offers no secret of the wrong kind, and offers to store the right one", async () => {
    // An AWS credential where an API key is required is a publish refusal with a
    // delay on it. Nothing else in the vault is offered - and since the list is
    // a dead end, the way out is *here*: the round trip this replaces was open
    // the vault, add the key, come back, and re-pick the capability.
    serve([AWS_SECRET]);
    mount(binding());

    expect(await screen.findByText("No api_key secret in the vault")).toBeInTheDocument();
    expect(picker()).toBeDisabled();
    expect(screen.getByRole("button", { name: "Add a key" })).toBeInTheDocument();
  });

  it("binds the secret that was chosen, by id", async () => {
    // The spec records which secret to use and never the secret, so the id is the
    // whole of what this control writes.
    serve([API_KEY_SECRET]);
    const onChange = vi.fn();
    mount(binding(), { onChange });

    await userEvent.click(await screen.findByLabelText("Secret"));
    await userEvent.click(screen.getByRole("option", { name: /Weather API key/ }));

    expect(onChange).toHaveBeenCalledWith(expect.objectContaining({ secret_id: "sec-1" }));
  });

  it("sends somebody to the vault for a secret that is more than one field", async () => {
    // An inline form takes an API key and nothing else. A shape with several
    // fields is filled in where it belongs, and the value stays there either
    // way - an agent records which secret to use, never the secret.
    serve([]);
    mount(binding(), {
      definition: {
        ...WEATHER,
        requires_secret: {
          kind: "aws_credentials",
          description: "The role this capability assumes.",
          required_when: null,
        },
      },
    });

    expect(await screen.findByRole("link", { name: "Store one in the vault" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Add a key" })).toBeNull();
  });

  it("stores a new key in place and selects it, without leaving the page", async () => {
    // The whole point of the inline form: the four-step round trip through the
    // vault was the most common thing this control asked people to do.
    serve([]);
    const onChange = vi.fn();
    mount(binding(), { onChange });
    vi.mocked(apiClient.post).mockResolvedValue({
      id: "sec-new",
      name: "Weather",
      kind: "api_key",
      hint: "cdef",
    });

    await userEvent.click(await screen.findByRole("button", { name: "Add a key" }));
    await userEvent.type(screen.getByLabelText("Key"), "wx-secret-abcdef");
    await userEvent.click(screen.getByRole("button", { name: "Save key" }));

    await waitFor(() =>
      expect(apiClient.post).toHaveBeenCalledWith("/secrets", {
        name: "Weather",
        value: { kind: "api_key", api_key: "wx-secret-abcdef" },
        // What the key is for, taken from the method this binding chose. It is
        // what lets the picker offer only the right keys next time instead of
        // every API key in the vault.
        purpose: "custom",
      }),
    );
    // Selected, not merely created: leaving the binding pointing at nothing
    // would mean doing the work and still failing to publish.
    await waitFor(() =>
      expect(onChange).toHaveBeenCalledWith(expect.objectContaining({ secret_id: "sec-new" })),
    );
  });

  it("does not ask for a key at all when this configuration needs none", async () => {
    // Web search takes one for Tavily and none for DuckDuckGo. Asking for a key
    // the server will not demand is as wrong as not asking for one it will -
    // and it is the version that makes the free default look unavailable.
    serve([]);
    mount(binding({ config: { method: "duckduckgo" } }), {
      definition: {
        ...WEATHER,
        requires_secret: {
          kind: "api_key",
          description: "The API key for the chosen search service",
          required_when: { field: "method", equals: ["tavily", "brave", "exa"] },
        },
      },
    });

    await waitFor(() => expect(screen.queryByLabelText("Secret")).toBeNull());
    expect(screen.queryByRole("button", { name: "Add a key" })).toBeNull();
  });

  it("does not claim the vault is empty when the vault could not be read", async () => {
    // `GET /secrets` needs `connections:manage`, which a member editing their own
    // agent does not have. The list arrives empty either way, and "no api_key
    // secret in the vault" would be this page inventing a fact about the
    // organization out of a refusal - and calling a stored secret deleted.
    refuse();
    mount(binding({ secret_id: "sec-1" }));

    expect(
      await screen.findByText(/says nothing about what your organization has stored/),
    ).toBeInTheDocument();
    // In the server's own words, because "the vault could not be read" without
    // the reason leaves a member filing a bug about a permission they never had.
    expect(screen.getByText(/connections:manage/)).toBeInTheDocument();
    expect(picker()).toHaveTextContent("The vault could not be read");
    expect(screen.queryByText("No api_key secret in the vault")).not.toBeInTheDocument();
    expect(screen.queryByText(/not in this organization's vault/)).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Store one in the vault" })).not.toBeInTheDocument();
  });

  it("still says nothing is selected when the vault could not be read", async () => {
    // Unlike the two refusals about a *stored* secret, this one is a fact about
    // the spec: it holds whether or not anybody can list the vault, and it is the
    // one that blocks publishing.
    refuse();
    mount(binding());

    // The refusal first, so this is asserted about the settled unreadable state
    // rather than about the moment before the request came back.
    expect(
      await screen.findByText(/says nothing about what your organization has stored/),
    ).toBeInTheDocument();
    expect(screen.getByText(/cannot be published until it has one/)).toBeInTheDocument();
  });

  it("names a stored secret of the wrong kind rather than silently dropping it", async () => {
    // The picker cannot produce this, an imported or hand-written spec can, and
    // filtering by kind is what makes it invisible: the id resolves to a real
    // secret that is not in the list.
    serve([API_KEY_SECRET, AWS_SECRET]);
    mount(binding({ secret_id: "sec-2" }));

    expect(await screen.findByText(/"Ingest role" is of kind aws_credentials/)).toBeInTheDocument();
  });

  it("says a secret that is gone is refused, rather than showing nothing chosen", async () => {
    // Deleting a secret leaves every binding that named it pointing at nothing.
    // "Choose a secret" would read as a decision never made, which is a different
    // problem with a different fix.
    serve([API_KEY_SECRET]);
    mount(binding({ secret_id: "sec-gone" }));

    expect(await screen.findByText(/not in this organization's vault/)).toBeInTheDocument();
  });

  it("does not offer the choice to a viewer who cannot edit", async () => {
    serve([API_KEY_SECRET]);
    mount(binding({ secret_id: "sec-1" }), { disabled: true });

    expect(await screen.findByText("Weather API key")).toBeInTheDocument();
    expect(picker()).toBeDisabled();
  });

  it("wires every label to the control it names, this card included", async () => {
    // The same walk the prop-driven tests do, repeated here because the secret
    // field only exists in this one: a label with no htmlFor reads as decoration
    // to a screen reader and leaves the control it describes unnamed.
    serve([API_KEY_SECRET]);
    const { container } = render(
      <CapabilitySettings
        catalog={[WEATHER]}
        selected={[binding({ secret_id: "sec-1" })]}
        onChange={vi.fn()}
      />,
      { wrapper },
    );
    await screen.findByText("Weather API key");

    const labels = Array.from(container.querySelectorAll<HTMLLabelElement>("label"));

    expect(labels.some((label) => label.textContent === "Secret")).toBe(true);
    for (const label of labels) {
      expect(label.htmlFor, `"${label.textContent}" names no control`).not.toBe("");
      expect(document.getElementById(label.htmlFor)).not.toBeNull();
    }
  });
});

/**
 * Which keys a slot offers, once a key says what it is for.
 *
 * Kind was the only filter, and with eleven `api_key` rows in a real vault that
 * is a list of indistinguishable options where exactly one works. Picking the
 * OpenAI key for a Tavily search stores a spec that publishes cleanly and fails
 * at the first run with an authentication error nobody traces back here.
 */
describe("SecretField · narrowing by what a key is for", () => {
  it("offers the keys for the chosen service and not the others", async () => {
    serve([
      { ...API_KEY_SECRET, id: "sec-tavily", name: "Tavily", purpose: "tavily" },
      { ...API_KEY_SECRET, id: "sec-openai", name: "OpenAI", purpose: "openai" },
    ]);
    mount(binding({ config: { method: "tavily" } }), { definition: SEARCH });

    await userEvent.click(await screen.findByLabelText("Secret"));

    expect(screen.getByRole("option", { name: /Tavily/ })).toBeInTheDocument();
    expect(screen.queryByRole("option", { name: /OpenAI/ })).toBeNull();
  });

  it("keeps offering the keys that never said what they were for", async () => {
    // Every key stored before purposes existed reads as `custom`, and so does
    // every key for a service this deployment does not name. Filtering those
    // out would hide a working Tavily key on the day this shipped.
    serve([{ ...API_KEY_SECRET, id: "sec-old", name: "Search key", purpose: "custom" }]);
    mount(binding({ config: { method: "tavily" } }), { definition: SEARCH });

    await userEvent.click(await screen.findByLabelText("Secret"));

    expect(screen.getByRole("option", { name: /Search key/ })).toBeInTheDocument();
  });

  it("keeps the bound key visible even when it is for something else", async () => {
    // A selection vanishing from its own control, on a spec that was saved and
    // is still valid, reads as data loss whatever the reason for it.
    serve([{ ...API_KEY_SECRET, id: "sec-openai", name: "OpenAI", purpose: "openai" }]);
    mount(binding({ config: { method: "tavily" }, secret_id: "sec-openai" }), {
      definition: SEARCH,
    });

    await waitFor(() => expect(screen.getByLabelText("Secret")).toHaveTextContent("OpenAI"));
  });

  it("draws each key's mark and masked tail, so eleven api_key rows are eleven rows", async () => {
    // The reason narrowing was added at all: a real vault holds a dozen keys of
    // this kind. The purpose that filters the list is also what draws the row.
    serve([
      { ...API_KEY_SECRET, id: "sec-openai", name: "Prod", purpose: "openai" },
      // No purpose at all - stored before purposes existed. It is still offered,
      // and a monogram is what keeps it from being a blank gap.
      { ...API_KEY_SECRET, id: "sec-old", name: "Search key" },
    ]);
    mount(binding());

    await userEvent.click(await screen.findByLabelText("Secret"));

    const marked = screen.getByRole("option", { name: /Prod/ });
    expect(marked.querySelector("svg > title")?.textContent).toBe("OpenAI");
    expect(marked).toHaveTextContent("····P7KD");
    expect(
      screen.getByRole("option", { name: /Search key/ }).querySelector("svg > title"),
    ).toBeNull();
  });

  it("offers every key of the right kind when nothing names a service", async () => {
    // An unconditional requirement - the weather capability - has no field to
    // read a service from, so narrowing would be guessing.
    serve([{ ...API_KEY_SECRET, id: "sec-openai", name: "OpenAI", purpose: "openai" }]);
    mount(binding());

    await userEvent.click(await screen.findByLabelText("Secret"));

    expect(screen.getByRole("option", { name: /OpenAI/ })).toBeInTheDocument();
  });
});
