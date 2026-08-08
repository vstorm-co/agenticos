import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { FileCard, PendingFileCard } from "./file-card";

/**
 * One card for a file, wherever a file is shown without being opened.
 *
 * There were three - a pill in the transcript with a generic document glyph, a tile
 * in the Files panel with a truncated name, and the composer's card with an excerpt -
 * so the same file looked like three things on one screen. This is #136's problem one
 * layer out: that change unified what *opening* a file means and left showing one
 * alone.
 */
describe("a file on a card", () => {
  it("leads with the name, in full", () => {
    // Wrapped rather than truncated: the name is how somebody checks they attached
    // the right thing, and `_allegro_system_prompt…` answers nothing.
    render(<FileCard name="Hiszpanski_od_zera_do_B1.xlsx" />);

    expect(screen.getByText("Hiszpanski_od_zera_do_B1.xlsx")).toBeVisible();
  });

  it("says what it is and how big, on one line", () => {
    render(<FileCard name="report.csv" size={2048} />);

    expect(screen.getByText("CSV · 2.0 KB")).toBeVisible();
  });

  it("says what it is when nobody measured it", () => {
    // A transcript attachment has a name and a type and no size; a listing entry for
    // a directory has no size either. Neither is a failure worth a blank line.
    render(<FileCard name="notes.md" />);

    expect(screen.getByText("MD")).toBeVisible();
  });

  it("takes a label for a type the suffix cannot give", () => {
    // The paste in the composer: named for a file nobody chose, so the card says what
    // it actually was.
    render(<FileCard name="pasted-2026-08-08.txt" typeLabel="PASTED" size={48_000} />);

    expect(screen.getByText("PASTED · 46.9 KB")).toBeVisible();
  });

  it("shows the first lines when a surface has them", () => {
    render(<FileCard name="mockup.html" preview={'<!DOCTYPE html>\n<html lang="pl">'} />);

    expect(screen.getByText(/<!DOCTYPE html>/)).toBeVisible();
  });

  it("shows its mark when there is no preview to show", () => {
    // The band is reserved either way: cards of two heights in one strip read as two
    // kinds of thing.
    const { container } = render(<FileCard name="handbook.pdf" />);

    expect(container.querySelectorAll("svg").length).toBeGreaterThan(1);
  });

  it("opens when a surface says what opening means", async () => {
    const onOpen = vi.fn();
    render(<FileCard name="report.csv" onOpen={onOpen} />);

    await userEvent.click(screen.getByRole("button", { name: /report\.csv/ }));

    expect(onOpen).toHaveBeenCalled();
  });

  it("is not a button where there is nothing to open", () => {
    // The composer's cards: the file is not stored anywhere a viewer could reach yet.
    render(<FileCard name="report.csv" />);

    expect(screen.queryByRole("button")).toBeNull();
  });

  it("offers removal always, not on hover", async () => {
    // A hover-only control is unreachable on a touch screen and invisible to anybody
    // who does not think to try.
    const onRemove = vi.fn();
    render(<FileCard name="report.csv" onRemove={onRemove} removeLabel="Remove report.csv" />);

    await userEvent.click(screen.getByRole("button", { name: "Remove report.csv" }));

    expect(onRemove).toHaveBeenCalled();
  });

  it("says a file is on its way, in the place it will occupy", () => {
    // In place rather than beside: a dashed box after the finished cards made the
    // first one appear to move when a second file was dropped.
    render(<PendingFileCard name="big.csv" size={5_000_000} />);

    expect(screen.getByText("big.csv")).toBeVisible();
    expect(screen.getByText(/4\.8 MB/)).toBeVisible();
  });
});
