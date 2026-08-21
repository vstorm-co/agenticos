import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactElement } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { toast } from "sonner";

import { SyncSourceWizard } from "./sync-source-wizard";
import { apiClient } from "@/lib/api-client";
import { ApiError } from "@/lib/api-error";
import type { ConnectorInfo, SyncSourceCreate } from "@/lib/rag-api";
import type { KBScope } from "@/types/knowledge-base";

vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));
vi.mock("@/lib/api-client", () => ({
  apiClient: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() },
}));

/** A service-account credential in the organization's vault, as `/secrets` lists one. */
const DRIVE_CREDENTIAL = {
  id: "secret-1",
  name: "Drive service account",
  kind: "gcp_service_account",
  purpose: "custom",
  hint: "a1b2",
  visibility: "org",
  created_at: "2026-08-20T00:00:00Z",
};

/**
 * The credential step reads the vault and the caller's permissions, so both are
 * served rather than left to a rejected query - an empty picker and a refused
 * one look the same on screen and mean different things.
 */
function serve({ secrets = [DRIVE_CREDENTIAL], permissions = ["secrets:view"] } = {}) {
  vi.mocked(apiClient.get).mockImplementation(async (path: string) => {
    if (path === "/secrets") return { items: secrets, total: secrets.length };
    if (path === "/me/permissions")
      return {
        organization_id: "org-1",
        role: "builder",
        is_app_admin: false,
        permissions: permissions.map((permission) => ({ permission, scope: "all" })),
      };
    return {};
  });
}

function withQuery(ui: ReactElement) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const view = render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>);
  // The provider has to survive a rerender: the credential step reads the vault
  // through react-query, and a rerender that dropped the provider would throw
  // where the test means to assert about the dialog.
  return {
    ...view,
    rerender: (next: ReactElement) =>
      view.rerender(<QueryClientProvider client={client}>{next}</QueryClientProvider>),
  };
}

beforeEach(() => {
  vi.mocked(toast.error).mockClear();
  serve();
});

/**
 * Which collection the wizard says it will fill.
 *
 * The picker used to require `defaultCollection` to be absent *and*
 * `collections` to be non-empty, and no call site could satisfy both - so a
 * source added from `/rag`, where the sync tab lists the whole organization's
 * sources rather than one collection's, went to whichever collection the
 * sidebar happened to have selected and nothing on screen said which (#434).
 *
 * These drive it the way the three call sites really do: a list of several with
 * a default (`/rag`), a list of one (`kb/[id]`), and none at all (the org
 * integration list).
 */

const CONNECTOR: ConnectorInfo = {
  type: "gdrive",
  name: "Google Drive",
  enabled: true,
  // Nothing required, so the configure step can be walked straight past to the
  // schedule step the picker lives on.
  config_schema: {},
  secret_kind: "none",
};

/** Walk the wizard from its first step to the last, where the collection is chosen. */
async function openScheduleStep(props: {
  collections: { name: string; scope: KBScope }[];
  defaultCollection?: string;
  onSubmit: (data: SyncSourceCreate) => void;
}) {
  withQuery(
    <SyncSourceWizard
      open
      onOpenChange={vi.fn()}
      connectors={[CONNECTOR]}
      collections={props.collections}
      defaultCollection={props.defaultCollection}
      onSubmit={props.onSubmit}
    />,
  );
  await userEvent.type(screen.getByLabelText("Source name"), "Engineering docs");
  await userEvent.click(screen.getByRole("button", { name: /Google Drive/ }));
  await userEvent.click(screen.getByRole("button", { name: /Continue/ }));
  // Configure, then the credential step. This connector needs no credential, so
  // it advances with nothing chosen.
  await userEvent.click(screen.getByRole("button", { name: /Continue/ }));
  await userEvent.click(screen.getByRole("button", { name: /Continue/ }));
  await screen.findByText("Sync mode");
}

