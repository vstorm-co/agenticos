import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { toast } from "sonner";

import { SyncSourceWizard } from "./sync-source-wizard";
import { ApiError } from "@/lib/api-error";
import type { ConnectorInfo, SyncSourceCreate } from "@/lib/rag-api";

vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

beforeEach(() => {
  vi.mocked(toast.error).mockClear();
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
};

/** Walk the wizard from its first step to the last, where the collection is chosen. */
async function openScheduleStep(props: {
  collections: { name: string }[];
  defaultCollection?: string;
  onSubmit: (data: SyncSourceCreate) => void;
}) {
  render(
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
  await userEvent.click(screen.getByRole("button", { name: /Continue/ }));
  await screen.findByText("Sync mode");
}

describe("the sync wizard's target collection", () => {
  it("is on screen, and starts on the one the caller suggested", async () => {
    await openScheduleStep({
      collections: [{ name: "handbook" }, { name: "contracts" }],
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
      collections: [{ name: "handbook" }, { name: "contracts" }],
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
      collections: [{ name: "org_handbook" }],
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
    service_account_json: { type: "textarea", required: true, label: "Service Account JSON" },
    folder_id: { type: "string", required: true, label: "Google Drive Folder ID" },
    include_subfolders: { type: "boolean", required: false, label: "Include subfolders" },
  },
};

const FOLDER_ID_REFUSED = "A Google Drive folder ID may contain only letters, digits, '-' and '_'.";

/** The 400 the create route answers, envelope and all. */
function refusal(details: Record<string, unknown>): ApiError {
  return new ApiError(400, "Invalid connector config", {
    error: { code: "BAD_REQUEST", message: "Invalid connector config", details },
  });
}

/** Fill the configure step in full and press Create source on the step after it. */
async function submitConfigured(onSubmit: (data: SyncSourceCreate) => Promise<void>) {
  render(
    <SyncSourceWizard
      open
      onOpenChange={vi.fn()}
      connectors={[GDRIVE]}
      collections={[{ name: "handbook" }]}
      defaultCollection="handbook"
      onSubmit={onSubmit}
    />,
  );
  await userEvent.type(screen.getByLabelText("Source name"), "Engineering docs");
  await userEvent.click(screen.getByRole("button", { name: /Google Drive/ }));
  await userEvent.click(screen.getByRole("button", { name: /Continue/ }));
  await userEvent.type(screen.getByLabelText(/Service Account JSON/), "{{}}");
  await userEvent.type(screen.getByLabelText(/Google Drive Folder ID/), "x' in parents");
  await userEvent.click(screen.getByRole("button", { name: /Continue/ }));
  await userEvent.click(screen.getByRole("button", { name: /Create source/ }));
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
    // The other required field is not implicated, and saying so would send
    // somebody to rewrite a credential that was accepted.
    expect(screen.getByLabelText(/Service Account JSON/)).not.toHaveAttribute("aria-invalid");
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
        refusal({
          fields: [{ field: "config.service_account_json", message: "That is not a service key." }],
        }),
      );

    await submitConfigured(onSubmit);
    expect(await screen.findByLabelText(/Google Drive Folder ID/)).toHaveAttribute(
      "aria-invalid",
      "true",
    );

    await userEvent.type(screen.getByLabelText(/Google Drive Folder ID/), "1AbC");
    await userEvent.click(screen.getByRole("button", { name: /Continue/ }));
    await userEvent.click(screen.getByRole("button", { name: /Create source/ }));

    expect(await screen.findByLabelText(/Service Account JSON/)).toHaveAttribute(
      "aria-invalid",
      "true",
    );
    expect(screen.getByLabelText(/Google Drive Folder ID/)).not.toHaveAttribute("aria-invalid");
    expect(screen.queryByText(FOLDER_ID_REFUSED)).toBeNull();
  });
});
