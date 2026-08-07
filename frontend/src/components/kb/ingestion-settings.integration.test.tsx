import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { IngestionSettings } from "./ingestion-settings";
import { apiClient } from "@/lib/api-client";
import { DEFAULT_INGESTION_CONFIG } from "@/lib/ingestion-config";
import { Perm } from "@/types/permissions";
import type { Permission } from "@/types/permissions";
import type { ModelProfile, ProviderInfo } from "@/types/providers";
import type { Secret, SecretPurpose } from "@/types/secrets";

/**
 * The model that reads the pictures, in the dialog where a collection is made.
 *
 * `ingestion-settings.test.tsx` covers the form's own decisions with the API
 * answering nothing. This asserts the one part of it that is somebody else's
 * component: the control that picks the describing model is the same one the
 * Builder uses - provider, model and a key stored inline - and not the bare
 * list of saved profiles it used to be, which on a fresh deployment was a
 * dashed box saying the organization has no models and offering no way to make
 * one.
 *
 * What it must *not* be is the Builder's panel entire. Deleting a model profile
 * from here would take it out from under every agent pointed at it, from a form
 * about one collection.
 */

vi.mock("@/lib/api-client", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api-client")>("@/lib/api-client");
  return {
    ...actual,
    apiClient: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() },
  };
});
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

const OPENAI: ProviderInfo = {
  id: "openai",
  name: "OpenAI",
  secret_kind: "api_key",
  supports_base_url: true,
  keyless: true,
};

const PURPOSE: SecretPurpose = {
  id: "openai",
  label: "OpenAI",
  category: "model_provider",
  kind: "api_key",
  help_url: null,
  description: "OpenAI keys",
};

function profile(overrides: Partial<ModelProfile> = {}): ModelProfile {
  return {
    id: "p1",
    label: "vision",
    provider: "openai",
    model: "gpt-4.1",
    secret_id: null,
    params: {},
    allow_byo: false,
    fallback_profile_ids: [],
    ...overrides,
  };
}

const state = {
  profiles: [] as ModelProfile[],
  secrets: [] as Secret[],
  permissions: [] as Permission[],
};

/** The vault, the provider catalog and the caller, as this control reads them. */
function serve() {
  vi.mocked(apiClient.get).mockImplementation(async (path: string) => {
    if (path === "/me/permissions")
      return {
        organization_id: "org-1",
        role: "member",
        is_app_admin: false,
        permissions: state.permissions.map((permission) => ({ permission, scope: "all" })),
      };
    if (path === "/providers/model-profiles")
      return { items: state.profiles, total: state.profiles.length };
    if (path === "/providers/catalog") return { items: [OPENAI], total: 1 };
    if (path === "/secrets") return { items: state.secrets, total: state.secrets.length };
    if (path === "/secrets/purposes") return { items: [PURPOSE], total: 1 };
    if (path === "/secrets/kinds") return { items: [], total: 0 };
    if (path === "/providers/openai/models")
      return { items: [{ id: "gpt-5", name: "GPT-5" }], total: 1, source: "live" };
    throw new Error(`unexpected GET ${path}`);
  });
}

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

/** The form with image description switched on, which is what renders the picker. */
function show(modelProfileId: string | null = null, disabled = false) {
  render(
    <IngestionSettings
      idPrefix="test"
      value={{
        ...DEFAULT_INGESTION_CONFIG,
        describe_images: true,
        image_description: {
          ...DEFAULT_INGESTION_CONFIG.image_description,
          model_profile_id: modelProfileId,
        },
      }}
      onChange={vi.fn()}
      disabled={disabled}
    />,
    { wrapper },
  );
}

/** The form with LlamaParse chosen, which is what renders its key picker. */
function showLlamaParse() {
  render(
    <IngestionSettings
      idPrefix="test"
      value={{ ...DEFAULT_INGESTION_CONFIG, pdf_parser: "llamaparse" }}
      onChange={vi.fn()}
    />,
    { wrapper },
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  state.profiles = [profile()];
  state.secrets = [];
  state.permissions = [Perm.collectionsEdit, Perm.connectionsManage, Perm.secretsEdit];
  serve();
});