describe("the sync wizard's target collection", () => {
  it("is on screen, and starts on the one the caller suggested", async () => {
    await openScheduleStep({
      collections: [
        { name: "handbook", scope: "org" },
        { name: "contracts", scope: "personal" },
      ],
      defaultCollection: "contracts",
      onSubmit: vi.fn(),
    });

    expect(screen.getByText("Target collection")).toBeVisible();
    // Radix draws the chosen item's text in the closed trigger, so this is the
    // seed being visible rather than the list being open.
    expect(screen.getByRole("combobox")).toHaveTextContent("contracts");
  });

  it("files the source under the collection that was chosen, not the suggestion", async () => {
    const onSubmit = vi.fn();
    await openScheduleStep({
      collections: [
        { name: "handbook", scope: "org" },
        { name: "contracts", scope: "personal" },
      ],
      defaultCollection: "contracts",
      onSubmit,
    });

    await userEvent.click(screen.getByRole("combobox"));
    await userEvent.click(await screen.findByRole("option", { name: "handbook" }));
    await userEvent.click(screen.getByRole("button", { name: /Create source/ }));

    expect(onSubmit).toHaveBeenCalledWith(expect.objectContaining({ collection_name: "handbook" }));
  });

  it("offers no choice when the caller offered one collection", async () => {
    // `kb/[id]`, whose sources belong to that base and nowhere else.
    const onSubmit = vi.fn();
    await openScheduleStep({
      collections: [{ name: "org_handbook", scope: "org" }],
      defaultCollection: "org_handbook",
      onSubmit,
    });

    expect(screen.queryByText("Target collection")).toBeNull();

    await userEvent.click(screen.getByRole("button", { name: /Create source/ }));
    expect(onSubmit).toHaveBeenCalledWith(
      expect.objectContaining({ collection_name: "org_handbook" }),
    );
  });

  it("leaves an org-level integration unassigned when none was offered", async () => {
    // `reusable-integrations.tsx` passes an empty list on purpose: filing this
    // under a knowledge base is the one thing that list is not for.
    const onSubmit = vi.fn();
    await openScheduleStep({ collections: [], onSubmit });

    expect(screen.queryByText("Target collection")).toBeNull();

    await userEvent.click(screen.getByRole("button", { name: /Create source/ }));
    expect(onSubmit).toHaveBeenCalledWith(expect.objectContaining({ collection_name: null }));
  });
});

/**
 * The wizard says who will be able to read what the source ingests.
 *
 * Access is decided at the collection and there is no per-document isolation
 * inside one, so the pair - this credential, that collection - *is* the decision.
 * The wizard used to make it in silence, which is #982: a token issued for a
 * whole Confluence instance, pointed at an `org` collection, published the
 * instance to every member holding `collections:view` and no step said a word.
 */
