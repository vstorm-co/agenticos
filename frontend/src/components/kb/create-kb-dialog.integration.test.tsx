import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { CreateKBDialog } from "./create-kb-dialog";
import { apiClient } from "@/lib/api-client";
import { ApiError } from "@/lib/api-error";
import { INGESTION_LIMITS } from "@/lib/ingestion-config";
import { Perm } from "@/types/permissions";
import type { Permission } from "@/types/permissions";
import { providerMarkIn } from "@/test-utils/brand-marks";

/**
 * The Embeddings section of Create knowledge base, as somebody reading it sees it.
 *
 * Both selects here choose something billed to an OpenRouter key, and both used
 * to say so in bare text: "Deployment key", "OpenRouter", `text-embedding-3-large`.
 * The rest of the product draws that choice with the service's own mark, three
 * clicks away in the Builder. `create-kb-dialog.test.tsx` covers what the form
 * posts; this covers what it shows.
 */

vi.mock("@/lib/api-client", () => ({
  apiClient: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() },
}));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

const SECRETS = {
  items: [
    { id: "s-1", name: "OpenRouter prod", hint: "3123", purpose: "openrouter", kind: "api_key" },
    // A key for something else entirely: it must not be offered as one that can
    // pay for embeddings, and its mark must not appear in this select either.
    { id: "s-2", name: "Tavily", hint: "9999", purpose: "tavily", kind: "api_key" },
  ],
  total: 2,
};

/**
 * The same vault plus a key for the *other* embedding provider.
 *
 * Only the provider tests hold it: an OpenAI key in the vault is also what the
 * image-description form reads, and holding one is exactly when that form stops
 * offering to store one - so serving it everywhere would answer a question two
 * tests below are asking.
 */
const SECRETS_WITH_OPENAI = {
  items: [
    ...SECRETS.items,
    { id: "s-3", name: "OpenAI prod", hint: "7777", purpose: "openai", kind: "api_key" },
  ],
  total: 3,
};

const EMBEDDING_MODELS = {
  default: "text-embedding-3-large",
  providers: [
    {
      provider: "openrouter",
      name: "OpenRouter",
      models: [
        { model: "text-embedding-3-large", dim: 3072 },
        { model: "text-embedding-3-small", dim: 1536 },
      ],
    },
    {
      provider: "openai",
      name: "OpenAI",
      models: [{ model: "text-embedding-3-small", dim: 1536 }],
    },
  ],
};

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

/** Open the disclosure the embedding model and its key live behind. */
async function openEmbeddings() {
  await userEvent.click(screen.getByText("Embeddings"));
}

/** Open the disclosure the parser options and the images model live behind. */
async function openParsing() {
  await userEvent.click(screen.getByText("How documents are parsed"));
}

/** What the caller may do, and what their vault holds, per test. */
const state = { permissions: [] as Permission[], secrets: SECRETS };

/**
 * Answer every request the dialog makes.
 *
 * `embeddingModels: "refused"` is the third state the Embeddings section has to
 * draw: with `staleTime: Infinity` the rejection is cached for as long as the
 * dialog lives, so it is not a slow success that eventually arrives.
 */
function serve(embeddingModels: typeof EMBEDDING_MODELS | "refused" = EMBEDDING_MODELS) {
  vi.mocked(apiClient.get).mockImplementation(async (path: string) => {
    if (path === "/secrets") return state.secrets;
    if (path === "/rag/embedding-models") {
      if (embeddingModels === "refused") throw new Error("502 Bad Gateway");
      return embeddingModels;
    }
    // The images section reads the caller's permissions, the provider catalog
    // and what each provider publishes. Answering a list shape at
    // `/me/permissions` is not "no permissions", it is a `TypeError`.
    if (path === "/me/permissions")
      return {
        organization_id: "org-1",
        role: "builder",
        is_app_admin: false,
        permissions: state.permissions.map((permission) => ({ permission, scope: "all" })),
      };
    if (path === "/providers/catalog")
      return {
        items: [
          {
            id: "openai",
            name: "OpenAI",
            secret_kind: "api_key",
            supports_base_url: false,
            keyless: false,
          },
        ],
        total: 1,
      };
    if (path === "/secrets/purposes")
      return {
        items: [
          {
            id: "openai",
            label: "OpenAI",
            category: "model_provider",
            kind: "api_key",
            help_url: null,
            description: "OpenAI keys",
          },
        ],
        total: 1,
      };
    if (path === "/providers/openai/models") return { items: [], total: 0, source: null };
    return { items: [], total: 0 };
  });
}