describe("the model that describes the images", () => {
  it("asks for a provider, a model and a key rather than listing what exists", async () => {
    show();

    expect(await screen.findByLabelText("Provider")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Add model" })).toBeInTheDocument();
  });

  it("is not a dead end on a deployment with no models at all", async () => {
    // What the bare list rendered here: a dashed box saying the organization has
    // no models, in a dialog whose only remaining action was Cancel.
    state.profiles = [];
    show();

    expect(await screen.findByLabelText("Provider")).toBeInTheDocument();
    expect(screen.queryByText(/no models yet/)).toBeNull();
  });

  it("offers to store the missing key here instead of naming the page that holds it", async () => {
    // The provider has no key in the vault, and the answer to that is a form.
    // Sending somebody to the Vault and back is the flow this control replaced
    // everywhere else, and this dialog was the one place still describing it.
    show();

    await userEvent.click(await screen.findByLabelText("Provider"));
    await userEvent.click(screen.getByRole("option", { name: /OpenAI/ }));

    expect(screen.getByText(/No OpenAI key in the vault yet/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Add a key: OpenAI" })).toBeInTheDocument();
  });

  it("offers no such form to a caller who may not write to the vault", async () => {
    // `connections:manage` lets somebody define the model; storing the key it
    // runs on is `secrets:edit`, and this dialog is the second surface that
    // renders the form - gating it in the Builder alone would have left this one
    // offering a write that answers 403.
    state.permissions = [Perm.collectionsEdit, Perm.connectionsManage];
    show();

    await userEvent.click(await screen.findByLabelText("Provider"));
    await userEvent.click(screen.getByRole("option", { name: /OpenAI/ }));

    expect(screen.queryByRole("button", { name: "Add a key: OpenAI" })).toBeNull();
    expect(screen.getByText(/permission you do not hold/)).toBeInTheDocument();
  });

  it("stores no key while the dialog that holds it is frozen", async () => {
    // The form disables its submit on `disabled` and used to stop there, which
    // was harmless while this panel was a list of radios. It is not now: the
    // key field writes an organization-wide vault secret, and a dialog mid-save
    // did not mean "except the vault".
    show(null, true);

    await userEvent.click(await screen.findByLabelText("Provider"));
    await userEvent.click(screen.getByRole("option", { name: /OpenAI/ }));

    expect(screen.getByRole("button", { name: "Add a key: OpenAI" })).toBeDisabled();
  });

  it("says the chosen model has no key, which is what decides whether ingestion runs", async () => {
    show("p1");

    const current = await screen.findByRole("group", { name: "Current model" });
    expect(within(current).getByText("vision")).toBeInTheDocument();
    expect(within(current).getByText("no key")).toBeInTheDocument();
  });

  it("drops the badge once the model is keyed", async () => {
    state.profiles = [profile({ secret_id: "s-1" })];
    show("p1");

    const current = await screen.findByRole("group", { name: "Current model" });
    expect(within(current).queryByText("no key")).toBeNull();
  });

  it("offers no form to somebody who may edit the collection but not add a model", async () => {
    // `POST /providers/model-profiles` is `connections:manage`, which a
    // collection editor need not hold. Rendering the form for them would be a
    // 403 dressed as a control; the list of what already exists is the honest
    // answer, and it is what this panel showed everybody before.
    state.permissions = [Perm.collectionsEdit];
    show();

    await waitFor(() => expect(screen.getByRole("radio", { name: "vision" })).toBeInTheDocument());
    expect(screen.queryByLabelText("Provider")).toBeNull();
    expect(screen.queryByRole("button", { name: "Add model" })).toBeNull();
  });

  it("cannot delete a model every agent in the organization may be pointed at", async () => {
    // The reason this passes `allowAdd` and not `allowRemove`. A collection form
    // may create a model and a key; destroying an organization-wide profile is a
    // bigger claim than it makes, and the Builder is where that lives.
    show();

    await waitFor(() => expect(screen.getByText("Use a saved model (1)")).toBeInTheDocument());
    expect(screen.queryByRole("button", { name: /^Remove/ })).toBeNull();
  });
});

describe("the LlamaParse key", () => {
  /**
   * The second vault write this panel offers, and a different one: it says whose
   * account each parse is billed to. It reads the same permission as every other
   * one - `POST /secrets` is `secrets:edit` whichever form posted it - and until
   * #361 it asked nobody.
   */

  it("can be stored here rather than in another tab", async () => {
    showLlamaParse();

    expect(
      await screen.findByRole("button", { name: "Add a key: LlamaParse" }),
    ).toBeInTheDocument();
  });

  it("is not offered to a caller who may not write to the vault", async () => {
    state.permissions = [Perm.collectionsEdit];
    showLlamaParse();

    // The picker itself stays - the deployment's own key is still a choice
    // somebody with `collections:edit` may make - and only the write goes.
    expect(await screen.findByLabelText("LlamaParse key")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Add a key: LlamaParse" })).toBeNull();
    expect(screen.getByText(/permission you do not hold/)).toBeInTheDocument();
  });
});