describe("the audience of what a source ingests", () => {
  it("is stated on the step that decides it, even where the collection is pinned", async () => {
    // The issue's own repro: `kb/[id]` offers one collection, so there is no
    // picker - which is exactly why the sentence cannot be conditional on one.
    await openScheduleStep({
      collections: [{ name: "org_handbook", scope: "org" }],
      defaultCollection: "org_handbook",
      onSubmit: vi.fn(),
    });

    expect(screen.getByText("Who will be able to read this")).toBeVisible();
    // This connector authenticates with nothing, so the sentence describes what
    // the source ingests rather than a credential it does not have.
    expect(
      screen.getByText(/everyone in this organization who can view that collection/),
    ).toHaveTextContent("Everything this source ingests becomes searchable in org_handbook");
  });

  it("follows the picker, so a personal collection reads differently", async () => {
    await openScheduleStep({
      collections: [
        { name: "handbook", scope: "org" },
        { name: "contracts", scope: "personal" },
      ],
      defaultCollection: "handbook",
      onSubmit: vi.fn(),
    });

    expect(screen.getByText(/who can view that collection/)).toBeVisible();

    await userEvent.click(screen.getByRole("combobox"));
    await userEvent.click(await screen.findByRole("option", { name: "contracts" }));

    expect(screen.getByText(/by you alone/)).toHaveTextContent("contracts");
    expect(screen.queryByText(/who can view that collection/)).toBeNull();
  });

  it("names the credential that was chosen", async () => {
    const view = withQuery(wizard(vi.fn()));
    await userEvent.type(screen.getByLabelText("Source name"), "Engineering docs");
    await userEvent.click(screen.getByRole("button", { name: /Google Drive/ }));
    await userEvent.click(screen.getByRole("button", { name: /Continue/ }));
    await userEvent.type(screen.getByLabelText(/Google Drive Folder ID/), "1AbC_-def");
    await userEvent.click(screen.getByRole("button", { name: /Continue/ }));
    await pickTheCredential();
    await userEvent.click(screen.getByRole("button", { name: /Continue/ }));

    expect(await screen.findByText(/Drive service account/)).toHaveTextContent("handbook");
    view.unmount();
  });

  it("says an unassigned org integration can be searched by nobody yet", async () => {
    await openScheduleStep({ collections: [], onSubmit: vi.fn() });

    expect(screen.getByText(/filed under no knowledge base yet/)).toBeVisible();
  });

  it("reads the vault only once somebody is looking at the sentence", async () => {
    // The knowledge-base page mounts this wizard whether or not it is open, so a
    // vault read in the wizard's own body ran on every page load - including for
    // members holding no `secrets:view`, who get a refusal for it, retried.
    vi.mocked(apiClient.get).mockClear();
    withQuery(
      <SyncSourceWizard
        open={false}
        onOpenChange={vi.fn()}
        connectors={[GDRIVE]}
        collections={[{ name: "org_handbook", scope: "org" }]}
        defaultCollection="org_handbook"
        onSubmit={vi.fn()}
      />,
    );

    expect(vi.mocked(apiClient.get).mock.calls.map(([path]) => path)).not.toContain("/secrets");
  });

  it("is stated for a clone too, which repoints somebody else's credential", async () => {
    // A clone references the same vault secret and names a different collection,
    // so the audience changes while nothing about the credential does - and it
    // is the only way to change one from this product's own UI.
    withQuery(
      <SyncSourceWizard
        open
        onOpenChange={vi.fn()}
        connectors={[GDRIVE]}
        collections={[{ name: "org_handbook", scope: "org" }]}
        defaultCollection="org_handbook"
        orgIntegrations={[
          {
            id: "src-1",
            organization_id: "org-1",
            name: "Company Drive",
            connector_type: "gdrive",
            collection_name: null,
            config: {},
            secret_id: DRIVE_CREDENTIAL.id,
            secret_hint: DRIVE_CREDENTIAL.hint,
            sync_mode: "full",
            schedule_minutes: null,
            is_active: true,
            last_sync_at: null,
            last_sync_status: null,
            last_error: null,
            created_at: null,
          },
        ]}
        onSubmit={vi.fn()}
        onClone={vi.fn()}
      />,
    );

    await userEvent.click(screen.getByRole("button", { name: /Use existing/ }));
    // Nothing is said before a source is picked: there is no credential to name.
    expect(screen.queryByText("Who will be able to read this")).toBeNull();

    await userEvent.click(screen.getByRole("button", { name: /Company Drive/ }));

    expect(await screen.findByText(/Drive service account/)).toHaveTextContent("org_handbook");
  });
});

/**
 * A connector with something to configure, so there is an input to mark.
 *
 * Three fields rather than one on purpose: the defect this covers is not that
 * the refusal went missing - it was in a toast - but that with four inputs on
 * screen a sentence about one of them says nothing about which (#897).
 */
const GDRIVE: ConnectorInfo = {
  type: "gdrive",
  name: "Google Drive",
  enabled: true,
  config_schema: {
    folder_id: { type: "string", required: true, label: "Google Drive Folder ID" },
    include_subfolders: { type: "boolean", required: false, label: "Include subfolders" },
  },
  // The credential is a vault secret this source references, not a field it
  // carries - so it is not in `config_schema` any more (#937).
  secret_kind: "gcp_service_account",
};

const FOLDER_ID_REFUSED = "A Google Drive folder ID may contain only letters, digits, '-' and '_'.";

/** The 400 the create route answers, envelope and all. */
function refusal(details: Record<string, unknown>): ApiError {
  return new ApiError(400, "Invalid connector config", {
    error: { code: "BAD_REQUEST", message: "Invalid connector config", details },
  });
}

function wizard(onSubmit: (data: SyncSourceCreate) => Promise<void>, open = true) {
  return (
    <SyncSourceWizard
      open={open}
      onOpenChange={vi.fn()}
      connectors={[GDRIVE]}
      collections={[{ name: "handbook", scope: "org" }]}
      defaultCollection="handbook"
      onSubmit={onSubmit}
    />
  );
}

/** Fill the configure step in full and press Create source on the step after it. */
async function submitConfigured(onSubmit: (data: SyncSourceCreate) => Promise<void>) {
  const view = withQuery(wizard(onSubmit));
  await userEvent.type(screen.getByLabelText("Source name"), "Engineering docs");
  await userEvent.click(screen.getByRole("button", { name: /Google Drive/ }));
  await userEvent.click(screen.getByRole("button", { name: /Continue/ }));
  await userEvent.type(screen.getByLabelText(/Google Drive Folder ID/), "x' in parents");
  await userEvent.click(screen.getByRole("button", { name: /Continue/ }));
  await pickTheCredential();
  await userEvent.click(screen.getByRole("button", { name: /Continue/ }));
  await userEvent.click(screen.getByRole("button", { name: /Create source/ }));
  return view;
}