/** Mount the dialog. Called by each test, so a test can set the caller up first. */
function show() {
  render(<CreateKBDialog open onOpenChange={vi.fn()} />, { wrapper });
}

beforeEach(() => {
  vi.clearAllMocks();
  state.permissions = [Perm.connectionsManage, Perm.secretsEdit];
  state.secrets = SECRETS;
  serve();
});

describe("the embedding key picker", () => {
  it("draws the mark for every key it offers, and its masked tail", async () => {
    show();
    await openEmbeddings();
    await userEvent.click(screen.getByLabelText("Key"));

    const key = await screen.findByRole("option", { name: /OpenRouter prod/ });
    expect(providerMarkIn(key)).toBe("openrouter");
    expect(key).toHaveTextContent("····3123");
  });

  it("offers no deployment key, because there is none", async () => {
    // Every collection pays with a vault key of its own. The row that used to
    // read "Deployment key" offered a collection that embedded on a variable
    // the operator set once for everybody, which is what this removed.
    show();
    await openEmbeddings();
    expect(screen.getByLabelText("Key")).toHaveTextContent("Choose a key");
    await userEvent.click(screen.getByLabelText("Key"));

    expect(screen.queryByRole("option", { name: /Deployment key/ })).toBeNull();
  });

  it("offers no key that cannot pay for embeddings", async () => {
    show();
    await openEmbeddings();
    await userEvent.click(screen.getByLabelText("Key"));

    expect(screen.queryByRole("option", { name: /Tavily/ })).toBeNull();
  });

  it("shows the selected key's mark on the closed trigger", async () => {
    show();
    await openEmbeddings();
    await userEvent.click(screen.getByLabelText("Key"));
    await userEvent.click(await screen.findByRole("option", { name: /OpenRouter prod/ }));

    expect(providerMarkIn(screen.getByLabelText("Key"))).toBe("openrouter");
  });
});

describe("the embedding model picker", () => {
  it("names the model the collection would be created with", async () => {
    // The one choice in this dialog that cannot be revisited - the vector column
    // is created at the model's width - and the trigger used to sit on its
    // placeholder for as long as the dialog was open. Mounting a controlled
    // Radix select before its options exist writes the value onto a hidden
    // native `<select>` with no matching `<option>`, reads `""` back out of the
    // change event, and hands that to `onValueChange`, which is `setState`.
    show();
    await openEmbeddings();

    expect(await screen.findByLabelText("Model")).toHaveTextContent("text-embedding-3-large");
    expect(screen.queryByText("Loading models…")).toBeNull();
  });

  it("says the list is still loading rather than offering an empty picker", () => {
    // Asserted before the query resolves, which is the state the placeholder is
    // for: no select at all, because one whose value arrives after its options
    // is the bug above.
    show();

    expect(screen.getByText("Loading models…")).toBeInTheDocument();
    expect(screen.queryByLabelText("Model")).toBeNull();
  });

  it("draws the mark of the key that pays, beside every model id", async () => {
    show();
    await openEmbeddings();
    await userEvent.click(screen.getByLabelText("Model"));

    expect(
      providerMarkIn(await screen.findByRole("option", { name: /text-embedding-3-small/ })),
    ).toBe("openrouter");
  });

  it("says which model an untouched deployment would use, in the list", async () => {
    show();
    await openEmbeddings();
    await userEvent.click(screen.getByLabelText("Model"));

    const preselected = await screen.findByRole("option", { name: /text-embedding-3-large/ });
    expect(preselected).toHaveTextContent("deployment default");
  });
});

/**
 * Whose endpoint serves the model, which used to be nobody's choice: every
 * request went to openrouter.ai, hardcoded, whatever key the collection had.
 */
