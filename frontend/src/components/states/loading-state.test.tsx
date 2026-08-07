import { readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";

import { LoadingState } from "./loading-state";

/** Every placeholder bar in a skeleton, whatever variant drew it. */
function bars(container: HTMLElement): Element[] {
  return Array.from(container.querySelectorAll(".animate-pulse"));
}

describe("LoadingState", () => {
  it("draws a shape when no variant is given", () => {
    // The whole bug: a caller that forgets the prop used to get three dots.
    // Whatever the default becomes, it has to have a shape.
    const { container } = render(<LoadingState />);

    expect(screen.getByRole("status", { name: /loading/i })).toBeInTheDocument();
    expect(bars(container).length).toBeGreaterThan(1);
  });

  it("announces itself once, not once per bar", () => {
    render(<LoadingState variant="skeleton-cards" rows={4} />);

    expect(screen.getAllByRole("status")).toHaveLength(1);
  });

  it("renders one row per row for a list", () => {
    const { container } = render(<LoadingState variant="skeleton-list" rows={3} />);

    expect(container.querySelectorAll(".rounded-xl.border")).toHaveLength(3);
  });

  it("renders a card grid at the grid the pages use", () => {
    const { container } = render(<LoadingState variant="skeleton-cards" rows={6} />);
    const grid = screen.getByRole("status");

    expect(grid.className).toContain("grid");
    expect(grid.className).toContain("sm:grid-cols-2");
    expect(container.querySelectorAll(".rounded-xl.border")).toHaveLength(6);
  });

  it("renders a tile grid with an icon slot per tile", () => {
    const { container } = render(<LoadingState variant="skeleton-tiles" rows={2} />);

    expect(container.querySelectorAll(".rounded-xl.border")).toHaveLength(2);
    // The leading icon square is what distinguishes a tile from a text card.
    expect(container.querySelectorAll(".h-9.w-9")).toHaveLength(2);
  });

  it("renders a table with the columns it was asked for", () => {
    render(<LoadingState variant="skeleton-table" columns={6} rows={4} />);

    expect(screen.getAllByRole("columnheader")).toHaveLength(6);
    // Header row plus body rows.
    expect(screen.getAllByRole("row")).toHaveLength(5);
    expect(screen.getAllByRole("cell")).toHaveLength(24);
  });

  it("defaults a table to five columns", () => {
    render(<LoadingState variant="skeleton-table" rows={1} />);

    expect(screen.getAllByRole("columnheader")).toHaveLength(5);
  });

  it("renders a panel as one card with inner rows", () => {
    const { container } = render(<LoadingState variant="skeleton-panel" rows={3} />);

    expect(screen.getByRole("status").className).toContain("rounded-xl");
    expect(container.querySelectorAll(".rounded-md.border")).toHaveLength(3);
  });

  it("renders one tile per stat", () => {
    const { container } = render(<LoadingState variant="stats" rows={3} />);

    expect(container.querySelectorAll(".rounded-xl.border")).toHaveLength(3);
  });

  it("picks a calm count per variant when the caller does not", () => {
    // Not a magic-number test: the point is that every variant has a default,
    // so a caller who knows nothing about the data still gets a full shape.
    const { container: list } = render(<LoadingState variant="skeleton-list" />);
    const { container: cards } = render(<LoadingState variant="skeleton-cards" />);

    expect(list.querySelectorAll(".rounded-xl.border")).toHaveLength(4);
    expect(cards.querySelectorAll(".rounded-xl.border")).toHaveLength(6);
  });

  it("lets a page override the grid it was given", () => {
    // How a two-up page reconciles with a three-up variant instead of forking one.
    render(<LoadingState variant="skeleton-tiles" className="lg:grid-cols-2" />);

    const grid = screen.getByRole("status");
    expect(grid.className).toContain("lg:grid-cols-2");
    expect(grid.className).not.toContain("lg:grid-cols-3");
  });

  it("pulses, so reduced motion can flatten it globally", () => {
    // `globals.css` neutralizes every animation under prefers-reduced-motion;
    // using the standard utility is what opts these into that.
    const { container } = render(<LoadingState variant="skeleton-list" rows={1} />);

    expect(bars(container).length).toBeGreaterThan(0);
  });
});

/**
 * The regression net.
 *
 * The dots were never chosen - they were the default, and thirteen call sites
 * inherited them. Asserting on the component alone would not have caught that,
 * so this reads the source: no page may ask for a shapeless wait, and the
 * variant that provided one may not come back.
 */
describe("no page asks for a shapeless wait", () => {
  const SRC = join(__dirname, "..", "..");

  function sourceFiles(dir: string): string[] {
    return readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
      const path = join(dir, entry.name);
      if (entry.isDirectory()) return sourceFiles(path);
      return /\.tsx?$/.test(entry.name) && !entry.name.includes(".test.") ? [path] : [];
    });
  }

  it("mentions dot-pulse nowhere in src/", () => {
    const offenders = sourceFiles(SRC).filter((file) =>
      readFileSync(file, "utf8").includes("dot-pulse"),
    );

    expect(offenders).toEqual([]);
  });

  it("renders no bare shared LoadingState in a page or panel", () => {
    // A bare `<LoadingState />` still gets a skeleton, but it gets a generic
    // one - the shape is the caller's decision, so it has to be made. Scoped to
    // files that import the shared component: `files/file-content.tsx` reaches for
    // `Skeleton` directly, sized to the body it is standing in for.
    const offenders = sourceFiles(SRC).filter((file) => {
      const source = readFileSync(file, "utf8");
      const importsShared =
        /import\s*\{[^}]*\bLoadingState\b[^}]*\}\s*from\s*"@\/components\/states"/.test(source);
      return importsShared && /<LoadingState\s*\/>/.test(source);
    });

    expect(offenders).toEqual([]);
  });
});
