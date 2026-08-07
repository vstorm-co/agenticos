import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { SyncSourceWizard } from "./sync-source-wizard";
import type { ConnectorInfo, SyncSourceCreate } from "@/lib/rag-api";

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