/** Choose the one credential the vault holds, on the step that asks for it. */
async function pickTheCredential() {
  await userEvent.click(await screen.findByLabelText(/Vault credential/));
  await userEvent.click(await screen.findByRole("option", { name: /Drive service account/ }));
}

describe("a config the connector refuses", () => {
  it("marks the input the server named, on the step that holds it", async () => {
    const onSubmit = vi.fn().mockRejectedValue(
      refusal({
        connector_type: "gdrive",
        fields: [{ field: "config.folder_id", message: FOLDER_ID_REFUSED }],
      }),
    );

    await submitConfigured(onSubmit);

    const folderId = await screen.findByLabelText(/Google Drive Folder ID/);
    expect(folderId).toHaveAttribute("aria-invalid", "true");
    expect(screen.getByText(FOLDER_ID_REFUSED)).toBeVisible();
    // The other input on this step is not implicated, and saying so would send
    // somebody to rewrite a value that was accepted.
    expect(screen.getByLabelText(/Include subfolders/)).not.toHaveAttribute("aria-invalid");
    // Marked instead of announced: a toast is not beside anything.
    expect(toast.error).not.toHaveBeenCalled();
  });

  it("announces what belongs to no input rather than losing it", async () => {
    // A connector is entitled to refuse a config without blaming one field of
    // it, and there is nowhere on the form for that to land.
    const onSubmit = vi.fn().mockRejectedValue(refusal({ connector_type: "gdrive", fields: [] }));

    await submitConfigured(onSubmit);

    expect(toast.error).toHaveBeenCalledWith("Invalid connector config");
    expect(screen.getByText("Sync mode")).toBeVisible();
  });

  it("marks what the second attempt was refused for, not what the first was", async () => {
    const onSubmit = vi
      .fn()
      .mockRejectedValueOnce(
        refusal({ fields: [{ field: "config.folder_id", message: FOLDER_ID_REFUSED }] }),
      )
      .mockRejectedValueOnce(
        refusal({ fields: [{ field: "secret_id", message: "That is not a service account." }] }),
      );

    await submitConfigured(onSubmit);
    expect(await screen.findByLabelText(/Google Drive Folder ID/)).toHaveAttribute(
      "aria-invalid",
      "true",
    );

    await userEvent.type(screen.getByLabelText(/Google Drive Folder ID/), "1AbC");
    await userEvent.click(screen.getByRole("button", { name: /Continue/ }));
    await userEvent.click(screen.getByRole("button", { name: /Continue/ }));
    await userEvent.click(screen.getByRole("button", { name: /Create source/ }));

    // The mark follows the field to whichever step holds it, and the credential
    // is a step of its own since #937.
    expect(await screen.findByLabelText(/Vault credential/)).toHaveAttribute(
      "aria-invalid",
      "true",
    );
    expect(screen.queryByText(FOLDER_ID_REFUSED)).toBeNull();
  });

  it("stops marking an input the moment it is edited", async () => {
    // A refusal about a value that has since been changed is a refusal about
    // nothing, and the rest of this product's forms drop it here too.
    const onSubmit = vi
      .fn()
      .mockRejectedValue(
        refusal({ fields: [{ field: "config.folder_id", message: FOLDER_ID_REFUSED }] }),
      );

    await submitConfigured(onSubmit);
    await userEvent.type(await screen.findByLabelText(/Google Drive Folder ID/), "1");

    expect(screen.getByLabelText(/Google Drive Folder ID/)).not.toHaveAttribute("aria-invalid");
    expect(screen.queryByText(FOLDER_ID_REFUSED)).toBeNull();
  });

  it("does not act on a submission the reader walked away from", async () => {
    // The X and Escape stay live while a create is pending, so the dialog can
    // be dismissed and reopened before the answer arrives. Marking an input on
    // the strength of that answer would send somebody to fix a field they never
    // filled in - and the step it jumps to has no connector chosen, so it draws
    // nothing at all.
    let refuse!: (reason: unknown) => void;
    const pending = new Promise<void>((_resolve, reject) => {
      refuse = reject;
    });
    const view = await submitConfigured(vi.fn().mockReturnValue(pending));

    view.rerender(wizard(vi.fn(), false));
    view.rerender(wizard(vi.fn(), true));

    await act(async () => {
      refuse(refusal({ fields: [{ field: "config.folder_id", message: FOLDER_ID_REFUSED }] }));
      await pending.catch(() => undefined);
    });

    expect(screen.getByLabelText("Source name")).toBeVisible();
    expect(screen.queryByText(FOLDER_ID_REFUSED)).toBeNull();
    // Said rather than swallowed: a create that failed is not nothing.
    expect(toast.error).toHaveBeenCalledWith("Invalid connector config");
  });
});

