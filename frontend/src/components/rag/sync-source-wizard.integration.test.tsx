import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { SyncSourceWizard } from "./sync-source-wizard";
import type { ConnectorInfo } from "@/lib/rag-api";

/**
 * The target-collection picker on the wizard's last step.
 *
 * Two collections can carry the same label - a label is a display name and
 * nothing enforces otherwise - so each row qualifies its label with the
 * physical name. That qualifier is a comparison against the other rows, and
 * Radix draws the selected item's `ItemText` in the closed trigger: in
 * `children` it followed the choice out of the list, where it disambiguated
 * a set of one.
 *
 * **Nothing in the product reaches this control yet, and that is #434.** The
 * picker needs `defaultCollection` absent and `collections` non-empty; all
 * three call sites pass a truthy `defaultCollection` or an empty list, and none
 * passes `label` at all. So this file mounts the wizard the way none of them
 * do. The fix under test is correct and currently latent - when #434 is decided
 * (delete the control, or reach it and pass `label: kb.name`), this file is
 * what changes with it.
 */

const CONNECTOR: ConnectorInfo = {
  type: "gdrive",
  name: "Google Drive",
  enabled: true,
  // Nothing required, so the configure step can be walked straight past to the
  // schedule step the picker lives on.
  config_schema: {},
};

/** Walk the wizard to its last step, where the collection is chosen. */
async function openScheduleStep(collections: { name: string; label?: string }[]) {
  render(
    <SyncSourceWizard
      open
      onOpenChange={vi.fn()}
      connectors={[CONNECTOR]}
      collections={collections}
      onSubmit={vi.fn()}
    />,
  );

  await userEvent.type(screen.getByLabelText("Source name"), "Engineering docs");
  await userEvent.click(screen.getByRole("button", { name: /Google Drive/ }));
  await userEvent.click(screen.getByRole("button", { name: /Continue/ }));
  await userEvent.click(screen.getByRole("button", { name: /Continue/ }));
}

describe("the target collection picker", () => {
  it("qualifies a label with the collection's own name, in the list", async () => {
    // Which is the whole point of drawing it: two "Docs" are told apart by the
    // collection each is stored under.
    await openScheduleStep([
      { name: "eng_docs", label: "Docs" },
      { name: "sales_docs", label: "Docs" },
    ]);

    await userEvent.click(screen.getByRole("combobox"));

    const rows = screen.getAllByRole("option", { name: "Docs" });
    expect(rows).toHaveLength(2);
    expect(within(rows[0]!).getByText("(eng_docs)")).toBeVisible();
    expect(within(rows[1]!).getByText("(sales_docs)")).toBeVisible();
  });

  it("does not repeat the qualifier on the closed trigger", async () => {
    await openScheduleStep([
      { name: "eng_docs", label: "Docs" },
      { name: "sales_docs", label: "Docs" },
    ]);

    const picker = screen.getByRole("combobox");
    await userEvent.click(picker);
    await userEvent.click(screen.getAllByRole("option", { name: "Docs" })[0]!);

    expect(picker).toHaveTextContent("Docs");
    expect(picker).not.toHaveTextContent("eng_docs");
  });

  it("falls back to the collection's name where it has no label", async () => {
    // A row reading only "(eng_docs)" beside nothing would be a label that
    // failed to load rather than a collection that never had one.
    await openScheduleStep([{ name: "eng_docs" }]);

    await userEvent.click(screen.getByRole("combobox"));

    const only = screen.getByRole("option", { name: "eng_docs" });
    expect(within(only).queryByText("(eng_docs)")).toBeNull();
  });
});