describe("choosing the provider", () => {
  beforeEach(() => {
    state.secrets = SECRETS_WITH_OPENAI;
  });

  it("offers only the models the chosen provider serves", async () => {
    show();
    await openEmbeddings();
    await userEvent.click(await screen.findByLabelText("Embedding provider"));
    await userEvent.click(await screen.findByRole("option", { name: "OpenAI" }));
    await userEvent.click(screen.getByLabelText("Model"));

    expect(await screen.findByRole("option", { name: /text-embedding-3-small/ })).toBeVisible();
    expect(screen.queryByRole("option", { name: /text-embedding-3-large/ })).toBeNull();
  });

  it("offers only the keys that provider will accept", async () => {
    show();
    await openEmbeddings();
    await userEvent.click(await screen.findByLabelText("Embedding provider"));
    await userEvent.click(await screen.findByRole("option", { name: "OpenAI" }));
    await userEvent.click(screen.getByLabelText("Key"));

    expect(await screen.findByRole("option", { name: /OpenAI prod/ })).toBeVisible();
    expect(screen.queryByRole("option", { name: /OpenRouter prod/ })).toBeNull();
  });

  it("forgets a key chosen for the provider being left behind", async () => {
    // A key is a key for a provider: an OpenRouter key sent to OpenAI's address
    // is refused after it has already arrived. Moving the provider empties the
    // key select rather than carrying the wrong key over to be refused on save.
    show();
    await openEmbeddings();
    await userEvent.click(screen.getByLabelText("Key"));
    await userEvent.click(await screen.findByRole("option", { name: /OpenRouter prod/ }));
    await userEvent.click(await screen.findByLabelText("Embedding provider"));
    await userEvent.click(await screen.findByRole("option", { name: "OpenAI" }));

    expect(screen.getByLabelText("Key")).toHaveTextContent("Choose a key");
  });

  it("puts a refusal about the key under the picker rather than in a toast", async () => {
    // The server is the authority on whether a collection may be created without
    // a key - there is no deployment key to fall back to, so it refuses on the
    // field - and the refusal has to land where the empty select is.
    vi.mocked(apiClient.post).mockRejectedValueOnce(
      new ApiError(400, "Choose the vault key that pays", {
        error: {
          code: "BAD_REQUEST",
          message: "Choose the vault key that pays",
          details: {
            fields: [{ field: "embedding_secret_id", message: "Choose the vault key that pays" }],
          },
        },
      }),
    );
    show();
    await openEmbeddings();
    await userEvent.type(screen.getByLabelText("Name"), "Handbook");
    await userEvent.click(screen.getByRole("button", { name: "Create" }));

    expect(await screen.findByText("Choose the vault key that pays")).toBeInTheDocument();
  });

  it("posts the provider, its key and the model the provider serves", async () => {
    show();
    await openEmbeddings();
    await userEvent.click(await screen.findByLabelText("Embedding provider"));
    await userEvent.click(await screen.findByRole("option", { name: "OpenAI" }));
    await userEvent.click(screen.getByLabelText("Key"));
    await userEvent.click(await screen.findByRole("option", { name: /OpenAI prod/ }));
    await userEvent.type(screen.getByLabelText("Name"), "Handbook");
    await userEvent.click(screen.getByRole("button", { name: "Create" }));

    await waitFor(() => expect(apiClient.post).toHaveBeenCalled());
    const body = vi.mocked(apiClient.post).mock.calls.at(-1)?.[1] as Record<string, unknown>;
    expect(body.embedding_provider).toBe("openai");
    expect(body.embedding_secret_id).toBe("s-3");
    // The deployment default is 3072-wide and OpenAI's entry here serves only the
    // 1536 one, so the model has to move with the provider - posting the default
    // would create a column the provider cannot fill.
    expect(body.embedding_model).toBe("text-embedding-3-small");
  });
});

/**
 * Three states, not two.
 *
 * The section said "Loading models…" whether the request was in flight or had
 * been refused. After the client's one retry the query is settled in error for
 * the life of the dialog, so that sentence described something that was not
 * going to happen - and the model is frozen at creation, the vector column
 * being made at its width, so it is the one choice here nobody can revisit.
 */