describe("the credential step", () => {
  /** Walk as far as the credential step, with a connector that needs one. */
  async function openCredentialStep() {
    const view = withQuery(wizard(vi.fn()));
    await userEvent.type(screen.getByLabelText("Source name"), "Engineering docs");
    await userEvent.click(screen.getByRole("button", { name: /Google Drive/ }));
    await userEvent.click(screen.getByRole("button", { name: /Continue/ }));
    await userEvent.type(screen.getByLabelText(/Google Drive Folder ID/), "1AbC");
    await userEvent.click(screen.getByRole("button", { name: /Continue/ }));
    return view;
  }

  it("does not advance until a credential is chosen", async () => {
    // A source with no credential is one that cannot sync, and the connectors
    // have no deployment-wide fallback to run on instead - so the wizard asks
    // here rather than creating a row that fails in a worker.
    await openCredentialStep();

    expect(await screen.findByLabelText(/Vault credential/)).toBeVisible();
    expect(screen.getByRole("button", { name: /Continue/ })).toBeDisabled();

    await pickTheCredential();

    expect(screen.getByRole("button", { name: /Continue/ })).toBeEnabled();
  });

  it("sends the credential's id and no credential of its own", async () => {
    // The whole of #937 on this surface: what leaves the browser is a reference,
    // not a service account JSON pasted into a config field.
    const onSubmit = vi.fn().mockResolvedValue(undefined);
    await submitConfigured(onSubmit);

    const sent = onSubmit.mock.calls[0]?.[0] as SyncSourceCreate;
    expect(sent.secret_id).toBe("secret-1");
    expect(sent.config).not.toHaveProperty("service_account_json");
  });

  it("offers only the kind this connector authenticates with", async () => {
    // An S3 key pair is in the same vault and cannot sign a Drive request. Two
    // credentials, one offered.
    serve({
      secrets: [
        DRIVE_CREDENTIAL,
        { ...DRIVE_CREDENTIAL, id: "secret-2", name: "Backups key", kind: "aws_credentials" },
      ],
    });
    await openCredentialStep();

    await userEvent.click(await screen.findByLabelText(/Vault credential/));

    expect(await screen.findByRole("option", { name: /Drive service account/ })).toBeVisible();
    expect(screen.queryByRole("option", { name: /Backups key/ })).toBeNull();
  });

  it("says the vault holds none rather than showing an empty picker", async () => {
    // An empty picker with nowhere to go is the dead end this step replaced.
    serve({ secrets: [] });
    await openCredentialStep();

    expect(await screen.findByText(/holds no credential/)).toBeVisible();
    expect(screen.getByRole("link", { name: /Open the Vault/ })).toBeVisible();
    expect(screen.getByRole("button", { name: /Continue/ })).toBeDisabled();
  });

  it("says who has to choose when the reader cannot see the vault", async () => {
    // Not an empty picker: a member without `secrets:view` is not looking at an
    // organization with no credentials.
    serve({ permissions: [] });
    await openCredentialStep();

    expect(await screen.findByText(/cannot see this organization's credentials/)).toBeVisible();
    expect(screen.queryByLabelText(/Vault credential/)).toBeNull();
  });
  it("says the vault could not be read rather than that it is empty", async () => {
    // The two look identical in `secrets`, and they mean opposite things: one
    // sends somebody to the Vault to add a duplicate, the other to try again.
    vi.mocked(apiClient.get).mockImplementation(async (path: string) => {
      if (path === "/secrets") throw new Error("502 Bad Gateway");
      if (path === "/me/permissions")
        return {
          organization_id: "org-1",
          role: "builder",
          is_app_admin: false,
          permissions: [{ permission: "secrets:view", scope: "all" }],
        };
      return {};
    });
    await openCredentialStep();

    expect(await screen.findByText(/vault could not be read/)).toBeVisible();
    expect(screen.queryByText(/holds no credential/)).toBeNull();
    expect(screen.getByRole("button", { name: /Continue/ })).toBeDisabled();
  });
});
