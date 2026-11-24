import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type { UnsavedCopy } from "@/lib/unsaved-copies";
import { DEFAULT_SCORING } from "@/lib/scoring";
import { EMPTY_DRAFT } from "./case-form";
import { UnsavedCopiesBanner } from "./unsaved-copies-banner";

const NOW = new Date().toISOString();

function copy(place: string, value: unknown, base = 4): UnsavedCopy {
  return { key: `k:${place}`, place, base, savedAt: NOW, value };
}

const caseCopy = (input: string, extra: object = {}) => ({
  draft: { ...EMPTY_DRAFT, input, ...extra },
  json: null,
});

function banner(copies: UnsavedCopy[]) {
  const onRestore = vi.fn();
  const onDiscard = vi.fn();
  render(
    <UnsavedCopiesBanner copies={copies} latest={4} onRestore={onRestore} onDiscard={onDiscard} />,
  );
  return { onRestore, onDiscard };
}

const row = (text: RegExp) => screen.getByText(text).closest("li")!;

describe("UnsavedCopiesBanner", () => {
  it("offers back each edit made on the current version, and discarding it", async () => {
    const grading = copy("grading", { draft: DEFAULT_SCORING, defaults: [] });
    const fresh = copy("case:new", caseCopy("Where is my parcel?"));
    const { onRestore, onDiscard } = banner([grading, fresh]);

    expect(screen.getByRole("region", { name: "Restore your unsaved changes?" })).toBeVisible();
    await userEvent.click(
      within(row(/^Grading, changed/)).getByRole("button", { name: "Restore" }),
    );
    expect(onRestore).toHaveBeenCalledWith(grading);
    await userEvent.click(
      within(row(/^A new case, written/)).getByRole("button", { name: "Discard" }),
    );
    expect(onDiscard).toHaveBeenCalledWith(fresh);
  });

  it("names a case by its question, cut short when it is long", () => {
    banner([copy("case:c1", caseCopy(`  ${"Why ".repeat(30)} `))]);
    expect(screen.getByText(/^The case “(Why ){20}…”, changed/)).toBeInTheDocument();
  });

  it("offers only Discard for an edit the dataset has moved past, showing what it was", async () => {
    banner([
      copy("case:c1", caseCopy("Refund window?", { reference_answer: "30 days" }), 2),
      copy("case:c2", { draft: EMPTY_DRAFT, json: '{"input": "As JSON"}' }, 3),
      copy(
        "case:c3",
        caseCopy("Unfinished", { checks: [{ type: "contains", value: "", rest: {} }] }),
        3,
      ),
      copy("grading", { draft: { checks: { enabled: false } }, defaults: [] }, 1),
    ]);

    expect(screen.queryByRole("button", { name: "Restore" })).toBeNull();
    expect(
      screen.getByText(
        "These changes were made on version 2; the dataset has moved on to version 4.",
      ),
    ).toBeInTheDocument();
    const shown = screen.getAllByText("Show the changes");
    expect(shown).toHaveLength(4);
    for (const summary of shown) await userEvent.click(summary);
    expect(screen.getByText("30 days")).toBeInTheDocument();
    expect(screen.getByText('{"input": "As JSON"}')).toBeInTheDocument();
    // A draft that would not save as it stands is shown as written.
    expect(within(row(/^The case “Unfinished”/)).getAllByText(/Unfinished/)).toHaveLength(2);
    expect(within(row(/^Grading, changed/)).getByText(/checks/)).toBeInTheDocument();
  });
});
