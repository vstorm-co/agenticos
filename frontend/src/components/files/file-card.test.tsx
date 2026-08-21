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

describe("cards in a strip beside each other", () => {
  it("reserves two lines for the name whether it needs one or two", () => {
    // `report.pdf` beside `1773207574972.jpg` was two cards of two heights in one
    // strip, which reads as two kinds of thing. The band below was already fixed
    // for exactly this reason; the name was not.
    render(<FileCard name="a.pdf" />);

    expect(screen.getByTitle("a.pdf")).toHaveClass("h-8", "line-clamp-2");
  });

  it("keeps the whole name reachable when it clamps", () => {
    const long = "Jak_zdobyc_przyjaciol_i_zjednac_sobie_ludzi_wydanie_rozszerzone.pdf";

    render(<FileCard name={long} />);

    expect(screen.getByTitle(long)).toBeInTheDocument();
  });

  it("draws the picture for an image it was given an address for", () => {
    // A grey glyph standing in for a photograph is the one case where the card
    // knows enough to show the thing itself.
    render(<FileCard name="conf.jpg" mimeType="image/jpeg" imageUrl="/api/files/f-1" />);

    expect(screen.getByAltText("conf.jpg")).toBeInTheDocument();
  });
});

describe("the chip a composer draws", () => {
  it("is one row with the name on one line, not a preview band", () => {
    // A file in the composer is pending confirmation, not content being read:
    // what is wanted is whether it is the right file, how big, and how to remove
    // it. Twenty tiles is seven rows of composer; twenty chips is one row (#927).
    const { container } = render(<FileCard name="report.csv" size={12} compact />);

    const chip = container.firstElementChild!;

    expect(chip.className).toContain("items-center");
    expect(chip.className).not.toContain("flex-col");
    expect(screen.getByTitle("report.csv")).toBeInTheDocument();
  });

  it("gives remove its own hit area at chip height", () => {
    // The tile's × is a 12px glyph in a corner. At chip height the card is about
    // the size that corner used to be.
    render(<FileCard name="report.csv" compact onRemove={vi.fn()} />);

    const remove = screen.getByRole("button", { name: /report\.csv/ });

    expect(remove.className).toContain("h-6");
    expect(remove.className).toContain("w-6");
  });

  it("draws a thumbnail in the chip for an image", () => {
    render(<FileCard name="conf.jpg" mimeType="image/jpeg" imageUrl="/api/files/f-1" compact />);

    expect(screen.getByAltText("conf.jpg")).toBeInTheDocument();
  });

  it("uploads at the size the finished ones are", () => {
    // A tile among chips would make the row jump when the upload lands.
    const { container } = render(<PendingFileCard name="big.csv" size={2048} compact />);

    expect(container.firstElementChild!.className).toContain("items-center");
    expect(screen.getByText(/Uploading/)).toBeVisible();
  });
});