describe("when the embedding model list cannot be read", () => {
  beforeEach(() => {
    // The same dialog against a refused list. `serve` is called again because
    // the suite-wide `beforeEach` has already answered everything; `show` is
    // called here rather than per test, since every test in this block wants
    // the same refused mount.
    cleanup();
    vi.clearAllMocks();
    state.permissions = [Perm.connectionsManage, Perm.secretsEdit];
    serve("refused");
    show();
  });

  it("says the list was refused rather than that it is still coming", async () => {
    await openEmbeddings();

    expect(await screen.findByText(/The list of providers could not be read/)).toBeInTheDocument();
    expect(screen.queryByText("Loading models…")).toBeNull();
  });

  it("says that creating will be refused, since no provider or key can be chosen", async () => {
    // There is no deployment default to fall back to: without the list nobody
    // can name a provider or a key, and the server refuses a collection that
    // names neither. Being told that is the difference between a choice not
    // offered and a refusal discovered on submit.
    await openEmbeddings();

    expect(await screen.findByText(/will be refused until it can/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Create" })).toBeInTheDocument();
  });

  it("offers no model picker to choose from a list it does not have", async () => {
    await openEmbeddings();
    await screen.findByText(/could not be read/);

    expect(screen.queryByLabelText("Model")).toBeNull();
  });
});

describe("the two keys this dialog can store", () => {
  /**
   * On a fresh deployment both offers appear at once - an embedding key in the
   * Embeddings section and a model-provider key in the describing-model form,
   * four inches apart, writing different secrets under different purposes. Both
   * were labelled "Add a key", so a screen reader heard the same button twice
   * and a test could only tell them apart by DOM position.
   */

  it("names each of them, so neither of them is just 'a key'", async () => {
    show();
    await openEmbeddings();
    await openParsing();
    await userEvent.click(screen.getByLabelText("Describe images"));
    await userEvent.click(await screen.findByLabelText("Provider"));
    await userEvent.click(screen.getByRole("option", { name: /OpenAI/ }));

    // Two offers, and the accessible name is what tells them apart - not the
    // section each happens to sit in.
    expect(
      screen.getByRole("button", { name: "Add a key: OpenRouter (embeddings)" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Add a key: OpenAI" })).toBeInTheDocument();
  });

  it("offers neither to a caller who may not write to the vault", async () => {
    // `collections:edit` is what opens this dialog; storing the embedding key is
    // `secrets:edit`, and a member holding the first and not the second was shown
    // both forms and refused by `POST /secrets` after pasting a key in (#361).
    state.permissions = [Perm.connectionsManage];
    show();
    await openEmbeddings();
    await openParsing();
    await userEvent.click(screen.getByLabelText("Describe images"));
    await userEvent.click(await screen.findByLabelText("Provider"));
    await userEvent.click(screen.getByRole("option", { name: /OpenAI/ }));

    expect(screen.queryByRole("button", { name: "Add a key: OpenRouter (embeddings)" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Add a key: OpenAI" })).toBeNull();
    // Two sentences, not silence, one per offer: the inline form says it here,
    // and the model panel says it in its own words because a disabled Add model
    // with nothing beside it explains nothing.
    expect(screen.getAllByText(/permission you do not hold/)).toHaveLength(2);
  });
});

describe("the image-description prompt", () => {
  it("is a markdown editor in this dialog too, not a bare textarea", async () => {
    // The regression that matters: the field is easy to swap back, and it is a
    // model prompt several sentences long - the same control the Builder uses
    // for an agent's instructions (#940). `IngestionSettings` is embedded whole
    // here, so this dialog and the standalone one get it or neither does.
    show();
    await openEmbeddings();
    await openParsing();
    await userEvent.click(screen.getByLabelText("Describe images"));

    const prompt = await screen.findByLabelText("Prompt");
    expect(prompt).toBeVisible();
    expect(screen.getByRole("button", { name: "Preview" })).toBeVisible();
    expect(screen.getByRole("button", { name: "Source" })).toBeVisible();
  });

  it("still caps what can be typed at the length the API enforces", async () => {
    // Swapping the control must not drop the bound: a field the server refuses
    // should not let somebody write past it and find out on submit.
    show();
    await openEmbeddings();
    await openParsing();
    await userEvent.click(screen.getByLabelText("Describe images"));

    expect(await screen.findByLabelText("Prompt")).toHaveAttribute(
      "maxlength",
      String(INGESTION_LIMITS.prompt.maxLength),
    );
  });
});
